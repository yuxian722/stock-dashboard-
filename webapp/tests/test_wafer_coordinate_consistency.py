"""Regression test locking in the invariant from bingomap/CLAUDE.md's
"wafer座標系統核心規則" section: every place on ①補資料/②誤吸偏移頁 that
shows a coordinate to the user (hover tooltip, ruler labels) must always
show the die's real, unrotated wafer_xy — never the current angle's
rotated display coordinate.

2026/09/03: this exact invariant was broken twice in one day (the hover
tooltip, then separately the ruler labels) despite both being documented
in CLAUDE.md as soon as found — writing the rule down did not stop it
from being violated again by a later, unrelated change, because nothing
actually re-checked it. This test exists so the check doesn't depend on
a human (or Claude) remembering to consult CLAUDE.md before touching
this code again: any future change that reintroduces the mismatch fails
this test immediately.

Uses real fixture data (the same T3DC94 substrate + same-lot T3_DA62.frm
stand-in used throughout the investigation that found these bugs) so the
test exercises the actual production code path, not a synthetic case.

Requires Playwright + a Chromium browser, which is NOT a declared project
dependency (this tool's actual users don't need it to run the app) — so
this whole module is skipped, not failed, when playwright isn't
installed. It's a development-time regression guard for whoever is
actively changing the wafer-rotation code, not part of the app's own
runtime requirements.
"""
import shutil
import threading
from pathlib import Path

import pytest

playwright_sync_api = pytest.importorskip("playwright.sync_api")
sync_playwright = playwright_sync_api.sync_playwright

from werkzeug.serving import make_server

FIXTURES = Path(__file__).parent.parent.parent / "bingomap" / "tests" / "fixtures"
REAL_FRM = FIXTURES / "8P065800A1_T3_DA62.frm"
REAL_STRATE = FIXTURES / "2130_V32AWCW_Z26306101253_20260814064943.strate"
# Die #1 in REAL_STRATE — the exact position whose disappearance/misplacement
# triggered this whole investigation. See bingomap/CLAUDE.md.
KNOWN_DIE_X, KNOWN_DIE_Y = 23, 48

ANGLES = ["0", "90", "180", "270"]


@pytest.fixture(scope="module")
def frm_root(tmp_path_factory):
    """A fake FRM_PATH root containing the real T3_DA62.frm fixture at the
    path frm_file_path() expects for LotNo=8P065800A1/Barcode=T3DA62.
    Passed explicitly via the #frm_path field in each test (not via the
    BINGOMAP_FRM_PATH env var) since webapp.app.DEFAULT_FRM_PATH is only
    ever read once, at module import time — which may already have
    happened via another test module in the same pytest session before
    this fixture gets a chance to set the env var."""
    root = tmp_path_factory.mktemp("frm_root")
    dest_dir = root / "8P065800A1" / "T3"
    dest_dir.mkdir(parents=True)
    shutil.copy(REAL_FRM, dest_dir / "DA62")
    return str(root) + "\\"


@pytest.fixture(scope="module")
def live_server():
    """Runs the real Flask app on a real TCP port (not the Flask test
    client) so Playwright can drive a real browser against it — needed
    because this test exercises client-side JS (rotation math, DOM
    rendering), not just the HTTP API."""
    from webapp.app import app

    server = make_server("127.0.0.1", 0, app)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture(scope="module")
def browser():
    import os

    # This session's sandbox pre-installs Chromium outside Playwright's own
    # managed browser cache (see the environment notes) — fall back to the
    # default (Playwright-managed) browser when that path doesn't exist, so
    # this test still works in an environment where `playwright install`
    # was run normally instead.
    launch_kwargs = {}
    sandbox_chromium = "/opt/pw-browsers/chromium"
    if os.path.exists(sandbox_chromium):
        launch_kwargs["executable_path"] = sandbox_chromium
    with sync_playwright() as p:
        b = p.chromium.launch(**launch_kwargs)
        yield b
        b.close()


def _display_xy_for_raw(page, raw_x, raw_y, grid_selector, bounds_var, angle_var, mirror_var):
    return page.evaluate(
        """([sel, rx, ry, boundsVar, angleVar, mirrorVar]) => {
            const cells = document.querySelectorAll(sel + ' .wafer-cell');
            for (const c of cells) {
                const x = parseInt(c.dataset.x, 10), y = parseInt(c.dataset.y, 10);
                const rawBounds = eval(boundsVar);
                const angle = eval(angleVar);
                const mirror = eval(mirrorVar);
                const raw = unrotateWaferPoint(x, y, rawBounds, angle, mirror);
                if (raw.x === rx && raw.y === ry) return {x, y};
            }
            return null;
        }""",
        [grid_selector, raw_x, raw_y, bounds_var, angle_var, mirror_var],
    )


def _ruler_labels_for_cell(page, grid_id, display_x, display_y):
    """Reads the ruler's column header label and row label for the given
    display-coordinate cell, exactly as a human visually counting along
    the ruler would."""
    return page.evaluate(
        """([gridId, dx, dy]) => {
            const grid = document.getElementById(gridId);
            const rows = Array.from(grid.querySelectorAll('.wafer-row'));
            const headerCells = Array.from(rows[0].children);
            let colIndex = -1;
            for (const r of rows.slice(1)) {
                const cells = Array.from(r.children);
                const idx = cells.findIndex(c => c.dataset && c.dataset.x === String(dx) && c.dataset.y === String(dy));
                if (idx >= 0) { colIndex = idx; break; }
            }
            const colLabel = colIndex >= 0 ? headerCells[colIndex].textContent : null;
            let rowLabel = null;
            for (const r of rows.slice(1)) {
                const cells = Array.from(r.children);
                if (cells.some(c => c.dataset && c.dataset.x === String(dx) && c.dataset.y === String(dy))) {
                    rowLabel = cells[0].textContent;
                    break;
                }
            }
            return {colLabel, rowLabel};
        }""",
        [grid_id, display_x, display_y],
    )


def test_supplement_page_ruler_and_tooltip_agree_with_raw_wafer_xy_at_every_angle(live_server, browser, frm_root):
    page = browser.new_page(viewport={"width": 1900, "height": 1200})
    page.goto(live_server + "/")
    page.set_input_files("#template-file", str(REAL_STRATE))
    page.click("#btn-load-template")
    page.wait_for_timeout(300)
    page.fill("#frm_lot_no", "8P065800A1")
    page.fill("#frm_barcode_id", "T3DA62")
    page.fill("#frm_path", frm_root)
    page.click("#btn-load-frm")
    page.wait_for_selector("#frm-status.ok", timeout=10000)

    for angle in ANGLES:
        page.select_option("#wafer-angle", angle)
        page.wait_for_timeout(150)

        d = _display_xy_for_raw(
            page, KNOWN_DIE_X, KNOWN_DIE_Y, "#wafer-grid",
            "waferRawBoundsByPanel[0]", "waferAngleByPanel[0]", "waferMirrorByPanel[0]",
        )
        assert d is not None, f"angle={angle}: raw ({KNOWN_DIE_X}:{KNOWN_DIE_Y}) not found in rendered grid at all"

        cell = page.query_selector(f'#wafer-grid [data-x="{d["x"]}"][data-y="{d["y"]}"]')
        cell.dispatch_event("mouseover")
        hover_text = page.inner_text("#wafer-hover-status")
        assert f"{KNOWN_DIE_X}:{KNOWN_DIE_Y}" in hover_text, (
            f"angle={angle}: hover tooltip showed {hover_text!r}, expected it to contain "
            f"{KNOWN_DIE_X}:{KNOWN_DIE_Y}"
        )

        ruler = _ruler_labels_for_cell(page, "wafer-grid", d["x"], d["y"])
        ruler_values = {ruler["colLabel"], ruler["rowLabel"]}
        assert ruler_values == {str(KNOWN_DIE_X), str(KNOWN_DIE_Y)}, (
            f"angle={angle}: ruler showed column={ruler['colLabel']!r} row={ruler['rowLabel']!r}, "
            f"expected these two values to be exactly {{{KNOWN_DIE_X}, {KNOWN_DIE_Y}}} "
            f"(same as the hover tooltip) — ruler and tooltip must never disagree"
        )

    page.close()


def test_mispick_page_ruler_and_tooltip_agree_with_raw_wafer_xy_at_every_angle(live_server, browser, frm_root):
    page = browser.new_page(viewport={"width": 1900, "height": 1200})
    page.goto(live_server + "/mispick")
    page.fill("#mp_frm_lot_no", "8P065800A1")
    page.fill("#mp_frm_barcode_id", "T3DA62")
    page.fill("#mp_frm_path", frm_root)
    page.fill("#mp_wafer_ring", "T3DC94")
    page.click("#mp-btn-preview-wafer")
    page.wait_for_selector("#mp-preview-status:has-text('已載入')", timeout=10000)

    for angle in ANGLES:
        page.select_option("#mp-wafer-angle", angle)
        page.wait_for_timeout(150)

        # mispick.js's renderOneWaferGrid() cells carry no dataset.x/y (only
        # app.js's grid does) — the cell's own `title` (already asserted to
        # be the raw coordinate by the hover-tooltip fix) is the only way to
        # locate it, then its DOM position (which row, which column within
        # that row) tells us which ruler cells to compare against.
        found = page.evaluate(
            """(needle) => {
                const grid = document.getElementById('mp-wafer-grid');
                const rows = Array.from(grid.querySelectorAll('.wafer-row'));
                for (let ri = 1; ri < rows.length; ri++) {
                    const cells = Array.from(rows[ri].children);
                    for (let ci = 1; ci < cells.length; ci++) {
                        if (cells[ci].title && cells[ci].title.includes(needle)) {
                            return {
                                title: cells[ci].title,
                                rowLabel: cells[0].textContent,
                                colLabel: Array.from(rows[0].children)[ci].textContent,
                            };
                        }
                    }
                }
                return null;
            }""",
            f"{KNOWN_DIE_X}:{KNOWN_DIE_Y}",
        )
        assert found is not None, (
            f"angle={angle}: no cell's title contains {KNOWN_DIE_X}:{KNOWN_DIE_Y} — "
            f"either the hover-tooltip fix regressed, or the die isn't rendered at all"
        )

        ruler_values = {found["colLabel"], found["rowLabel"]}
        assert ruler_values == {str(KNOWN_DIE_X), str(KNOWN_DIE_Y)}, (
            f"angle={angle}: cell title said {found['title']!r} but ruler showed "
            f"column={found['colLabel']!r} row={found['rowLabel']!r} — expected these two "
            f"values to be exactly {{{KNOWN_DIE_X}, {KNOWN_DIE_Y}}}, same as the title — "
            f"ruler and hover must never disagree"
        )

    page.close()
