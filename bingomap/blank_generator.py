"""Generate a blank/golden .strate skeleton, replacing the manual EAS
"Create Golden SubstrateMap" web form step.

Derived from BINGOMAP空白圖檔產生與座標補資料軟體.pptx (slide 6): the DIE_INFO
skeleton walks the substrate positions in the machine's own fixed order,
formatted "column:row", with wafer_ring/wafer_xy left blank and bin
defaulted to "1" pending coordinate supplement.

Site-numbering start (`convention`) varies by shop-floor process and must
not be mixed up (SOP explicitly warns this is the #1 source of scrapped
batches):
   - EPOXY process: numbering starts at 0:0
   - LOC process:   numbering starts at 1:1

Substrate position walk order: this project's actual machine (DB) starts
at the first position (0:0), each column's rows always ascending, columns
ascending — simple column-major sweep. (2026/09/03: this module used to
also support an ESEC 2100SD walk order (start at the LAST position,
descending/serpentine) — removed along with `machine_type` per the user's
request to drop ESEC support entirely, since this project's actual
hardware is DB. See git history before this date if it's ever needed
again.)
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterator, Literal

from .strate import DieInfo, StrateFile

Convention = Literal["EPOXY", "LOC"]

_CONVENTION_START = {"EPOXY": 0, "LOC": 1}


def _positions_db(row_count: int, col_count: int, start: int) -> Iterator[tuple[int, int]]:
    for col in range(start, col_count + start):
        for row in range(start, row_count + start):
            yield col, row


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
    positions = _positions_db(substrate_row, substrate_column, start)

    die_info: list[DieInfo] = []
    index = 1
    for col, row in positions:
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


def blank_from_positions(
    *,
    assy_lot: str,
    mapping_lot: str,
    eqpid: str,
    oper: str,
    substrate_id: str,
    substrate_row: int,
    substrate_column: int,
    substrate_block: int,
    notch: str = "",
    ref: str = "",
    t2_point: str = "NA",
    t2_flat: str = "NA",
    out_mgz_slot_no: str = "",
    positions: list[str],
) -> StrateFile:
    """Build a blank skeleton from an explicit, already-known position order
    instead of deriving it from `convention`/`machine_type`.

    This is the "複製既有.strate為範本" (copy an existing file as a template)
    path: `positions` comes straight from a previously-parsed real file's own
    DIE_INFO (see webapp's /api/parse_strate), so it is guaranteed correct
    for that specific substrate — reusing it sidesteps re-deriving the walk
    order from `convention` entirely.
    """
    die_info = [
        DieInfo(index=i, wafer_ring="", wafer_xy="", sub_pos=pos, bin="1", f6="0", f7="0", timestamp="0", f9="1")
        for i, pos in enumerate(positions, start=1)
    ]
    total = len(positions)
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
