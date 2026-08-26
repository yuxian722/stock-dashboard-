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
  `DieInfo.from_line()` parses them completely unchanged, **including
  `wafer_xy`, with no transform at all**.

  2026/08/26大更正(推翻2026/08/21那次的結論)：先前這裡宣稱log的
  `wafer_xy`是`row:col`、需要跟`.strate`的`col:row`互換(`_swap_wafer_xy()`，
  已刪除)，是錯的。使用者這次同時提供了真實log(`BAB1420260801_04.0.log`)
  跟同一台machine對同一枚基板(`Z25709007096`)真正產生的`.strate`檔案，
  可以直接互相比對而不用猜——結果log的`StrateMap`交易裡`<DIE_INFO>`/
  `<DIE_INFO_OTHER_LAYER>`的224行(56+168)`<Item>`文字，跟真正`.strate`
  檔案自己的DIE_INFO/DIE_INFO_OTHER_LAYER逐行**完全一致，一個字都沒有
  不一樣**(見`test_extract_strate_files_die_info_matches_real_strate_byte_for_byte`)
  ——`wafer_xy`本來就已經是`.strate`格式自己的`col:row`，不需要任何轉換。

  那之前為什麼會覺得「swap才對」？因為當時拿`_swap_wafer_xy()`的輸出去
  跟一份真實`.frm`的`die_map`交叉比對(`test_extract_strate_files_wafer_xy_matches_real_frm_die_map`)，
  確認過49顆FC2643的die全部對到`frm.die_map`裡的bin=1——這個交叉比對本身
  沒有做錯，**但`frm.die_map`存的key其實是`(row,col)`不是`(col,row)`**
  (`frm_reader.py`解析FRM二進位格式時把兩個座標分量叫做`x,y`，但這兩個
  變數名稱本身就是誤導——第一個位元組實際上對應真正的row/列，不是col/欄)。
  等於是**兩個各自獨立、方向相反的欄位語意問題疊在一起**：不轉wafer_xy
  但用`frm.die_map.get((row,col))`查是對的；轉了wafer_xy但用
  `frm.die_map.get((col,row))`查「剛好」也對得上——兩個錯誤互相抵消，
  讓「swap wafer_xy」這個錯誤結論看起來像是通過了真實資料驗證。這次靠
  log-vs-.strate的直接比對(不透過任何中間轉換的FRM查表)才真正拆穿。

- `ASSY_LOT`/`OPER` never appear anywhere in this log — not in
  `StrateMap`, not in any other transaction type. `MAPPING_LOT` isn't in
  `StrateMap` either (only `WaferMap`/`WaferStart` carry it, for the
  wafer, not the substrate). All three are left blank in the extracted
  `StrateFile`, to be filled in by hand afterward — per user instruction
  2026/08/18, rather than guessing a cross-transaction correlation.

- `WaferStart` events: one per physical wafer, carrying a flat `<BinList>`
  string (`ColCount * RowCount` characters, one per die position — a
  digit for a bin kind, or a space for "no die there") — the same
  information an `.frm` file's die map holds.

  2026/08/26大更正：`<ColCount>`/`<RowCount>`這兩個標籤名稱**本身也跟
  `.strate`格式自己的col/row軸向對調**(跟上面`frm_reader.py`的`x,y`
  誤導性命名是同一種問題，只是換一個資料來源)——直接拿使用者提供的完整
  真實log交叉驗證：FC2643/EU014這片wafer，`wafer_xy`第二個分量(`.strate`
  格式裡代表row)實際數值範圍是0~45(46種)，第一個分量(col)在24以內——
  也就是log自己標的`ColCount`(46)其實對應`.strate`的row軸長度，
  `RowCount`(24)才對應`.strate`的col軸長度。`wafer_map_from_element()`
  已經把這個對調處理好：建構`WaferBinMap`時`columns=RowCount, rows=ColCount`，
  `BinList`的chunk索引(原本語意上的"row")對應`.strate`座標的col分量、
  chunk內字元位置(原本語意上的"col")對應`.strate`座標的row分量，這樣
  算出來的`(x=col,y=row)`才能直接跟`_die_list()`現在不轉換的`wafer_xy`
  對上，不需要任何字串層級的swap。`WaferUpload`的`<WAFER_INFO>`/
  `<ORG_WAFER_INFO>`區塊看起來相似，但只是零星的defect-code覆蓋資料，
  不是完整的bin map — 這裡不使用。
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
    """StrateMap's DIE_INFO `wafer_xy` needs no transform — see the module
    docstring's 2026/08/26 correction for why (a previous version of this
    function used to swap it; that swap was wrong, see below)."""
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
    col_count = _int_text(elem, "ColCount")
    row_count = _int_text(elem, "RowCount")
    binlist = bin_list_elem.text
    # 2026/08/26大更正：WaferStart的<ColCount>/<RowCount>標籤名稱跟
    # StrateMap的<DIE_INFO> wafer_xy(.strate格式本身的col:row)實際軸向是
    # 對調的——直接拿使用者提供的完整真實log(BAB1420260801_04.0.log)交叉
    # 驗證：這片wafer(FC2643/EU014layout)wafer_xy第二個分量(.strate格式
    # 裡代表row)實際數值範圍是0~45(46種)，第一個分量(代表col)範圍在
    # RowCount(24)以內——也就是log自己標的ColCount(46)其實對應.strate的
    # row軸長度，RowCount(24)對應.strate的col軸長度，跟命名剛好相反。
    # BinList是`RowCount`個長度`ColCount`的字串接起來，因此chunk索引
    # (0..RowCount-1)才是.strate座標的col分量，chunk內的字元位置
    # (0..ColCount-1)才是.strate座標的row分量。這裡建構WaferBinMap時
    # 把columns/rows對調成(row_count, col_count)、set_bin也對調成
    # (chunk索引, 字元位置)，這樣算出來的(x=col,y=row)才能直接對上
    # StrateFile.die_info的wafer_xy(不需要swap，見_die_list()的更正)。
    wafer_map = WaferBinMap(columns=row_count, rows=col_count)
    for chunk_idx in range(row_count):
        chunk = binlist[chunk_idx * col_count : (chunk_idx + 1) * col_count]
        for char_pos, ch in enumerate(chunk):
            if ch != " ":
                wafer_map.set_bin(chunk_idx, char_pos, ch)
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
