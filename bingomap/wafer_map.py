"""Wafer bin grid + rectangle-select scanning.

Mirrors WaferCoordinate.exe's picking interaction: the operator drags a
rectangle over the wafer grid, and the tool walks that rectangle picking up
every good (green / BIN 1) cell in scan order while skipping bad (magenta /
BIN 7, or any other bin) and empty cells — cells outside the physical wafer
circle simply have no entry in the map at all.

This module is deliberately agnostic about where the bin data came from —
today that's a human reading it off WaferCoordinate.exe or 目視檢查 and
typing/pasting it in; nothing here depends on how the grid was populated.

The scan order (column-major, x outer / y inner, both ascending) is a
reasonable default, not a byte-verified match to WaferCoordinate.exe's own
traversal — we only have partial photos of a real selection, not a full
confirmed reference. It matters only for readability of the resulting pick
order; assign_dies() maps picks to substrate positions strictly in the
order given, whatever that order is, so getting this exactly right is a
polish item, not a correctness one.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .assignment import DiePick

DEFAULT_GOOD_BIN = "1"


@dataclass
class WaferBinMap:
    columns: int
    rows: int
    cells: dict[tuple[int, int], str] = field(default_factory=dict)

    def bin_at(self, x: int, y: int) -> str | None:
        """None means no data for that cell (e.g. outside the wafer circle)."""
        return self.cells.get((x, y))

    def set_bin(self, x: int, y: int, bin: str) -> None:
        self.cells[(x, y)] = bin


def scan_rectangle(
    wafer_map: WaferBinMap,
    x_range: range,
    y_range: range,
    *,
    good_bin: str = DEFAULT_GOOD_BIN,
) -> list[tuple[int, int]]:
    """Column-major raster scan of a selected rectangle (x outer, y inner,
    both ascending), keeping only cells whose bin equals `good_bin` and
    silently skipping everything else (other bins, or no data at all).
    """
    picked: list[tuple[int, int]] = []
    for x in x_range:
        for y in y_range:
            if wafer_map.bin_at(x, y) == good_bin:
                picked.append((x, y))
    return picked


def build_picks_from_scan(
    scanned: list[tuple[int, int]],
    sub_positions: list[str],
    *,
    wafer_ring: str,
    bin: str = DEFAULT_GOOD_BIN,
) -> list[DiePick]:
    """Zip a scanned wafer-coordinate list with the substrate positions they
    should fill, in order. `sub_positions` is deliberately an explicit,
    caller-supplied list (e.g. a subset of a blank StrateFile's die_info
    positions) rather than something this function infers, since deciding
    which substrate sites to skip is a judgement call the operator/UI makes
    — see assignment.py's docstring on why unfilled sites are dropped
    rather than defaulted.
    """
    if len(scanned) != len(sub_positions):
        raise ValueError(
            f"scanned {len(scanned)} wafer coordinate(s) but {len(sub_positions)} "
            "substrate position(s) were given to fill — counts must match"
        )
    return [
        DiePick.from_xy(sub_pos, wafer_ring, x, y, bin=bin)
        for sub_pos, (x, y) in zip(sub_positions, scanned)
    ]
