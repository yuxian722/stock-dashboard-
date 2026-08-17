"""誤吸偏移／BIN點除 (mis-pick offset / BIN exclusion) analysis.

Two independent coordinate models, selected by `machine_type`:

- **DB** (`"DB"`, the default — this project's actual production machine
  type): the STRATE `wafer_xy` ("FX:FY") *is* the wafer bin map's own raw
  (x, y) coordinate, no transform at all. Confirmed 2026/08/17 against a
  real DB case the user provided: a screenshot of ChipMOS's internal
  "WaferCoordinate" tool with its 機型(machine type) selector explicitly
  set to "DB系列", whose own picked-coordinate list (X, Y, Bin columns)
  matched a real STRATE file's `wafer_xy` column entry-for-entry, plus the
  matching 目視檢查 wafer bin map screenshot and the matching EAS "Bingo Map
  Query" report for the same SUBSTRATE_ID. There is no known-mis-pick
  incident in that evidence, so the *coordinate correspondence* is
  confirmed but the *offset-direction* convention (what a "+1 in X"
  machine-motion offset means) is inferred by consistency (DB has no
  rotation anywhere else in this evidence, so offsets are applied directly
  in the same frame) rather than independently confirmed — flag this to
  the user rather than treating it as fully verified.

- **ESEC** (`"ESEC"`): ported from the user's ESEC 2100 reference tool
  ("STRATE座標偏移點除工具" v78, its live `v67BuildRows`/`v67Classify`/
  `v72RawToMachine270`/`v72MachineToRaw270` functions — the file also
  contains an entire earlier implementation, `run()`, that is dead code
  never wired to any button; it was not ported). The reference tool's own
  comments say its formulas were field-verified for ESEC 2100SD
  specifically and locked to NOTCH=270 — see `REQUIRED_NOTCH_ESEC` below.
  **This project's actual machines are DB, not ESEC** — the user explicitly
  said so on 2026/08/17 after this ESEC path had already shipped — so this
  path exists for reference/future use but should not be assumed to match
  this project's own real hardware. See bingomap/CLAUDE.md for the full
  story of both corrections (the DB confirmation, and the earlier
  wafer-ID-normalization fix).

Real-world problem (same for both machine types): a bonder had a *known*
systematic wafer-pickup offset (e.g. off by one column) during some run.
Given the original wafer bin map and the STRATE file(s) already produced
from that run, figure out which already-placed dies actually came from a
bad wafer position and need to be mechanically point-removed from the
substrate.

Pipeline:

  1. Convert STRATE's `wafer_xy` ("FX:FY") to the wafer MAP's own raw
     coordinate frame — identity for DB, a fixed X-flip for ESEC (see
     above). Look up the **nominal** bin there: if it isn't a Good bin,
     this position wasn't going to be picked anyway and is dropped rather
     than classified.
  2. Apply the operator's offset. For DB this is a direct add in the raw
     frame. For ESEC the raw-MAP coordinate is first rotated into
     "machine frame" so the offset (given in machine-motion terms) applies
     in the right frame, then rotated back to look up the **actual** bin
     the shifted position lands on.
  3. Classify by the actual bin: NG bin -> force-delete, review bin ->
     needs manual confirmation, Good bin -> still fine, anything else ->
     anomaly (never auto-deleted).

Deliberate improvement over the ESEC reference tool: it silently ignored
stacked-die (一次上兩顆) substrates' `[DIE_INFO_OTHER_LAYER_*]` section —
this module processes both layers (see `analyze_substrate`'s `layer`
tagging), since bingomap already models that structure and there is no
reason a mis-pick offset would only ever affect one layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .strate import DieInfo, StrateFile
from .wafer_map import WaferBinMap

MachineType = Literal["DB", "ESEC"]

REQUIRED_NOTCH_ESEC = "270"

DECISION_INVALID_COORD = "INVALID_STRATE_WAFER_COORD"
DECISION_OUT_OF_GEOMETRY = "STRATE_POSITION_OUT_OF_DECLARED_GEOMETRY"
DECISION_NOMINAL_NOT_FOUND = "NOMINAL_COORD_NOT_FOUND"
DECISION_NOMINAL_NOT_GOOD = "NOMINAL_MAP_NOT_GOOD"
DECISION_SHIFTED_NOT_FOUND = "SHIFTED_COORD_NOT_FOUND"
DECISION_FORCE_DELETE = "FORCE_DELETE_ACTUAL_BIN_NG"
DECISION_REVIEW = "REVIEW_ACTUAL_BIN_REVIEW"
DECISION_OK = "OK_ACTUAL_GOOD_BIN"
DECISION_ANOMALY = "ACTUAL_OTHER_BIN_DIAGNOSTIC"

ACTION_DECISIONS = {DECISION_FORCE_DELETE, DECISION_REVIEW}


class UnsupportedNotchError(ValueError):
    """Raised for ESEC when a STRATE's NOTCH header isn't 270 — the only
    orientation that machine type's formulas were field-validated for. Does
    not apply to DB, which has no NOTCH restriction (see module docstring)."""


class InvalidGeometryError(ValueError):
    """Raised instead of guessing when SUBSTRATE_COLUMN/ROW/BLOCK are
    missing or don't divide evenly — mirrors the reference tool's
    `v74ValidateGeom`, which refuses to fall back to a default size."""


class UnknownMachineTypeError(ValueError):
    pass


def _check_machine_type(machine_type: str) -> None:
    if machine_type not in ("DB", "ESEC"):
        raise UnknownMachineTypeError(f"machine_type must be 'DB' or 'ESEC', got {machine_type!r}")


@dataclass(frozen=True)
class Offset:
    axis: str  # "X" or "Y"
    value: int
    dx: int  # machine-frame delta actually applied
    dy: int


def make_offset(axis: str, value: int) -> Offset:
    if axis not in ("X", "Y"):
        raise ValueError(f"axis must be 'X' or 'Y', got {axis!r}")
    if value == 0:
        raise ValueError("偏移量必須是非0的整數")
    dx = value if axis == "X" else 0
    dy = value if axis == "Y" else 0
    return Offset(axis=axis, value=value, dx=dx, dy=dy)


def parse_bin_set(text: str, default: str = "") -> set[str]:
    """Comma/semicolon/whitespace-separated BIN list, e.g. "7,9" -> {"7","9"}."""
    import re

    raw = (text or "").strip() or default
    return {p for p in re.split(r"[,，;；\s]+", raw) if p}


@dataclass(frozen=True)
class WaferRange:
    min_x: int
    max_x: int
    min_y: int
    max_y: int


def wafer_range(wafer_map: WaferBinMap) -> WaferRange:
    if not wafer_map.cells:
        raise ValueError("wafer map has no cells to compute a range from")
    xs = [x for x, _ in wafer_map.cells]
    ys = [y for _, y in wafer_map.cells]
    return WaferRange(min(xs), max(xs), min(ys), max(ys))


def _raw_to_machine_esec270(x: int, y: int, r: WaferRange) -> tuple[int, int]:
    return r.max_y - y, x - r.min_x


def _machine_to_raw_esec270(x: int, y: int, r: WaferRange) -> tuple[int, int]:
    return y + r.min_x, r.max_y - x


def _wafer_xy_to_raw_map(fx: int, fy: int, r: WaferRange, machine_type: MachineType) -> tuple[int, int]:
    """STRATE `wafer_xy` -> the wafer MAP's own raw (x, y) coordinate."""
    if machine_type == "DB":
        return fx, fy  # identity — confirmed against real DB evidence, see module docstring
    return r.max_x - fx, fy  # ESEC: fixed X-flip, field-verified for NOTCH=270 only


def _apply_offset(nominal_xy: tuple[int, int], offset: Offset, r: WaferRange, machine_type: MachineType) -> tuple[int, int]:
    if machine_type == "DB":
        return nominal_xy[0] + offset.dx, nominal_xy[1] + offset.dy
    machine_xy = _raw_to_machine_esec270(*nominal_xy, r)
    shifted = (machine_xy[0] + offset.dx, machine_xy[1] + offset.dy)
    return _machine_to_raw_esec270(*shifted, r)


def output_position(tx: int, ty: int, substrate_column: int, machine_type: MachineType = "DB") -> tuple[int, int]:
    """The printed work-order grid position for a substrate coordinate.
    DB: identity (no evidence of any flip — see module docstring). ESEC: a
    fixed left-right flip (top-left = A1), matching the reference tool's
    `v67OutputPos`. Shared with crack_recovery.py."""
    _check_machine_type(machine_type)
    if machine_type == "DB":
        return tx, ty
    return substrate_column - 1 - tx, ty


def output_block(output_x: int, substrate_column: int, substrate_block: int) -> int | None:
    if output_x < 0 or output_x >= substrate_column:
        return None
    block_width = substrate_column / substrate_block
    return min(substrate_block, int(output_x // block_width) + 1)


def normalize_wafer_id(value: str) -> str:
    """Trim + uppercase, matching the reference tool's own wafer-ID
    comparison (`String(r.strateWaferId||'').trim().toUpperCase()`) in both
    its mis-pick (`runV68`) and Crack (`runV78Crack`) pipelines — used so
    this module's `wafer_ring` matching isn't accidentally stricter (exact,
    case-sensitive) than what the reference tool actually does."""
    return (value or "").strip().upper()


def validate_geometry(substrate: StrateFile) -> None:
    w, h, b = substrate.substrate_column, substrate.substrate_row, substrate.substrate_block
    if w <= 0 or h <= 0 or b <= 0:
        raise InvalidGeometryError(
            f"{substrate.substrate_id} 缺少或無效的 SUBSTRATE_COLUMN/SUBSTRATE_ROW/SUBSTRATE_BLOCK"
        )
    if b > w or w % b != 0:
        raise InvalidGeometryError(
            f"{substrate.substrate_id} 尺寸{w}x{h}、Block={b} 無法平均分欄，請確認STRATE產品規格後再輸出"
        )


@dataclass
class MispickRow:
    substrate_id: str
    layer: str  # "primary" or "other" — which DIE_INFO section this came from
    source_die: DieInfo
    fx: int | None
    fy: int | None
    tx: int | None
    ty: int | None
    decision: str
    nominal_map_xy: tuple[int, int] | None = None
    nominal_bin: str | None = None
    actual_map_xy: tuple[int, int] | None = None
    actual_bin: str | None = None
    output_xy: tuple[int, int] | None = None
    output_block: int | None = None
    action_no: int | None = None


def parse_xy(text: str) -> tuple[int, int] | None:
    x_str, sep, y_str = text.partition(":")
    if not sep:
        return None
    try:
        return int(x_str), int(y_str)
    except ValueError:
        return None


def _classify_row(
    die: DieInfo,
    layer: str,
    substrate: StrateFile,
    wafer_map: WaferBinMap,
    rng: WaferRange,
    offset: Offset,
    good_bins: set[str],
    ng_bins: set[str],
    review_bins: set[str],
    machine_type: MachineType,
) -> MispickRow:
    wafer_xy = parse_xy(die.wafer_xy)
    sub_xy = parse_xy(die.sub_pos)

    row = MispickRow(
        substrate_id=substrate.substrate_id,
        layer=layer,
        source_die=die,
        fx=wafer_xy[0] if wafer_xy else None,
        fy=wafer_xy[1] if wafer_xy else None,
        tx=sub_xy[0] if sub_xy else None,
        ty=sub_xy[1] if sub_xy else None,
        decision=DECISION_INVALID_COORD,
    )
    if wafer_xy is None:
        return row
    fx, fy = wafer_xy

    if (
        sub_xy is None
        or not (0 <= sub_xy[0] < substrate.substrate_column)
        or not (0 <= sub_xy[1] < substrate.substrate_row)
    ):
        row.decision = DECISION_OUT_OF_GEOMETRY
        return row
    tx, ty = sub_xy

    nominal_xy = _wafer_xy_to_raw_map(fx, fy, rng, machine_type)
    row.nominal_map_xy = nominal_xy
    row.nominal_bin = wafer_map.bin_at(*nominal_xy)
    if row.nominal_bin is None:
        row.decision = DECISION_NOMINAL_NOT_FOUND
        return row
    if row.nominal_bin not in good_bins:
        row.decision = DECISION_NOMINAL_NOT_GOOD
        return row

    actual_xy = _apply_offset(nominal_xy, offset, rng, machine_type)
    row.actual_map_xy = actual_xy
    row.actual_bin = wafer_map.bin_at(*actual_xy)
    if row.actual_bin is None:
        row.decision = DECISION_SHIFTED_NOT_FOUND
        return row

    if row.actual_bin in ng_bins:
        row.decision = DECISION_FORCE_DELETE
    elif row.actual_bin in review_bins:
        row.decision = DECISION_REVIEW
    elif row.actual_bin in good_bins:
        row.decision = DECISION_OK
    else:
        row.decision = DECISION_ANOMALY

    row.output_xy = output_position(tx, ty, substrate.substrate_column, machine_type)
    row.output_block = output_block(row.output_xy[0], substrate.substrate_column, substrate.substrate_block)
    return row


@dataclass
class MispickResult:
    rows: list[MispickRow] = field(default_factory=list)
    excluded: list[DieInfo] = field(default_factory=list)
    """DIE_INFO rows whose wafer_ring didn't match the target wafer — a
    different wafer's data mixed into the same STRATE file. Never
    classified or point-removed."""


def col_name(n: int) -> str:
    """Spreadsheet-style column letters: 0->A, 25->Z, 26->AA. Matches the
    reference tool's `colName()`, used for the printed work-order's
    coordinate labels."""
    if n < 0:
        return ""
    n = int(n)
    s = ""
    while True:
        s = chr(65 + (n % 26)) + s
        n = n // 26 - 1
        if n < 0:
            break
    return s


def output_coord(row: MispickRow) -> str:
    if row.output_xy is None:
        return ""
    x, y = row.output_xy
    return col_name(x) + str(y + 1)


def analyze_substrate(
    substrate: StrateFile,
    wafer_map: WaferBinMap,
    *,
    wafer_ring: str,
    offset: Offset,
    good_bins: set[str],
    ng_bins: set[str],
    review_bins: set[str],
    machine_type: MachineType = "DB",
) -> MispickResult:
    """Run the mis-pick offset analysis for one substrate's DIE_INFO rows
    (both layers, if it's a stacked/two-layer substrate). `machine_type`
    defaults to "DB" — this project's actual machine type, see module
    docstring — not "ESEC" (which was this feature's first, since-corrected
    default)."""
    _check_machine_type(machine_type)
    if machine_type == "ESEC" and str(substrate.notch).strip() != REQUIRED_NOTCH_ESEC:
        raise UnsupportedNotchError(
            f"ESEC模式只驗證過NOTCH=270的情況，這份STRATE的NOTCH={substrate.notch!r}，"
            "為避免用未驗證的公式誤判，不會產生結果"
        )
    validate_geometry(substrate)
    rng = wafer_range(wafer_map)
    target_wafer_id = normalize_wafer_id(wafer_ring)

    result = MispickResult()
    for layer, dies in (("primary", substrate.die_info), ("other", substrate.other_layer_die_info)):
        for die in dies:
            if normalize_wafer_id(die.wafer_ring) != target_wafer_id:
                result.excluded.append(die)
                continue
            result.rows.append(
                _classify_row(
                    die, layer, substrate, wafer_map, rng, offset, good_bins, ng_bins, review_bins, machine_type
                )
            )

    action_rows = [r for r in result.rows if r.decision in ACTION_DECISIONS]
    action_rows.sort(key=lambda r: (r.output_xy[0], r.output_xy[1], r.source_die.index))
    for i, r in enumerate(action_rows, start=1):
        r.action_no = i

    return result
