"""Generate a blank/golden .strate skeleton, replacing the manual EAS
"Create Golden SubstrateMap" web form step.

Derived from BINGOMAP空白圖檔產生與座標補資料軟體.pptx (slide 6): the DIE_INFO
skeleton walks the substrate positions in the machine's own fixed order,
formatted "column:row", with wafer_ring/wafer_xy left blank and bin
defaulted to "1" pending coordinate supplement.

Two things vary by shop-floor convention and must not be mixed up (SOP
explicitly warns this is the #1 source of scrapped batches):

1. Site-numbering start (`convention`):
   - EPOXY process: numbering starts at 0:0
   - LOC process:   numbering starts at 1:1

2. Substrate position walk order (`machine_type`) — confirmed against a
   real internal email (2019/11/27) comparing a DB-machine file against an
   ESEC 2100SD-machine file for the same product, both machines' own
   engineers flagging this exact mismatch as the cause of scrapped BINGO
   MAP data when copied across machine types:
   - DB:   starts at the first position (0:0), each column's rows always
     ascending, columns ascending — simple column-major sweep.
   - ESEC (2100SD): starts at the LAST position (COLUMN-1:ROW-1), columns
     walked in DESCENDING order, and the row direction alternates
     (serpentine/boustrophedon) each time the column changes.
   Do not assume any other machine type follows either pattern without a
   real sample to confirm against — see bingomap/CLAUDE.md.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterator, Literal

from .strate import DieInfo, StrateFile

Convention = Literal["EPOXY", "LOC"]
MachineType = Literal["DB", "ESEC"]

_CONVENTION_START = {"EPOXY": 0, "LOC": 1}


def _positions_db(row_count: int, col_count: int, start: int) -> Iterator[tuple[int, int]]:
    for col in range(start, col_count + start):
        for row in range(start, row_count + start):
            yield col, row


def _positions_esec(row_count: int, col_count: int, start: int) -> Iterator[tuple[int, int]]:
    last_col = col_count + start - 1
    for i, col in enumerate(range(last_col, start - 1, -1)):
        descending = i % 2 == 0
        row_range = (
            range(row_count + start - 1, start - 1, -1) if descending else range(start, row_count + start)
        )
        for row in row_range:
            yield col, row


_POSITION_STRATEGIES = {"DB": _positions_db, "ESEC": _positions_esec}


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
    machine_type: MachineType = "DB",
) -> StrateFile:
    if convention not in _CONVENTION_START:
        raise ValueError(f"convention must be 'EPOXY' or 'LOC', got {convention!r}")
    if machine_type not in _POSITION_STRATEGIES:
        raise ValueError(f"machine_type must be 'DB' or 'ESEC', got {machine_type!r}")
    if substrate_row <= 0 or substrate_column <= 0:
        raise ValueError("substrate_row and substrate_column must be positive")

    start = _CONVENTION_START[convention]
    positions = _POSITION_STRATEGIES[machine_type](substrate_row, substrate_column, start)

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
    for that specific substrate — reusing it sidesteps the DB-vs-ESEC
    ordering pitfall entirely (see module docstring / CLAUDE.md) instead of
    trying to re-guess which machine_type produced the original file.
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
