"""Extract .strate-equivalent substrate data and wafer bin maps directly
from a machine's SECS/AFC transaction log — a plain-text trace of embedded
XML transaction fragments interleaved with DEBUG/INFO log lines, NOT raw
SECS-II binary.

This is the "④ STRATE補檔 XML合併" nav item (`_nav.html`), built
2026/08/18 from a real BAB14 log the user provided. Findings, all verified
against that real log (see bingomap/tests/fixtures/secs_log_sample.log,
trimmed from it) rather than guessed:

- The log file itself is UTF-16LE with no BOM (every ASCII byte followed
  by a 0x00 byte) — decode_secs_log() detects and handles this; also
  handles a BOM if one is ever present, and falls back to UTF-8.

- `StrateMap` events (`Type="Event"`): one per completed substrate. Their
  `<DIE_INFO>`/`<DIE_INFO_OTHER_LAYER>` `<Item>` rows are ALREADY in the
  exact 9-field CSV format `.strate` DIE_INFO lines use
  (`index,wafer_ring,wafer_xy,sub_pos,bin,f6,f7,timestamp,f9`) —
  `DieInfo.from_line()` parses them completely unchanged.

- `ASSY_LOT`/`OPER` never appear anywhere in this log — not in
  `StrateMap`, not in any other transaction type. `MAPPING_LOT` isn't in
  `StrateMap` either (only `WaferMap`/`WaferStart` carry it, for the
  wafer, not the substrate). All three are left blank in the extracted
  `StrateFile`, to be filled in by hand afterward — per user instruction
  2026/08/18, rather than guessing a cross-transaction correlation.

- `WaferStart` events: one per physical wafer, carrying a flat `<BinList>`
  string (`ColCount * RowCount` characters, one per die position — a
  digit for a bin kind, or a space for "no die there") — the same
  information an `.frm` file's die map holds. The row/column orientation
  was verified against a real StrateMap's DIE_INFO from the SAME
  wafer_ring (frame): row index = DIE_INFO's own wafer_xy X component,
  character position within the row = DIE_INFO's own Y component — 189
  of 196 dies (96%) matched exactly; the handful of mismatches were dies
  the BinList (captured at wafer-start) called good('1') but which were
  logged bin='7' by the time they were actually picked minutes later — a
  real reclassification, not a coordinate error. `WaferUpload`'s
  `<WAFER_INFO>`/`<ORG_WAFER_INFO>` sections look superficially similar
  but are sparse defect-code overlays, not a full bin map — NOT used
  here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from xml.etree import ElementTree as ET

from .strate import DieInfo, StrateFile
from .wafer_map import WaferBinMap

# A self-closing `<Transaction ... />` (e.g. every empty Request half of a
# Request/Reply pair) has no matching `</Transaction>` of its own. The
# naive single-alternative pattern `<Transaction\b[^>]*>.*?</Transaction>`
# still "matches" one — its `[^>]*>` happily consumes the `/>` as if it
# were a plain opening tag's `>`, then the non-greedy `.*?</Transaction>`
# swallows everything up to the NEXT transaction's closing tag, silently
# merging two unrelated transactions into one bogus block (and, since that
# block is no longer valid XML on its own, ET.fromstring then drops BOTH
# transactions instead of just the bogus one — found 2026/08/19 via a
# real log where this genuinely deleted the second of two
# S7F25FormattedPPRequest Reply captures). The first alternative here
# matches a self-closing tag on its own (nothing to merge into), so the
# second alternative only ever fires on a real opening tag.
_TRANSACTION_RE = re.compile(
    r"<Transaction\b[^>]*/>|<Transaction\b[^>]*>.*?</Transaction>", re.S
)
_NAME_RE = re.compile(r'name="([^"]*)"')
_TYPE_RE = re.compile(r'Type="([^"]*)"')


def decode_secs_log(data: bytes) -> str:
    """The real log this module was built from is UTF-16LE with no BOM —
    every ASCII byte is followed by a 0x00 byte. Detect that (a BOM if
    present, otherwise a high proportion of NUL bytes in a sample), and
    fall back to UTF-8 for anything else."""
    if data.startswith(b"\xff\xfe"):
        return data[2:].decode("utf-16-le", errors="replace")
    if data.startswith(b"\xfe\xff"):
        return data[2:].decode("utf-16-be", errors="replace")
    sample = data[:512]
    if sample.count(b"\x00") > len(sample) // 4:
        return data.decode("utf-16-le", errors="replace")
    return data.decode("utf-8", errors="replace")


def iter_transactions(text: str):
    """Yields (name, type, xml.etree.Element) for every <Transaction>
    block in the log. This is a log file, not a validated XML document —
    DEBUG/INFO trace lines interleave with the transaction payloads, and
    a block occasionally won't parse as XML on its own (e.g. truncated by
    a log rotation mid-write) — those are skipped rather than aborting
    extraction of the rest of a 50k-line log."""
    for m in _TRANSACTION_RE.finditer(text):
        raw = m.group(0)
        name_m = _NAME_RE.search(raw)
        type_m = _TYPE_RE.search(raw)
        if not name_m or not type_m:
            continue
        try:
            elem = ET.fromstring(raw)
        except ET.ParseError:
            continue
        yield name_m.group(1), type_m.group(1), elem


def _text(elem: ET.Element, tag: str, default: str = "") -> str:
    child = elem.find(tag)
    if child is None or child.text is None:
        return default
    return child.text.strip()


def _int_text(elem: ET.Element, tag: str, default: int = 0) -> int:
    try:
        return int(_text(elem, tag))
    except ValueError:
        return default


def _die_list(elem: ET.Element, tag: str) -> list[DieInfo]:
    parent = elem.find(tag)
    if parent is None:
        return []
    return [
        DieInfo.from_line(item.text.strip())
        for item in parent.findall("Item")
        if item.text and item.text.strip()
    ]


def strate_file_from_element(elem: ET.Element) -> StrateFile:
    """Build a StrateFile from one <Transaction name="StrateMap"> element.
    ASSY_LOT/MAPPING_LOT/OPER aren't in this transaction at all (see
    module docstring) — left blank for the operator to fill in by hand."""
    return StrateFile(
        assy_lot="",
        mapping_lot="",
        eqpid=_text(elem, "EQPID"),
        oper="",
        substrate_id=_text(elem, "SUBSTRATE_ID"),
        substrate_row=_int_text(elem, "RowCount"),
        substrate_column=_int_text(elem, "ColCount"),
        substrate_block=_int_text(elem, "BlockCount"),
        out_mgz_slot_no=_text(elem, "OUT_MGZ_SLOT_NO"),
        total_bond_die_qty=_int_text(elem, "TOTAL_BOND_DIE_QTY"),
        good_die=_int_text(elem, "GOOD_DIE"),
        run_time=_text(elem, "RUN_TIME"),
        notch=_text(elem, "NotchMap"),
        ref=_text(elem, "Ref"),
        t2_point=_text(elem, "T2_POINT", "NA"),
        t2_flat=_text(elem, "T2_Flat", "NA"),
        die_info=_die_list(elem, "DIE_INFO"),
        other_layer_die_info=_die_list(elem, "DIE_INFO_OTHER_LAYER"),
    )


def extract_strate_files(text: str) -> list[StrateFile]:
    """One StrateFile per completed substrate (`StrateMap` Event)."""
    return [
        strate_file_from_element(elem)
        for name, ttype, elem in iter_transactions(text)
        if name == "StrateMap" and ttype == "Event"
    ]


@dataclass
class SecsWaferMap:
    frame_id: str
    wafer_id: str
    wafer_map: WaferBinMap


def wafer_map_from_element(elem: ET.Element) -> SecsWaferMap | None:
    bin_list_elem = elem.find("BinList")
    if bin_list_elem is None or not bin_list_elem.text:
        return None
    columns = _int_text(elem, "ColCount")
    rows = _int_text(elem, "RowCount")
    binlist = bin_list_elem.text
    wafer_map = WaferBinMap(columns=columns, rows=rows)
    # Row index = wafer_xy's X component, character position within the
    # row = wafer_xy's Y component — verified against a real StrateMap's
    # DIE_INFO from the same wafer_ring/FrameID, see module docstring.
    for x in range(rows):
        row_str = binlist[x * columns : (x + 1) * columns]
        for y, ch in enumerate(row_str):
            if ch != " ":
                wafer_map.set_bin(x, y, ch)
    return SecsWaferMap(
        frame_id=_text(elem, "FrameID"),
        wafer_id=_text(elem, "WaferID"),
        wafer_map=wafer_map,
    )


def extract_wafer_maps(text: str) -> list[SecsWaferMap]:
    """One SecsWaferMap per physical wafer (`WaferStart` Event) that
    actually carries a <BinList> — a handful of WaferStart events in the
    real log had no BinList element at all (skipped, not an error)."""
    out = []
    for name, ttype, elem in iter_transactions(text):
        if name == "WaferStart" and ttype == "Event":
            wm = wafer_map_from_element(elem)
            if wm is not None:
                out.append(wm)
    return out
