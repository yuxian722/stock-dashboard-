"""2026/10/28: simplified standalone viewer ("執行檔點進去就開啟", upload a
SECS log and see each substrate's own BINGO MAP grid before downloading).
Locks in the extract endpoint against the same real gold-edge-down fixture
bingomap/tests/test_blank_generator_gold_edge_orientation.py already
verified — this test doesn't re-derive the real gap positions, it reuses
that module's already-confirmed REAL_GAP_POSITIONS constant so a
regression in either place shows up as a mismatch, not two independently
-guessable "expected" sets."""
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from bingomap.tests.test_blank_generator_gold_edge_orientation import (  # noqa: E402
    REAL_GAP_POSITIONS,
)
from webapp.simple_bingo_viewer import app  # noqa: E402

FIXTURE = Path(__file__).parent.parent.parent / "bingomap" / "tests" / "fixtures" / "BAA0820260814_07_Z26306101253.log"


def test_extract_real_gold_edge_down_fixture_matches_known_gaps():
    client = app.test_client()
    log_base64 = base64.b64encode(FIXTURE.read_bytes()).decode("ascii")

    res = client.post("/api/simple_bingo/extract", json={"log_base64": log_base64})
    assert res.status_code == 200
    substrates = res.get_json()["substrates"]
    assert len(substrates) == 1

    s = substrates[0]
    assert s["substrate_id"] == "Z26306101253"
    assert s["num_dies"] == 299
    assert (s["min_col"], s["max_col"], s["min_row"], s["max_row"]) == (0, 27, 0, 10)

    present = {(p["col"], p["row"]) for p in s["positions"]}
    full_grid = {(c, r) for c in range(28) for r in range(11)}
    assert full_grid - present == REAL_GAP_POSITIONS

    # The downloaded text is this module's own StrateFile.to_text() output
    # unchanged — "正向/反向" is purely a frontend display transform (see
    # simple_bingo_viewer.py's module docstring) and must never touch it.
    assert "SUBSTRATE_ID=Z26306101253" in s["text"]
    assert s["text"].count("\r\n") > 0  # .strate files are always CRLF


def test_extract_without_log_base64_returns_400():
    client = app.test_client()
    res = client.post("/api/simple_bingo/extract", json={})
    assert res.status_code == 400
    assert "log" in res.get_json()["error"]


MULTI_SUBSTRATE_FIXTURE = (
    Path(__file__).parent.parent.parent
    / "bingomap" / "tests" / "fixtures" / "BAA0320260906_17.0_BB93AE_8L808002A1.log"
)


def test_extract_includes_wafer_maps_matched_by_wafer_ring():
    """2026/10/29改版新增：左半wafer圖需要的資料——每枚基板都要能用
    wafer_ring找到它來源那片wafer的WaferStart bin map，而且每顆die
    的wafer_xy(不是sub_pos)位置數要跟num_dies對得上，不然前端疊加
    標示會漏顆或對不到格子。"""
    client = app.test_client()
    log_base64 = base64.b64encode(MULTI_SUBSTRATE_FIXTURE.read_bytes()).decode("ascii")

    res = client.post("/api/simple_bingo/extract", json={"log_base64": log_base64})
    assert res.status_code == 200
    data = res.get_json()

    assert len(data["substrates"]) == 6
    assert len(data["wafer_maps"]) > 0
    wafer_rings = {wm["frame_id"] for wm in data["wafer_maps"]}

    for s in data["substrates"]:
        assert s["wafer_ring"] in wafer_rings
        assert len(s["wafer_positions"]) == s["num_dies"]
