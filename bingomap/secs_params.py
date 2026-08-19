"""Extract machine SECS "formatted process program" parameters (Equipment
Constants / recipe parameters) from a SECS/AFC transaction log — the
`S7F25FormattedPPRequest` transaction (SECS-II S7F25, a standard "Process
Program request" message; "Formatted" here just names this specific
transaction template in the log, same log format as bingomap/secs_log.py).

Real log confirmed 2026/08/19 (same BAB14 log used throughout secs_log.py):
each `S7F25FormattedPPRequest` `Type="Reply"` transaction carries a
`<DataList>` with `PP_ID`/`MDLN`/`SOFTREV` (which recipe/model/software
revision this parameter snapshot is for) and a flat list of `<Item>`
elements, each with:

    <CCODE>285278212</CCODE>
    <PPARM>No. of blocks</PPARM>   <!-- name -->
    <PPARM />                       <!-- unit (often empty) -->
    <PPARM>F8</PPARM>               <!-- format code -->
    <PPARM>1</PPARM>                <!-- current value -->
    <PPARM>0</PPARM>                <!-- min -->
    <PPARM>999</PPARM>              <!-- max -->

Always exactly 6 `<PPARM>` per `<Item>` in the real log (199 items in the
one recipe captured there) — a parser that finds some other count raises
rather than guessing which field is missing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from xml.etree import ElementTree as ET

# See bingomap/secs_log.py's identical constant for why the self-closing
# alternative is required: without it, a self-closing `<Transaction .../>`
# (every empty Request half of a pair) gets merged with whatever
# transaction follows, and both get silently dropped. Found 2026/08/19 via
# the real log: it deleted the SECOND of two real
# S7F25FormattedPPRequest Reply captures (TID=58203) because there was no
# other transaction's closing tag between that Request and its own Reply
# for the naive pattern to stop at.
_TRANSACTION_RE = re.compile(
    r"<Transaction\b[^>]*/>|<Transaction\b[^>]*>.*?</Transaction>", re.S
)
_NAME_RE = re.compile(r'name="([^"]*)"')
_TYPE_RE = re.compile(r'Type="([^"]*)"')


class SecsParamsFormatError(ValueError):
    """Raised when a S7F25FormattedPPRequest <Item> doesn't have the
    expected 6 <PPARM> fields — rather than silently guessing which one
    is missing."""


@dataclass
class SecsParam:
    ccode: str
    name: str
    unit: str
    format: str
    value: str
    min: str
    max: str


@dataclass
class PPParamSnapshot:
    pp_id: str
    mdln: str
    softrev: str
    tid: str
    params: list[SecsParam]


def _text(elem: ET.Element, tag: str, default: str = "") -> str:
    child = elem.find(tag)
    if child is None or child.text is None:
        return default
    return child.text.strip()


def _param_from_item(item: ET.Element) -> SecsParam:
    ccode = _text(item, "CCODE")
    pparms = [c.text.strip() if c.text else "" for c in item.findall("PPARM")]
    if len(pparms) != 6:
        raise SecsParamsFormatError(
            f"CCODE={ccode!r} 有 {len(pparms)} 個 PPARM 欄位，預期是6個(名稱/單位/格式/數值/下限/上限)"
        )
    name, unit, fmt, value, min_, max_ = pparms
    return SecsParam(ccode=ccode, name=name, unit=unit, format=fmt, value=value, min=min_, max=max_)


def _snapshot_from_element(elem: ET.Element, tid: str) -> PPParamSnapshot:
    data_list = elem.find("DataList")
    if data_list is None:
        return PPParamSnapshot(pp_id="", mdln="", softrev="", tid=tid, params=[])
    params = [_param_from_item(item) for item in data_list.findall("Item")]
    return PPParamSnapshot(
        pp_id=_text(data_list, "PP_ID"),
        mdln=_text(data_list, "MDLN"),
        softrev=_text(data_list, "SOFTREV"),
        tid=tid,
        params=params,
    )


def extract_pp_param_snapshots(text: str) -> list[PPParamSnapshot]:
    """One PPParamSnapshot per `S7F25FormattedPPRequest` Reply transaction
    in the log — reuses the same tolerant per-block XML parsing as
    bingomap/secs_log.py (skip a block that doesn't parse as XML rather
    than aborting the whole log)."""
    snapshots = []
    for m in _TRANSACTION_RE.finditer(text):
        raw = m.group(0)
        name_m = _NAME_RE.search(raw)
        type_m = _TYPE_RE.search(raw)
        if not name_m or not type_m:
            continue
        if name_m.group(1) != "S7F25FormattedPPRequest" or type_m.group(1) != "Reply":
            continue
        try:
            elem = ET.fromstring(raw)
        except ET.ParseError:
            continue
        tid_m = re.search(r'TID="([^"]*)"', raw)
        snapshots.append(_snapshot_from_element(elem, tid_m.group(1) if tid_m else ""))
    return snapshots
