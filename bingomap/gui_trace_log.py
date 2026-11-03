"""Extract BINGO MAP die-transfer data straight from a Diebonder's own
**GUI trace log** (`GUI/ecslog*.log` inside the equipment's full
diagnostic export — e.g. the zip pulled after a power-off event, alarm
investigation, or any other on-machine troubleshooting dump).

2026/11/03使用者：他原本上傳的都是EAP/host端固定時間批次抓的SECS/AFC
log(`secs_log.py`處理的那種)，這次直接從設備本機匯出一整包診斷資料
(裡面混了Alarm/Config/DBHost GEM log/Rcg/WINLOG斷電留存等)，想抓裡面
比較「即時」(機台自己剛發生的，不用等EAP排程去抓)的資料來產生BINGO MAP。
查了使用者實際傳的檔案才發現：`GUI/ecslog*.log`完全不是SECS/AFC log，
是這台Diebonder**自己GUI程式**的內部tag變化追蹤log(`CObserver::
OnValueChange`，監控一個叫`DIEBONDER.ECS2UI_CMD`的COM tag)。每次「1
DIE BONDING END」，就會把SEMI E142標準(`xsd.E142-1.V1005.SubstrateMap`)
的`TransferMap` XML整包塞進一個叫`E142_TRANSFER_MAP`的VID值裡、序列化
成字串寫進這行log——而且是**兩層XML跳脫**(log本身的XML:後面先跳脫一層，
VIDValue字串裡的E142 XML又再跳脫一層，要`html.unescape()`兩次才拿得到
真正的XML)。另外這個log檔案本身用一般UTF-8/ASCII寫(不是`secs_log.py`
處理的UTF-16LE)——不用另外處理，`decode_secs_log()`本來就會自動偵測
退回UTF-8。

單一事件(一行log，但log裡這一行的XML內容自己又夾了真的換行字元，所以
不能單純按`\\n`切，要用每行開頭的時間戳記當entry邊界)範例(已解開兩層
跳脫後)：
    <MapData xmlns="urn:semi-org:xsd.E142-1.V1005.SubstrateMap">
      <SubstrateMaps>
        <SubstrateMap SubstrateType="Strip" SubstrateId="Z26912130176" ...>
          <Overlay MapName="WaferToStrip">
            <TransferMap FromSubstrateType="Wafer" FromSubstrateId="JE9C1A">
              <T FX="27" FY="15" TX="3" TY="0"/>
            </TransferMap>
          </Overlay>
        </SubstrateMap>
      </SubstrateMaps>
    </MapData>
一行就是一顆die：從來源wafer(`FromSubstrateId`)的`FX:FY`，搬到目標
strip(`SubstrateId`，等同這個專案的「基板」/substrate_id)的`TX:TY`——
直接對應`.strate`的`wafer_xy`/`sub_pos`，不需要像WaferStart的BinList
那樣另外猜8種方向：這裡的`<T>`本身就是唯一的真相來源，沒有獨立的背景
bin圖可以互相校正，也不需要。bin固定填"1"：E142 TransferMap只會記錄
「真的被搬走」的die，壞品本來就不會出現在這個事件流裡，等同良品才有
記錄。

**跟`extract_strate_files()`最大的不同、使用者要知道的限制**：這個
事件流完全沒有`ASSY_LOT`/`MAPPING_LOT`/`OPER`/`EQPID`——這些是EAP主機
側才知道的批號/站別/設備代號，是host下發工單(`JobInfoFromAFC`)才會
記錄的東西，機台自己的GUI不會、也不需要知道這些，所以組出來的
`StrateFile`這幾個欄位一定是空字串，使用者如果要下載存檔，記得自己
補上。

**跨檔案合併**：這個GUI trace log每隔幾分鐘就會自動換檔(檔名裡的時間戳
是「這個檔案開始寫」的時間，不是事件時間)，一枚strip生產的時間常常
橫跨不只一個檔案——不能像`extract_strate_files()`那樣每個檔案各自獨立
解析成一批`StrateFile`，一定要把同一批上傳裡**所有**trace log檔案的
事件先收集起來、再按`SubstrateId`分組合併，才不會把同一枚基板拆成好
幾個殘缺的片段。所以這裡的進入點函式吃的是`list[str]`(一整批texts)，
不是像`extract_strate_files(text)`那樣單一檔案。"""
from __future__ import annotations

import html
import re

from .strate import DieInfo, StrateFile

# 2026/11/03事件偵測用的標記字串——這個VID名稱只會出現在這種GUI trace
# log裡，SECS/AFC log跟現成.strate檔案都不可能出現，拿來判斷「這份log
# 是不是這種類型」夠明確、也夠便宜(純substring檢查，不用先嘗試解析)。
TRACE_MARKER = "E142_TRANSFER_MAP"

_ENTRY_START_RE = re.compile(r"(?m)^(\d{2})-(\d{2})-(\d{4}) (\d{2}):(\d{2}):(\d{2}):(\d{3}):")
_TRANSFER_RE = re.compile(
    r'SubstrateType="Strip" SubstrateId="([^"]*)".*?'
    r'FromSubstrateType="Wafer" FromSubstrateId="([^"]*)".*?'
    r'<T FX="(\d+)" FY="(\d+)" TX="(\d+)" TY="(\d+)"',
    re.DOTALL,
)


def is_gui_trace_log_text(text: str) -> bool:
    """Cheap, specific format check — see `TRACE_MARKER` above."""
    return TRACE_MARKER in text


def _iter_transfer_events(text: str):
    """Yields (timestamp, substrate_id, wafer_ring, fx, fy, tx, ty) for every
    single-die transfer event in one decoded trace-log text. A "line" here
    is NOT a bare `\\n`-delimited line — the embedded E142 XML itself
    contains a real newline (right after its own `<?xml ...?>` declaration),
    so a naive `\\n` split would sever an entry's timestamp from its own
    XML payload. Instead, entries are anchored on the timestamp pattern
    that starts every real log line (`DD-MM-YYYY HH:MM:SS:mmm:`), and each
    entry runs until the next one of those (or end of text)."""
    starts = list(_ENTRY_START_RE.finditer(text))
    for i, m in enumerate(starts):
        entry_end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        entry = text[m.start() : entry_end]
        if TRACE_MARKER not in entry:
            continue
        # 兩層跳脫：log本身的XML:後面一層，E142 XML字串裡的VIDValue又
        # 一層——兩次html.unescape()是冪等安全的，就算某份log只跳脫了
        # 一層，第二次unescape對已經是明文的內容不會有副作用。
        decoded = html.unescape(html.unescape(entry))
        tm = _TRANSFER_RE.search(decoded)
        if tm is None:
            continue
        substrate_id, wafer_ring, fx, fy, tx, ty = tm.groups()
        day, month, year, hh, mm, ss, _ms = m.groups()
        timestamp = f"{year}{month}{day}{hh}{mm}{ss}"
        yield timestamp, substrate_id, wafer_ring, int(fx), int(fy), int(tx), int(ty)


def extract_strate_files_from_gui_trace(texts: list[str]) -> list[StrateFile]:
    """Entry point — see module docstring for why this takes the whole
    batch's texts at once instead of one file at a time.

    2026/11/03實測真實資料才發現：同一顆die的`CObserver::OnValueChange`
    常常連續寫出好幾行一模一樣的紀錄(時間戳記、FX/FY/TX/TY全部相同)——
    這台設備GUI內部顯然不只一個地方在監聽同一個tag，各自各寫一次log，
    不是真的有好幾顆die疊在同一個位置。拿使用者的真實診斷包測過：
    其中一枚基板在log裡出現589行事件，但扣掉完全重複的(timestamp,
    substrate_id,wafer_ring,fx,fy,tx,ty)七元組之後，只剩37個不重複的
    實際位置——用一個`set()`去重，不能只靠`(tx,ty)`去重(萬一同一個
    位置真的補打過兩次、FX/FY換了，那才是兩顆不同的die，要分開留著)。"""
    seen: set[tuple] = set()
    by_substrate: dict[str, list[tuple]] = {}
    for text in texts:
        if not is_gui_trace_log_text(text):
            continue
        for event in _iter_transfer_events(text):
            if event in seen:
                continue
            seen.add(event)
            timestamp, substrate_id, wafer_ring, fx, fy, tx, ty = event
            by_substrate.setdefault(substrate_id, []).append(event)

    out: list[StrateFile] = []
    for substrate_id, events in by_substrate.items():
        events.sort(key=lambda e: e[0])  # 按時間戳記排序，index照順序編號
        max_tx = max(e[5] for e in events)
        max_ty = max(e[6] for e in events)
        die_info = [
            DieInfo(
                index=i + 1,
                wafer_ring=wafer_ring,
                wafer_xy=f"{fx}:{fy}",
                sub_pos=f"{tx}:{ty}",
                bin="1",
                timestamp=timestamp,
            )
            for i, (timestamp, _sid, wafer_ring, fx, fy, tx, ty) in enumerate(events)
        ]
        out.append(
            StrateFile(
                assy_lot="",
                mapping_lot="",
                eqpid="",
                oper="",
                substrate_id=substrate_id,
                substrate_row=max_ty + 1,
                substrate_column=max_tx + 1,
                substrate_block=1,
                total_bond_die_qty=len(die_info),
                good_die=len(die_info),
                die_info=die_info,
            )
        )
    return out
