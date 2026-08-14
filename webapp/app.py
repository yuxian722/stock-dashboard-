"""Minimal web UI wrapping the bingomap core.

Flow matches the original ask: open the page -> fill in header info ->
generate the blank skeleton -> click/drag-select wafer coordinates ->
generate the final .strate file. All business logic (blank generation,
quantity validation, DIE_INFO assignment) stays in the bingomap package;
this module is just HTTP plumbing + a thin static frontend.

Wafer bin data (the green/magenta grid) still has no automatic source —
see bingomap/README.md — so this UI accepts it as pasted "x,y,bin" text
for now. Swapping that input for a real data source later doesn't touch
anything below /api/generate.
"""
from __future__ import annotations

import csv
import io
import os
from datetime import datetime

from flask import Flask, Response, jsonify, render_template, request

from bingomap.assignment import DieCountMismatch, DiePick, assign_dies, assign_two_layers
from bingomap.blank_generator import blank_from_positions, generate_blank
from bingomap.crack_recovery import (
    MissingNotchError,
    build_session,
    crack_csv_rows,
    crack_output_coord,
    wafer_scatter,
)
from bingomap.frm_reader import FrmFormatError, frm_file_path, frm_to_wafer_bin_map, parse_frm
from bingomap.mispick_analysis import (
    DECISION_ANOMALY,
    DECISION_FORCE_DELETE,
    DECISION_OK,
    DECISION_REVIEW,
    InvalidGeometryError,
    UnsupportedNotchError,
    analyze_substrate,
    make_offset,
    output_coord,
    parse_bin_set,
)
from bingomap.strate import StrateFile, StrateFormatError

app = Flask(__name__)

# Matches WaferCoordinate.exe.config's own FRM_PATH default. Only reachable
# when this Flask process itself runs on a machine with the F: network
# drive mapped — see bingomap/CLAUDE.md. Override with the BINGOMAP_FRM_PATH
# env var, or the frm_path field in a /api/frm request body, for other
# deployments.
DEFAULT_FRM_PATH = os.environ.get("BINGOMAP_FRM_PATH", r"F:\SMAP\FRM\\")


def _blank_from_header(data: dict):
    return generate_blank(
        assy_lot=data["assy_lot"],
        mapping_lot=data["mapping_lot"],
        eqpid=data["eqpid"],
        oper=data["oper"],
        substrate_id=data["substrate_id"],
        substrate_row=int(data["substrate_row"]),
        substrate_column=int(data["substrate_column"]),
        substrate_block=int(data["substrate_block"]),
        notch=data.get("notch", ""),
        ref=data.get("ref", ""),
        t2_point=data.get("t2_point", "NA"),
        t2_flat=data.get("t2_flat", "NA"),
        out_mgz_slot_no=data.get("out_mgz_slot_no", ""),
        convention=data.get("convention", "EPOXY"),
        machine_type=data.get("machine_type", "DB"),
    )


@app.get("/")
def index():
    return render_template("index.html", active_page="supplement")


@app.post("/api/blank")
def api_blank():
    data = request.get_json(force=True)
    try:
        blank = _blank_from_header(data)
    except (KeyError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(
        {
            "positions": [d.sub_pos for d in blank.die_info],
            "total_qty": blank.total_bond_die_qty,
        }
    )


def _die_info_to_picks(die_list: list) -> list[dict]:
    picks = []
    for d in die_list:
        x_str, _, y_str = d.wafer_xy.partition(":")
        try:
            x, y = int(x_str), int(y_str)
        except ValueError:
            continue
        picks.append({"x": x, "y": y, "bin": d.bin})
    return picks


@app.post("/api/parse_strate")
def api_parse_strate():
    """複製既有.strate為範本：parse an existing real file and hand back
    everything the frontend needs to prefill the form and picks — header
    fields, the file's own substrate position order (verbatim, so
    regenerating never has to re-guess convention/machine_type), and the
    wafer picks already made, split by layer if the file has a stacked
    OTHER_LAYER section."""
    data = request.get_json(force=True)
    text = data.get("text", "")
    if not text.strip():
        return jsonify({"error": "請提供.strate檔案內容"}), 400

    try:
        template = StrateFile.parse(text)
    except StrateFormatError as exc:
        return jsonify({"error": f"檔案格式解析失敗：{exc}"}), 422

    return jsonify(
        {
            "assy_lot": template.assy_lot,
            "mapping_lot": template.mapping_lot,
            "eqpid": template.eqpid,
            "oper": template.oper,
            "substrate_id": template.substrate_id,
            "substrate_row": template.substrate_row,
            "substrate_column": template.substrate_column,
            "substrate_block": template.substrate_block,
            "notch": template.notch,
            "ref": template.ref,
            "wafer_ring": template.die_info[0].wafer_ring if template.die_info else "",
            "positions": [d.sub_pos for d in template.die_info],
            "total_qty": len(template.die_info),
            "picks": _die_info_to_picks(template.die_info),
            "two_layer": bool(template.other_layer_die_info),
            "other_picks": _die_info_to_picks(template.other_layer_die_info),
            "primary_layer": template.die_info[0].f9 if template.die_info else "1",
            "other_layer": template.other_layer_die_info[0].f9 if template.other_layer_die_info else "",
        }
    )


@app.post("/api/frm")
def api_frm():
    """Auto-load the wafer bin map straight from the FRM file — the
    replacement for pasting "x,y,bin" text, once this server itself runs
    somewhere with F:\\SMAP\\FRM\\ mapped."""
    data = request.get_json(force=True)
    lot_no = (data.get("lot_no") or "").strip()
    barcode_id = (data.get("barcode_id") or "").strip()
    frm_root = (data.get("frm_path") or DEFAULT_FRM_PATH).strip()
    if not lot_no or not barcode_id:
        return jsonify({"error": "lot_no 和 barcode_id 都必填"}), 400

    try:
        path = frm_file_path(frm_root, lot_no, barcode_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    # frm_file_path() always joins with backslashes to match
    # WaferCoordinate.exe's own path construction (and to display a
    # Windows-familiar path in error messages) — real Windows deployments
    # handle that natively, but a non-Windows filesystem (e.g. this
    # session's Linux test suite) needs it translated to os.sep to
    # actually resolve.
    fs_path = path.replace("\\", os.sep)

    if not os.path.exists(fs_path):
        return (
            jsonify(
                {
                    "error": f"找不到檔案：{path}\n"
                    "請確認 LotNo/Barcode ID 是否正確，或這台電腦是否連得到F槽網路磁碟機"
                }
            ),
            404,
        )

    try:
        with open(fs_path, "rb") as f:
            frm = parse_frm(f.read())
    except FrmFormatError as exc:
        return jsonify({"error": f"檔案格式解析失敗：{exc}"}), 422
    except OSError as exc:
        return jsonify({"error": f"讀取檔案失敗：{exc}"}), 500

    return jsonify(
        {
            "columns": frm.col,
            "rows": frm.row,
            "lot_no": frm.lot_no,
            "wafer_id": frm.wafer_id,
            "wafer_type": frm.wafer_type,
            "cells": [{"x": x, "y": y, "bin": str(bin_kind)} for (x, y), bin_kind in frm.die_map.items()],
        }
    )


def _build_picks(selections: list[dict], sub_positions: list[str], wafer_ring: str) -> list[DiePick]:
    # assign_dies()/assign_two_layers() check len(picks) against
    # expected_qty before ever looking at an individual pick's sub_pos, so
    # when counts don't match we only need the right *length* to get a
    # correct DieCountMismatch message — the "" placeholder is never read
    # on that path. On the matching-count path every index is a real
    # position.
    return [
        DiePick.from_xy(
            sub_positions[i] if i < len(sub_positions) else "",
            wafer_ring,
            sel["x"],
            sel["y"],
            bin=str(sel.get("bin", "1")),
        )
        for i, sel in enumerate(selections)
    ]


@app.post("/api/generate")
def api_generate():
    data = request.get_json(force=True)
    try:
        template_positions = data.get("template_positions")
        if template_positions:
            # 複製既有.strate為範本 path: reuse the source file's own
            # position order verbatim instead of re-deriving it from
            # convention/machine_type — see blank_from_positions()'s
            # docstring for why that's the safer choice here.
            blank = blank_from_positions(
                assy_lot=data["assy_lot"],
                mapping_lot=data["mapping_lot"],
                eqpid=data["eqpid"],
                oper=data["oper"],
                substrate_id=data["substrate_id"],
                substrate_row=int(data["substrate_row"]),
                substrate_column=int(data["substrate_column"]),
                substrate_block=int(data["substrate_block"]),
                notch=data.get("notch", ""),
                ref=data.get("ref", ""),
                positions=template_positions,
            )
        else:
            blank = _blank_from_header(data)
    except (KeyError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400

    wafer_ring = data.get("wafer_ring", "")
    sub_positions = [d.sub_pos for d in blank.die_info]

    try:
        start_time = datetime.fromisoformat(data.get("start_time"))
    except (TypeError, ValueError):
        return jsonify({"error": "start_time must be an ISO 8601 timestamp"}), 400
    interval_seconds = int(data.get("interval_seconds", 2))

    try:
        if data.get("two_layer"):
            primary_picks = _build_picks(data.get("primary_selections", []), sub_positions, wafer_ring)
            other_picks = _build_picks(data.get("other_selections", []), sub_positions, wafer_ring)
            filled = assign_two_layers(
                blank,
                primary_picks,
                other_picks,
                start_time=start_time,
                interval_seconds=interval_seconds,
                expected_qty=blank.total_bond_die_qty,
                primary_layer=str(data.get("primary_layer", "2")),
                other_layer=str(data.get("other_layer", "1")),
            )
        else:
            picks = _build_picks(data.get("selections", []), sub_positions, wafer_ring)
            filled = assign_dies(
                blank,
                picks,
                start_time=start_time,
                interval_seconds=interval_seconds,
                expected_qty=blank.total_bond_die_qty,
            )
    except DieCountMismatch as exc:
        return jsonify({"error": str(exc)}), 409
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    timestamp = start_time.strftime("%Y%m%d%H%M%S")
    filename = filled.filename(timestamp)
    content = filled.to_text()
    return Response(
        content,
        mimetype="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/mispick")
def mispick_page():
    return render_template("mispick.html", active_page="mispick")


_MISPICK_CSV_HEADER = [
    "source_file", "substrate_id", "layer", "action_no", "decision",
    "output_block", "output_coord", "tx", "ty", "fx", "fy",
    "nominal_map_x", "nominal_map_y", "nominal_bin",
    "actual_map_x", "actual_map_y", "actual_bin", "wafer_ring",
]


def _csv_text(rows: list[list]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    for row in rows:
        writer.writerow(row)
    return "﻿" + buf.getvalue()  # BOM so Excel opens it as UTF-8, not Big5


@app.post("/api/mispick/analyze")
def api_mispick_analyze():
    """誤吸偏移／BIN點除: given a known machine pick offset, the original
    wafer bin map (FRM), and one or more already-produced STRATE files,
    figure out which placed dies actually landed on a bad wafer BIN and
    need to be point-removed. See bingomap/mispick_analysis.py — ported
    from the user's ESEC 2100 reference tool, NOTCH=270 only."""
    data = request.get_json(force=True)

    wafer_ring = (data.get("wafer_ring") or "").strip()
    if not wafer_ring:
        return jsonify({"error": "請輸入要比對的完整Wafer ID"}), 400

    try:
        offset = make_offset(data.get("offset_axis", "X"), int(data.get("offset_value", 0)))
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400

    good_bins = parse_bin_set(data.get("good_bins", ""), default="1")
    ng_bins = parse_bin_set(data.get("ng_bins", ""), default="7,9")
    review_bins = parse_bin_set(data.get("review_bins", ""), default="2")

    frm_info = data.get("frm") or {}
    lot_no = (frm_info.get("lot_no") or "").strip()
    barcode_id = (frm_info.get("barcode_id") or "").strip()
    frm_root = (frm_info.get("frm_path") or DEFAULT_FRM_PATH).strip()
    if not lot_no or not barcode_id:
        return jsonify({"error": "請輸入原始wafer MAP的FRM Lot No跟Barcode ID"}), 400
    try:
        path = frm_file_path(frm_root, lot_no, barcode_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    fs_path = path.replace("\\", os.sep)
    if not os.path.exists(fs_path):
        return jsonify({"error": f"找不到原始wafer MAP檔案：{path}"}), 404
    try:
        with open(fs_path, "rb") as f:
            frm = parse_frm(f.read())
    except FrmFormatError as exc:
        return jsonify({"error": f"原始wafer MAP格式解析失敗：{exc}"}), 422
    wafer_map = frm_to_wafer_bin_map(frm)

    strate_files = data.get("strate_files") or []
    if not strate_files:
        return jsonify({"error": "請至少上傳一份STRATE檔案"}), 400

    substrates_out = []
    csv_rows = [_MISPICK_CSV_HEADER]
    for item in strate_files:
        name = item.get("name", "")
        text = item.get("text", "")
        try:
            substrate = StrateFile.parse(text)
        except StrateFormatError as exc:
            substrates_out.append({"name": name, "substrate_id": None, "error": f"STRATE格式解析失敗：{exc}"})
            continue
        try:
            result = analyze_substrate(
                substrate,
                wafer_map,
                wafer_ring=wafer_ring,
                offset=offset,
                good_bins=good_bins,
                ng_bins=ng_bins,
                review_bins=review_bins,
            )
        except (UnsupportedNotchError, InvalidGeometryError) as exc:
            substrates_out.append({"name": name, "substrate_id": substrate.substrate_id, "error": str(exc)})
            continue

        summary = {"force_delete": 0, "review": 0, "anomaly": 0, "ok": 0, "other": 0}
        action_rows_out = []
        for row in result.rows:
            if row.decision == DECISION_FORCE_DELETE:
                summary["force_delete"] += 1
            elif row.decision == DECISION_REVIEW:
                summary["review"] += 1
            elif row.decision == DECISION_ANOMALY:
                summary["anomaly"] += 1
            elif row.decision == DECISION_OK:
                summary["ok"] += 1
            else:
                summary["other"] += 1

            nominal_x, nominal_y = row.nominal_map_xy or ("", "")
            actual_x, actual_y = row.actual_map_xy or ("", "")
            csv_rows.append(
                [
                    name, substrate.substrate_id, row.layer, row.action_no or "", row.decision,
                    row.output_block or "", output_coord(row), row.tx, row.ty, row.fx, row.fy,
                    nominal_x, nominal_y, row.nominal_bin or "",
                    actual_x, actual_y, row.actual_bin or "", row.source_die.wafer_ring,
                ]
            )
            if row.action_no is not None:
                action_rows_out.append(
                    {
                        "action_no": row.action_no,
                        "decision": row.decision,
                        "layer": row.layer,
                        "output_block": row.output_block,
                        "output_coord": output_coord(row),
                        "tx": row.tx,
                        "ty": row.ty,
                        "actual_bin": row.actual_bin,
                    }
                )
        action_rows_out.sort(key=lambda r: r["action_no"])

        substrates_out.append(
            {
                "name": name,
                "substrate_id": substrate.substrate_id,
                "error": None,
                "summary": summary,
                "excluded_count": len(result.excluded),
                "action_rows": action_rows_out,
            }
        )

    return jsonify(
        {
            "wafer": {"columns": frm.col, "rows": frm.row, "lot_no": frm.lot_no, "wafer_id": frm.wafer_id},
            "substrates": substrates_out,
            "csv": _csv_text(csv_rows),
        }
    )


@app.get("/crack")
def crack_page():
    return render_template("crack.html", active_page="crack")


def _crack_doc_payload(doc_index, name, substrate, candidates):
    cells = [
        {
            "key": c.key,
            "tx": c.tx,
            "ty": c.ty,
            "output_x": c.output_xy[0],
            "output_y": c.output_xy[1],
            "output_block": c.output_block,
            "output_coord": crack_output_coord(c),
            "wafer_id": c.wafer_id,
            "fx": c.fx,
            "fy": c.fy,
        }
        for c in candidates
        if c.doc_index == doc_index
    ]
    return {
        "doc_index": doc_index,
        "name": name,
        "substrate_id": substrate.substrate_id,
        "row": substrate.substrate_row,
        "column": substrate.substrate_column,
        "block": substrate.substrate_block,
        "cells": cells,
    }


@app.post("/api/crack/analyze")
def api_crack_analyze():
    """Crack位置回推: pool DIE_INFO rows sharing a wafer ID across every
    uploaded STRATE, let the operator mark crack positions on each
    substrate's own grid, and reconstruct where those marks sit relative to
    each other on the source wafer (local scatter only — see
    bingomap/crack_recovery.py for why this is explicitly not a true
    absolute wafer position). Stateless like the rest of this app: every
    call re-parses the uploaded STRATE text and re-derives everything from
    `marked_keys`, so there's nothing to keep in sync server-side."""
    data = request.get_json(force=True)
    strate_files = data.get("strate_files") or []
    if not strate_files:
        return jsonify({"error": "請至少上傳一份STRATE檔案"}), 400

    docs = []
    for item in strate_files:
        name = item.get("name", "")
        text = item.get("text", "")
        try:
            substrate = StrateFile.parse(text)
        except StrateFormatError as exc:
            return jsonify({"error": f"{name} 格式解析失敗：{exc}"}), 422
        docs.append((name, substrate))

    try:
        session = build_session(docs)
    except (InvalidGeometryError, MissingNotchError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 422

    marked_keys = [k for k in (data.get("marked_keys") or []) if k in session.by_key]
    wafer_ids = session.wafer_ids()

    focus_wafer_id = data.get("focus_wafer_id") or ""
    if focus_wafer_id not in wafer_ids:
        marked = session.marked(marked_keys)
        focus_wafer_id = marked[-1].wafer_id if marked else session.candidates[0].wafer_id

    docs_out = [_crack_doc_payload(i, name, substrate, session.candidates) for i, (name, substrate) in enumerate(docs)]

    rng, notch, points = wafer_scatter(session, focus_wafer_id, marked_keys)
    scatter = {
        "range": {"min_x": rng.min_x, "max_x": rng.max_x, "min_y": rng.min_y, "max_y": rng.max_y},
        "notch": notch,
        "points": [
            {"key": p.key, "x": p.x, "y": p.y, "is_crack": p.is_crack, "crack_no": p.crack_no} for p in points
        ],
    }

    crack_table = [
        {
            "crack_no": i,
            "key": c.key,
            "substrate_id": c.substrate_id,
            "source": c.doc_name,
            "output_block": c.output_block,
            "output_coord": crack_output_coord(c),
            "tx": c.tx,
            "ty": c.ty,
            "wafer_id": c.wafer_id,
            "fx": c.fx,
            "fy": c.fy,
            "notch": c.notch,
        }
        for i, c in enumerate(session.marked(marked_keys), start=1)
    ]

    return jsonify(
        {
            "docs": docs_out,
            "wafer_ids": wafer_ids,
            "focus_wafer_id": focus_wafer_id,
            "scatter": scatter,
            "crack_table": crack_table,
            "csv": _csv_text(crack_csv_rows(session, marked_keys)),
        }
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
