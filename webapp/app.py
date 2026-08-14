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

from datetime import datetime

from flask import Flask, Response, jsonify, render_template, request

from bingomap.assignment import DieCountMismatch, DiePick, assign_dies
from bingomap.blank_generator import generate_blank

app = Flask(__name__)


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


@app.post("/api/generate")
def api_generate():
    data = request.get_json(force=True)
    try:
        blank = _blank_from_header(data)
    except (KeyError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400

    selections = data.get("selections", [])
    wafer_ring = data.get("wafer_ring", "")
    sub_positions = [d.sub_pos for d in blank.die_info]

    # assign_dies() checks len(picks) against expected_qty before it ever
    # looks at an individual pick's sub_pos, so when counts don't match we
    # only need `picks` to have the right *length* to get the correct
    # DieCountMismatch message — the "" placeholder below is never read on
    # that path. On the matching-count path every index is a real position.
    picks = [
        DiePick.from_xy(
            sub_positions[i] if i < len(sub_positions) else "",
            wafer_ring,
            sel["x"],
            sel["y"],
            bin=str(sel.get("bin", "1")),
        )
        for i, sel in enumerate(selections)
    ]

    try:
        start_time = datetime.fromisoformat(data.get("start_time"))
    except (TypeError, ValueError):
        return jsonify({"error": "start_time must be an ISO 8601 timestamp"}), 400
    interval_seconds = int(data.get("interval_seconds", 2))

    try:
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
