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


# ---- Excel target-parameter checklist comparison (2026/08/20) ----
#
# 使用者提供的真實Excel(4欄: Item/Name/ID number/ID name)確認："ID number"
# 就是CCODE——跟199組固定基準參數比對，185組CCODE吻合，代表這是正確的比對
# 欄位，不是用參數名稱比對(名稱在真實資料裡本來就有重複，例如同一種
# "Rec. threshold matching rate"在好幾個不同的辨識設定底下各自出現一次，
# CCODE才是唯一鍵)。"Item"欄只有每組第一列才有值(其餘是合併儲存格視覺
# 效果)，屬於分類階層，不是比對用的鍵。
#
# .xlsx本身的讀取(openpyxl)是webapp/app.py的責任——這個模組維持只吃/吐
# 純Python資料，不依賴openpyxl，方便單元測試(跟這個套件其他模組一致的
# 原則)。


@dataclass
class ChecklistRow:
    """One row from the user's target-parameter checklist, already parsed
    into plain data by the caller."""

    category: str
    name: str
    ccode: str
    id_name: str


@dataclass
class ChecklistComparison:
    # CCODE 同時存在基準清單跟checklist的項目 (可能名稱有出入，見name_mismatch)
    matched: list[dict]
    # 基準清單裡有，但checklist沒有的項目 (機台目前有、但checklist沒列出來)
    machine_only: list[dict]
    # checklist裡有，但基準清單沒有的項目 (使用者說的「還沒加進去的」)
    checklist_only: list[ChecklistRow]
    # checklist裡同一個CCODE出現不止一次的分組——2026/08/20用使用者的真實
    # Excel發現有9組CCODE重複(比對整份250列裡有明顯的整段複製貼上痕跡)，
    # 不要靜默選第一筆/覆蓋，直接回報請使用者自己確認是不是貼錯
    duplicate_ccodes: list[dict]


def compare_checklist(
    baseline_params: list[SecsParam], checklist_rows: list[ChecklistRow]
) -> ChecklistComparison:
    """Check-list式比對：以CCODE為鍵，把使用者的目標參數清單(checklist_rows)
    跟目前機台的基準參數清單(baseline_params)分成三類——見上面模組註解。
    checklist_rows裡重複的CCODE不會被丟棄，也不會被靜默去重覆蓋：比對本身
    只取每個CCODE的第一筆代表，但完整的重複清單另外回報在
    duplicate_ccodes，讓使用者自己判斷是否為貼錯。"""
    by_ccode: dict[str, list[ChecklistRow]] = {}
    for row in checklist_rows:
        by_ccode.setdefault(row.ccode, []).append(row)

    duplicate_ccodes = [
        {"ccode": ccode, "rows": rows} for ccode, rows in by_ccode.items() if len(rows) > 1
    ]

    unique_checklist = {ccode: rows[0] for ccode, rows in by_ccode.items()}
    baseline_by_ccode = {p.ccode: p for p in baseline_params}

    matched = []
    checklist_only = []
    for ccode, row in unique_checklist.items():
        base = baseline_by_ccode.get(ccode)
        if base is None:
            checklist_only.append(row)
        else:
            matched.append(
                {
                    "ccode": ccode,
                    "baseline_name": base.name,
                    "checklist_name": row.name,
                    "id_name": row.id_name,
                    "category": row.category,
                    "name_mismatch": base.name.strip() != row.name.strip(),
                }
            )

    machine_only = [
        {"ccode": p.ccode, "name": p.name}
        for p in baseline_params
        if p.ccode not in unique_checklist
    ]

    return ChecklistComparison(
        matched=matched,
        machine_only=machine_only,
        checklist_only=checklist_only,
        duplicate_ccodes=duplicate_ccodes,
    )
