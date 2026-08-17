"""Crack位置回推 (crack position back-calculation) analysis.

Ported from the user's ESEC 2100 reference tool's "Crack位置回推" mode
(STRATE座標偏移點除工具 v78 — `runV78Crack`/`v78ToggleCrack`/`v78WaferView`).
Unlike the mis-pick offset mode (see mispick_analysis.py), this mode:

  - needs no wafer bin map and no offset — it works purely from
    already-produced STRATE file(s)
  - accepts any NOTCH (0/90/180/270-ish; anything else falls back to a
    plain X-flip with no extra rotation, matching the reference tool's own
    fallback), not locked to 270 the way the mis-pick mode is
  - treats every STRATE-recorded position as background "Good" — this mode
    isn't validating bin correctness at all, only reconstructing where
    operator-marked crack positions sit relative to each other (the
    reference tool's own CSV hardcodes a "1" in this column regardless of
    the row's actual recorded bin)

Real-world problem: an operator finds cracked dies by eye on a physical
substrate. This reconstructs where those same die positions sit relative
to each other on the *source wafer*, by pooling every currently-loaded
STRATE record that shares the same wafer ID (a wafer can span multiple
substrates) and normalizing their FX:FY coordinates into a *local* 0-based
view. This is explicitly NOT a true absolute wafer position — the
reference tool says so in its own help text ("僅代表已匯入資料相對位置"),
and this port carries that caveat forward rather than overstating what the
output means.

Unlike the mis-pick mode (which processes each STRATE substrate
independently and reports per-substrate errors), this mode matches the
reference tool's all-or-nothing behavior: `build_session()` raises on the
first invalid document rather than skipping it, because the whole point is
pooling multiple STRATE files together — a silently-dropped file could
produce a misleadingly incomplete local scatter without any visible
warning.

Wafer-ID matching uses `mispick_analysis.normalize_wafer_id()` (trim +
uppercase) — same reason as mispick_analysis.py: the reference tool
normalizes on both sides before comparing, so this module does too rather
than being accidentally stricter.

Like mispick_analysis.py, every function here takes a `machine_type`
("DB", the default and this project's real machine type, or "ESEC", the
reference tool's own machine, ported but not this project's hardware).
DB's `local_view()` is a plain identity normalization (no flip, no
rotation) — confirmed by extension from the same 2026/08/17 real DB
evidence that fixed mispick_analysis.py's coordinate transform: since that
evidence showed STRATE `wafer_xy` already equals the wafer MAP's own raw
coordinate for DB with no flip anywhere, there is no reason for this
module's *display* scatter to introduce a flip DB's own tooling doesn't
have. This specific consequence (the scatter's own orientation) was not
independently re-checked against a DB Crack scenario — it is inferred by
consistency, and is a display-only choice, not a bin/pass-fail decision.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .mispick_analysis import (
    MachineType,
    normalize_wafer_id,
    output_block,
    output_position,
    parse_xy,
    validate_geometry,
)
from .strate import DieInfo, StrateFile

CRACK_CSV_HEADER = [
    "crack_no", "substrate_id", "source_strate_file", "block", "output_coord",
    "output_x", "output_y", "raw_tx", "raw_ty", "complete_wafer_id",
    "strate_fx", "strate_fy", "local_x", "local_y", "notch",
    "crack_background_bin", "direction", "coordinate_scope",
]


class MissingNotchError(ValueError):
    """A STRATE header has no usable NOTCH value — crack mode still needs
    *some* NOTCH (any of them) to orient the local scatter, unlike the
    mis-pick mode's stricter =270-only requirement."""


def notch_degrees(value: str) -> int | None:
    """Extracts the first integer found in a NOTCH header value, matching
    the reference tool's tolerant `v71NotchDeg` (regex `-?\\d+`) rather than
    requiring an exact numeric string."""
    match = re.search(r"-?\d+", str(value or ""))
    return int(match.group()) if match else None


@dataclass(frozen=True)
class CrackCandidate:
    """One DIE_INFO row eligible to be marked as a crack — has a usable
    wafer_ring, FX:FY, and TX:TY within the declared substrate geometry.
    Rows failing any of those are simply never turned into a candidate,
    matching the reference tool's click handler refusing to mark them."""

    key: str  # f"{doc_index}:{layer}:{row_index}" — stable identity for toggling
    doc_index: int
    doc_name: str
    substrate_id: str
    layer: str
    source_die: DieInfo
    wafer_id: str  # normalized (trim+upper)
    fx: int
    fy: int
    tx: int
    ty: int
    output_xy: tuple[int, int]
    output_block: int | None
    notch: str  # the substrate's own raw NOTCH header string


@dataclass
class CrackSession:
    candidates: list[CrackCandidate] = field(default_factory=list)
    by_key: dict[str, CrackCandidate] = field(default_factory=dict)

    def wafer_ids(self) -> list[str]:
        return sorted({c.wafer_id for c in self.candidates})

    def rows_for_wafer(self, wafer_id: str) -> list[CrackCandidate]:
        return [c for c in self.candidates if c.wafer_id == wafer_id]

    def marked(self, marked_keys: list[str]) -> list[CrackCandidate]:
        """Resolves an ordered list of keys (the operator's click order —
        crack numbering is simply this order, 1-based) to candidates,
        silently dropping any key that isn't a real candidate (e.g. a
        stale key from a previous upload)."""
        return [self.by_key[k] for k in marked_keys if k in self.by_key]


def build_session(docs: list[tuple[str, StrateFile]], *, machine_type: MachineType = "DB") -> CrackSession:
    """`docs` is (source_file_name, parsed StrateFile) pairs — one entry
    per uploaded .strate file. All-or-nothing: raises on the first
    document with invalid geometry or a missing NOTCH rather than skipping
    it — see module docstring."""
    session = CrackSession()
    for doc_index, (name, substrate) in enumerate(docs):
        validate_geometry(substrate)
        notch_raw = str(substrate.notch).strip()
        if notch_degrees(notch_raw) is None:
            raise MissingNotchError(f"{name}（{substrate.substrate_id}）缺少有效NOTCH，無法確認Wafer方向")

        row_index = 0
        for layer, dies in (("primary", substrate.die_info), ("other", substrate.other_layer_die_info)):
            for die in dies:
                row_index += 1
                wafer_id = normalize_wafer_id(die.wafer_ring)
                wafer_xy = parse_xy(die.wafer_xy)
                sub_xy = parse_xy(die.sub_pos)
                if not wafer_id or wafer_xy is None:
                    continue
                if (
                    sub_xy is None
                    or not (0 <= sub_xy[0] < substrate.substrate_column)
                    or not (0 <= sub_xy[1] < substrate.substrate_row)
                ):
                    continue
                tx, ty = sub_xy
                fx, fy = wafer_xy
                out_xy = output_position(tx, ty, substrate.substrate_column, machine_type)
                key = f"{doc_index}:{layer}:{row_index}"
                candidate = CrackCandidate(
                    key=key,
                    doc_index=doc_index,
                    doc_name=name,
                    substrate_id=substrate.substrate_id,
                    layer=layer,
                    source_die=die,
                    wafer_id=wafer_id,
                    fx=fx,
                    fy=fy,
                    tx=tx,
                    ty=ty,
                    output_xy=out_xy,
                    output_block=output_block(out_xy[0], substrate.substrate_column, substrate.substrate_block),
                    notch=notch_raw,
                )
                session.candidates.append(candidate)
                session.by_key[key] = candidate

    if not session.candidates:
        raise ValueError("STRATE中沒有可用的完整Wafer ID或Wafer FX:FY")
    return session


@dataclass(frozen=True)
class WaferPoolRange:
    min_x: int
    max_x: int
    min_y: int
    max_y: int


def wafer_pool_range(rows: list[CrackCandidate]) -> WaferPoolRange:
    xs = [r.fx for r in rows]
    ys = [r.fy for r in rows]
    return WaferPoolRange(min(xs), max(xs), min(ys), max(ys))


def wafer_notch(rows: list[CrackCandidate]) -> int | None:
    """The pooled scatter's orientation comes from the FIRST row's own
    substrate — matches the reference tool's `v78NotchForRows`, which does
    not attempt to reconcile differing NOTCH values across pooled docs."""
    if not rows:
        return None
    return notch_degrees(rows[0].notch)


def local_view(fx: int, fy: int, rng: WaferPoolRange, notch: int, machine_type: MachineType = "DB") -> tuple[int, int]:
    """Normalizes a pooled wafer coordinate into a local, 0-based relative
    scatter position — NOT a true absolute wafer position (see module
    docstring).

    DB: plain identity normalization (no flip, no rotation) — see module
    docstring for the evidence basis.

    ESEC: mirrors the reference tool's `v78WaferView` exactly, including
    its fallback for any notch that isn't exactly 90/180/270 (treated the
    same as 0deg: a plain X-flip with no further rotation)."""
    if machine_type == "DB":
        return fx - rng.min_x, fy - rng.min_y

    n = notch % 360
    raw_x = rng.max_x - fx
    raw_y = fy - rng.min_y
    raw_max_x = rng.max_x - rng.min_x
    raw_max_y = rng.max_y - rng.min_y
    if n == 90:
        return raw_y, raw_max_x - raw_x
    if n == 180:
        return raw_max_x - raw_x, raw_max_y - raw_y
    if n == 270:
        return raw_max_y - raw_y, raw_x
    return raw_x, raw_y


@dataclass(frozen=True)
class ScatterPoint:
    key: str  # key of one representative candidate at this fx:fy (for a crack, the marked one)
    x: int
    y: int
    is_crack: bool
    crack_no: int | None


def wafer_scatter(
    session: CrackSession, wafer_id: str, marked_keys: list[str], machine_type: MachineType = "DB"
) -> tuple[WaferPoolRange, int | None, list[ScatterPoint]]:
    """The pooled local scatter for one wafer_id — one point per distinct
    FX:FY (matches the reference tool's dot-plot dedup, `v78DrawWafer`'s
    `unique=[...new Map(rows.map(r=>[r.fx+':'+r.fy,r])).values()]`), each
    flagged if any candidate sharing that FX:FY is currently marked."""
    pool = session.rows_for_wafer(wafer_id)
    if not pool:
        raise KeyError(f"no candidates for wafer_id {wafer_id!r}")
    rng = wafer_pool_range(pool)
    notch = wafer_notch(pool)
    n = notch if notch is not None else 0

    crack_no_by_key = {c.key: i + 1 for i, c in enumerate(session.marked(marked_keys))}
    grouped: dict[tuple[int, int], list[CrackCandidate]] = {}
    for c in pool:
        grouped.setdefault((c.fx, c.fy), []).append(c)

    points = []
    for (fx, fy), group in grouped.items():
        vx, vy = local_view(fx, fy, rng, n, machine_type)
        marked_in_group = next((c for c in group if c.key in crack_no_by_key), None)
        rep = marked_in_group or group[0]
        crack_no = crack_no_by_key.get(rep.key)
        points.append(ScatterPoint(key=rep.key, x=vx, y=vy, is_crack=crack_no is not None, crack_no=crack_no))
    return rng, notch, points


def crack_direction_label(notch: int | None) -> str:
    if notch == 270:
        return "270_RIGHT"
    return f"NOTCH_{notch}"


def crack_output_coord(candidate: CrackCandidate) -> str:
    from .mispick_analysis import col_name

    x, y = candidate.output_xy
    return col_name(x) + str(y + 1)


def crack_csv_rows(session: CrackSession, marked_keys: list[str], machine_type: MachineType = "DB") -> list[list]:
    """CSV rows for the currently-marked cracks, in click order (crack_no
    is simply that order, 1-based) — matches `v78CrackCsv`."""
    rows: list[list] = [CRACK_CSV_HEADER]
    for i, c in enumerate(session.marked(marked_keys), start=1):
        pool = session.rows_for_wafer(c.wafer_id)
        rng = wafer_pool_range(pool)
        notch = wafer_notch(pool)
        view_x, view_y = local_view(c.fx, c.fy, rng, notch if notch is not None else 0, machine_type)
        rows.append(
            [
                f"C{i}",
                c.substrate_id,
                c.doc_name,
                f"B{c.output_block}" if c.output_block else "",
                crack_output_coord(c),
                c.output_xy[0],
                c.output_xy[1],
                c.tx,
                c.ty,
                c.wafer_id,
                c.fx,
                c.fy,
                view_x,
                view_y,
                c.notch,
                "1",
                crack_direction_label(notch),
                "IMPORTED_LOCAL_ONLY",
            ]
        )
    return rows
