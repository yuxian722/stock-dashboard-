"""Fill a blank substrate-map skeleton with operator-picked wafer coordinates.

This is the part of the workflow that used to require WaferCoordinate.exe:
the operator points at wafer die sites on a map, and each pick gets written
into the next applicable substrate position. Two behaviours are load-bearing
and were verified against a real production .strate sample rather than
assumed:

- substrate positions with no pick are dropped from DIE_INFO entirely
  (not written out with bin=0), and survivors are renumbered 1..N
- each surviving die gets a sequentially incrementing timestamp

The "決不能選錯數量" (quantity must match exactly) rule from the SOP is
enforced as DieCountMismatch, reproducing the same wording WaferCoordinate.exe
shows in its confirmation dialog ("需要 Die 數量N，已選擇數量M，需減少…顆" when
over, "…還需選擇…顆" when under — verified against a live screenshot of the
real dialog for both directions).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from .strate import DieInfo, StrateFile


class DieCountMismatch(ValueError):
    def __init__(self, expected: int, actual: int):
        self.expected = expected
        self.actual = actual
        diff = actual - expected
        if diff > 0:
            detail = f"需減少{diff}顆"
        elif diff < 0:
            detail = f"還需選擇{-diff}顆"
        else:
            detail = ""
        super().__init__(f"需要 Die 數量{expected}，已選擇數量{actual}，{detail}")


@dataclass
class DiePick:
    """One operator selection: a wafer die site assigned to a substrate position."""

    sub_pos: str
    wafer_ring: str
    wafer_xy: str
    bin: str = "1"

    @classmethod
    def from_xy(cls, sub_pos: str, wafer_ring: str, x: int, y: int, bin: str = "1") -> "DiePick":
        """Convenience for the shape wafer-picking UIs actually produce —
        an X/Y/Bin table (see WaferCoordinate.exe's dgvSelectedCoord grid)
        — rather than the pre-joined "x:y" string the .strate format wants."""
        return cls(sub_pos=sub_pos, wafer_ring=wafer_ring, wafer_xy=f"{x}:{y}", bin=bin)


def assign_dies(
    blank: StrateFile,
    picks: list[DiePick],
    *,
    start_time: datetime,
    interval_seconds: int = 2,
    expected_qty: int | None = None,
) -> StrateFile:
    """Return a new StrateFile with `picks` written into `blank`'s skeleton.

    `picks` need not cover every substrate position — unmatched positions
    are dropped, matching real production files where unbonded sites are
    simply absent from DIE_INFO rather than kept with bin=0.
    """
    if expected_qty is not None and len(picks) != expected_qty:
        raise DieCountMismatch(expected_qty, len(picks))

    valid_positions = {d.sub_pos for d in blank.die_info}
    pick_by_pos: dict[str, DiePick] = {}
    for pick in picks:
        if pick.sub_pos not in valid_positions:
            raise ValueError(
                f"{pick.sub_pos!r} is not a valid substrate position for this "
                f"{blank.substrate_column}x{blank.substrate_row} layout"
            )
        if pick.sub_pos in pick_by_pos:
            raise ValueError(f"duplicate pick for substrate position {pick.sub_pos!r}")
        pick_by_pos[pick.sub_pos] = pick

    filled: list[DieInfo] = []
    ts = start_time
    index = 1
    for blank_die in blank.die_info:  # preserves the skeleton's column-major order
        pick = pick_by_pos.get(blank_die.sub_pos)
        if pick is None:
            continue
        filled.append(
            DieInfo(
                index=index,
                wafer_ring=pick.wafer_ring,
                wafer_xy=pick.wafer_xy,
                sub_pos=pick.sub_pos,
                bin=pick.bin,
                f6="0",
                f7="0",
                timestamp=ts.strftime("%Y%m%d%H%M%S"),
                f9="1",
            )
        )
        index += 1
        ts += timedelta(seconds=interval_seconds)

    return replace(blank, die_info=filled, total_bond_die_qty=len(filled), good_die=len(filled))
