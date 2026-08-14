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

import os
from datetime import datetime

from flask import Flask, Response, jsonify, render_template, request

from bingomap.assignment import DieCountMismatch, DiePick, assign_dies, assign_two_layers
from bingomap.blank_generator import generate_blank
from bingomap.frm_reader import FrmFormatError, frm_file_path, parse_frm

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
    return render_template("index.html")


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


if __name__ == "__main__":
    app.run(debug=True, port=5000)
