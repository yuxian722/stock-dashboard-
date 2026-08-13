"""Generate a blank/golden .strate skeleton, replacing the manual EAS
"Create Golden SubstrateMap" web form step.

Derived from BINGOMAP空白圖檔產生與座標補資料軟體.pptx (slide 6): the DIE_INFO
skeleton walks column-major (outer loop over SUBSTRATE_COLUMN, inner loop
over SUBSTRATE_ROW), formatted "column:row", with wafer_ring/wafer_xy left
blank and bin defaulted to "1" pending coordinate supplement.

Two site-numbering conventions are used on the shop floor and must not be
mixed up (SOP explicitly warns this is the #1 source of scrapped batches):
- EPOXY process: numbering starts at 0:0
- LOC process:   numbering starts at 1:1
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from .strate import DieInfo, StrateFile

Convention = Literal["EPOXY", "LOC"]

_CONVENTION_START = {"EPOXY": 0, "LOC": 1}


def generate_blank(
    *,
    assy_lot: str,
    mapping_lot: str,
    eqpid: str,
    oper: str,
    substrate_id: str,
    substrate_row: int,
    substrate_column: int,
    substrate_block: int,
    notch: str,
    ref: str,
    t2_point: str = "NA",
    t2_flat: str = "NA",
    out_mgz_slot_no: str = "",
    convention: Convention = "EPOXY",
) -> StrateFile:
    if convention not in _CONVENTION_START:
        raise ValueError(f"convention must be 'EPOXY' or 'LOC', got {convention!r}")
    if substrate_row <= 0 or substrate_column <= 0:
        raise ValueError("substrate_row and substrate_column must be positive")

    start = _CONVENTION_START[convention]
    die_info: list[DieInfo] = []
    index = 1
    for col in range(start, substrate_column + start):
        for row in range(start, substrate_row + start):
            die_info.append(
                DieInfo(
                    index=index,
                    wafer_ring="",
                    wafer_xy="",
                    sub_pos=f"{col}:{row}",
                    bin="1",
                    f6="0",
                    f7="0",
                    timestamp="0",
                    f9="1",
                )
            )
            index += 1

    total = substrate_row * substrate_column
    return StrateFile(
        assy_lot=assy_lot,
        mapping_lot=mapping_lot,
        eqpid=eqpid,
        oper=oper,
        substrate_id=substrate_id,
        substrate_row=substrate_row,
        substrate_column=substrate_column,
        substrate_block=substrate_block,
        out_mgz_slot_no=out_mgz_slot_no,
        total_bond_die_qty=total,
        good_die=total,
        run_time="",
        notch=notch,
        ref=ref,
        t2_point=t2_point,
        t2_flat=t2_flat,
        die_info=die_info,
    )


def timestamp_now() -> str:
    """YYYYMMDDHHMMSS, matching the filename/RUN_TIME convention."""
    return datetime.now().strftime("%Y%m%d%H%M%S")
