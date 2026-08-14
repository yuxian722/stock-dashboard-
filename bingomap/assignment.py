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


def _build_die_info_list(
    blank: StrateFile,
    picks: list[DiePick],
    *,
    layer: str,
    start_time: datetime,
    interval_seconds: int,
    expected_qty: int | None,
) -> list[DieInfo]:
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
                f9=layer,
            )
        )
        index += 1
        ts += timedelta(seconds=interval_seconds)
    return filled


def assign_dies(
    blank: StrateFile,
    picks: list[DiePick],
    *,
    start_time: datetime,
    interval_seconds: int = 2,
    expected_qty: int | None = None,
    layer: str = "1",
) -> StrateFile:
    """Return a new StrateFile with `picks` written into `blank`'s skeleton.

    `picks` need not cover every substrate position — unmatched positions
    are dropped, matching real production files where unbonded sites are
    simply absent from DIE_INFO rather than kept with bin=0.

    `layer` is each surviving row's f9 value. Every single-layer sample we
    verified against had f9="1" throughout, hence the default — but f9 is
    not a constant in general, see assign_two_layers() below and
    bingomap/CLAUDE.md's note on 疊層(一次上兩顆).
    """
    filled = _build_die_info_list(
        blank, picks, layer=layer, start_time=start_time,
        interval_seconds=interval_seconds, expected_qty=expected_qty,
    )
    return replace(blank, die_info=filled, total_bond_die_qty=len(filled), good_die=len(filled))


def assign_two_layers(
    blank: StrateFile,
    primary_picks: list[DiePick],
    other_picks: list[DiePick],
    *,
    start_time: datetime,
    interval_seconds: int = 2,
    expected_qty: int | None = None,
    primary_layer: str = "2",
    other_layer: str = "1",
) -> StrateFile:
    """Stacked-die ("一次上兩顆") variant of assign_dies(): fills both
    DIE_INFO sections of a StrateFile from the SAME substrate-position
    skeleton — confirmed against a real 2-layer sample where both layers'
    substrate position sequences were identical, just with different wafer
    picks and a different trailing f9 per section (see
    bingomap/CLAUDE.md). `expected_qty` is checked against both pick lists
    independently, matching that sample (55 dies each side, same target).

    Both DieCountMismatch and the plain ValueError cases are raised as-is
    from whichever side fails first (primary checked before other).
    """
    primary_filled = _build_die_info_list(
        blank, primary_picks, layer=primary_layer, start_time=start_time,
        interval_seconds=interval_seconds, expected_qty=expected_qty,
    )
    other_filled = _build_die_info_list(
        blank, other_picks, layer=other_layer, start_time=start_time,
        interval_seconds=interval_seconds, expected_qty=expected_qty,
    )
    return replace(
        blank,
        die_info=primary_filled,
        other_layer_die_info=other_filled,
        total_bond_die_qty=len(primary_filled),
        good_die=len(primary_filled),
    )
