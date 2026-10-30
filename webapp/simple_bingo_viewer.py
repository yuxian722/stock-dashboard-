"""SECS LOG BINGO MAP 檢視器 — 簡化版獨立小工具.

使用者2026/10/28的要求：原本④STRATE補檔頁功能太多，這次要一個「執行檔
點進去就開啟」的簡單版本：上傳SECS log → 每一枚基板各自秀出BINGO MAP
格子圖(可以跟實物肉眼核對) + 對應的.strate檔案 → 核對過的直接下載。

2026/10/29大改版：使用者決定把整個工具大砍成只留「補資料」這一件事
(②誤吸偏移/③Crack位置回推/⑤上片狀態人工確認/⑥SECS格式化參數全部不要)，
而且只做「A. 資料本身已經完整(SECS log或現成.strate)，只是要看圖核對、
下載」這個情境，不做①頁原本「從空白wafer圖手動點座標建立全新檔案」那個
情境(B)——B之後要不要做、怎麼做，另外再討論，這次先把A做到「簡單明瞭
好操作」。

新版面：左半wafer圖(這一枚基板來源的那片wafer，依bin上色，疊加一層標示
「這一枚基板用了wafer上的哪些格子」)、右半這一枚自己的BINGO MAP格子圖，
畫面左側一欄列出這批所有基板(可能到20幾枚)，點哪一枚兩邊的圖就換成哪
一枚的。wafer圖跟bin顏色/疊加標示的畫法，直接照抄`strate_xml.js`裡
`renderWaferGrid()`/`BIN_COLORS`/`matchedSubstrates`這一整套已經驗證過
的邏輯(同一個專案不要自己重寫一份座標系統)——疊加用的CSS類別特地選了
`.focus`(只加外框、不蓋掉底色)而不是`.referenced`(會用純色蓋掉格子，
會讓wafer自己的bin顏色看不到)，因為這裡要同時看到「這格本來是什麼bin」
跟「這格屬不屬於目前選到的基板」兩個資訊，不能只留其中一個。

這次沒有接FRM二進位讀取——wafer圖的資料來源是log自己的`WaferStart`事件
(`extract_wafer_maps()`，跟④頁同一套)，方向已經由這套函式自動比對同一
份log裡這片wafer自己的`StrateMap`已知位置校正過，不需要像①頁處理FRM
檔案時那樣，另外給swap_xy/mirror_x/mirror_y三個手動勾選框——這也是這次
「簡單明瞭」具體省下的一塊，不是漏做，是這個資料來源本來就不需要。

刻意做成完全獨立的Flask app(不是app.py裡再加一個路由)，理由：
- 「簡單一點」的要求，這支檔案只做一件事，不用在那支已經有6個分頁、
  上千行的app.py裡再找地方塞新邏輯，之後要維護/刪除這個簡化版也不會
  牽動原本的工具。
- 仍然掛同一個`webapp/templates`/`webapp/static`資料夾，直接共用
  style.css既有的`.substrate-cell`/`.lyr-substrate-grid`視覺樣式(跟
  ①補資料頁BINGO MAP長得一樣，使用者已經認得)，不用重新設計一套。
- 解析SECS log的邏輯直接呼叫`bingomap.secs_log.extract_strate_files()`
  ——這個專案裡唯一一套已經拿真實log/.strate交叉驗證過的parser，不要
  自己重寫一份。

「正向／反向」顯示切換：2026/08/27的真實案例(見bingomap/CLAUDE.md「金邊
朝下」機台那則)已經用真實SECS log + Bingo Map Query報表交叉驗證過結論
——`.strate`檔案本身的`sub_pos`座標是機台固定的內部座標系統，跟金邊朝
哪邊無關，不需要也不該去改；使用者實際感受到的「方向不一樣」，是下游
報表工具自己的「列反過來、欄不動」顯示轉換。這支簡化版工具的「反向」
選項就是重現同一種**純顯示層**轉換(只影響畫面上的格子怎麼排，絕對不會
改到回傳/下載的`.strate`文字內容一個字)，不是又猜一次座標公式——使用者
拿實物比對、哪個方向對得上就切哪個，兩個方向之間可以隨時切換重畫，不
需要重新上傳log。

2026/10/29再追加：使用者實際的log資料夾(`AFC/Log/<EQPID>`)裡，每個檔案
都已經是`.log.zip`(壓縮過的)，不是解壓縮好的純文字`.log`——一開始只接受
base64後直接丟給`decode_secs_log()`，餵進去的其實是zip的二進位內容，
解碼出來自然是亂碼、`extract_strate_files()`找不到任何`StrateMap`交易，
使用者看到的「這份log裡沒有找到StrateMap(基板)資料」這個錯誤訊息因此
是誤導的(聽起來像是log本身沒有資料，其實是根本沒解壓縮)。改成：收到的
位元組如果是zip格式(開頭`PK`)，自動解壓縮，裡面每個`.log`/`.txt`項目各自
decode；如果zip裡還包了zip(使用者提到v87支援「選整個LOG資料夾壓成的
zip，裡面包.log.zip」這種巢狀情況)，遞迴再解一層。解出來的每份log各自
呼叫`extract_strate_files()`/`extract_wafer_maps()`，結果合併成同一批
(一次選一整個資料夾的zip，等於一次看完好幾天的基板+wafer資料)。

2026/10/29再追加(工號登入+下載紀錄)：使用者要求「登入時需輸入工號，若
有修改在記錄起來」。這支工具目前唯一會真的「產生後果」的動作是下載
——沒有像v87那樣可以在畫面上點格子真的改資料，所以「修改」在這裡的
意思就是「確認、下載了這一枚的.strate檔案」，不是每次切正向/反向、
每次點選清單都要記錄(那只是在看，還沒有任何人對這份資料下決定)。

設計成這樣：
- 工號**不是帳號密碼驗證**，這是內部現場工具，沒有後端使用者資料庫，
  目的是「可追溯是誰確認/下載的」，不是「擋人進不去」——打開頁面先
  跳一個「輸入工號」畫面，有填就能進，不檢查工號格式或是否存在。
- 每按一次「下載」，前端先呼叫這支後端的`/api/simple_bingo/log_download`
  記一筆(工號、時間、流水號、檔名、目前的正向/反向狀態)，**不等後端
  回應結果擋住下載**——記錄失敗(例如硬碟寫不進去)不應該讓使用者連檔案
  都拿不到，只在畫面上顯示一行警告，不是阻斷性的錯誤。
- 記錄寫成本機一個CSV檔(`simple_bingo_viewer_downloads.csv`，跟這支
  Python檔案同一個資料夾)，每次下載append一行，不需要資料庫——現場
  電腦直接用Excel/記事本打開就能看，跟這個專案一貫「簡單、不用額外
  安裝東西」的原則一致。這個檔案本身會累積真實現場資料，已經加進
  `.gitignore`，不會被誤commit上去。

2026/10/29再追加(手動補空白位置)：使用者反映BINGO MAP上常常有空白位置
(例如漏pick、或這份log本來就沒記錄到)，要求「可以有一個bingomap圖檔可以
讓我編輯...點選左邊wafer讓我框選座標」——這是這個專案在app.js(④頁)已經
做過、驗證過的「補資料」情境(這支簡化版最早決定只做「方案A：資料已經
完整，只看圖核對下載」，方案B「手動從wafer圖點座標填入」當時explicitly
deferred，這次使用者要求補上B)。

跟使用者確認過的設計決策：
- **填入順序**：在wafer圖上框選/點選好幾顆要填入的die後，不用使用者再
  一格一格指定「這顆填哪個空白位置」，而是依照這枚基板自己bounding box
  的column-major順序(跟`bingomap/blank_generator.py`同一種慣例：外層
  loop欄、內層loop列，都由小到大)自動依序對應填入目前還空白的位置——
  跟app.js舊版「框選wafer→點BINGO MAP隨便一格→按順序自動分配」同一種
  使用者已經熟悉、已經驗證過的心智模型，不是重新設計一套。
- **只能選良品(bin=1)**：跟app.js的`toggleStagePick()`同一條規則——不能
  手動把一顆壞die放進良品位置。
- **沒有獨立的「空白骨架」資料來源**：app.js的補資料情境是從FRM讀出來的
  完整空白骨架(每個合法位置都在，只是沒填)去配對；這支工具的基板資料
  直接來自SECS log解析(`StrateFile`)，log裡本來就只記錄「真的有die」的
  位置、完全沒有「這個位置合法但目前空白」的清單。這裡退而求其次：拿
  這枚基板自己bounding box內「目前沒被填」的格子當作可填目标，不去驗證
  這些格子是不是真的落在這枚基板的物理形狀內(例如被去角的corner)——
  這跟整支工具一貫的「拿實物比對、相信操作員肉眼判斷」設計哲學一致
  (不引入一套我們沒有可靠資料來源能正確做的形狀驗證)，但也代表**理論上
  使用者可以手動填到形狀外的角落**，是刻意接受的已知限制，不是沒注意到。
- **後端重新產生檔案**：前端只送picks清單，後端用`StrateFile.parse()`/
  `to_text()`處理格式——不在前端JavaScript另外重寫一份序列化邏輯，避免
  前後端格式兩邊維護、容易走樣。

2026/10/29再更正：上面這版做出來(`/api/simple_bingo/apply_picks`，補進
「目前選到的這枚基板」自己的空白位置、合併回同一份檔案下載)之後，使用
者看了實際畫面回報「你是不是誤會我的意思」——沒有要補某一枚既有基板的
缺口，要的是完全獨立、不綁定清單裡任何一枚基板的全新基板：自己輸入
SUBSTRATE_ID、從wafer圖挑die填進一張完全空白的BINGO MAP、下載一份獨立
全新的`.strate`檔案，不跟任何既有資料合併。用`AskUserQuestion`當面
確認過這個方向(而不是再猜一次)，選項是「獨立建立全新基板」。

改成`/api/simple_bingo/build_new_substrate`：
- **形狀/其他欄位哪裡來**：使用者沒有另外畫一個「輸入列數欄數」的UI，
  這支工具就近拿「目前清單裡選到的那一枚基板」當樣板——同一片wafer上
  通常有好幾枚同形狀的基板，清單裡隨便一枚現成的就能提供
  ASSY_LOT/MAPPING_LOT/EQPID/OPER/SUBSTRATE_ROW/SUBSTRATE_COLUMN/
  SUBSTRATE_BLOCK/NOTCH/Ref/T2_POINT/T2_Flat這些欄位的合理預設值(同一片
  wafer、同一個job，這些欄位幾乎必然相同)，只有SUBSTRATE_ID是這枚全新
  基板真正需要使用者自己輸入的——不是又多加一套表單。
- **可填位置＝整個宣告形狀，不是「扣掉已有的」**：跟補缺口版的關鍵差異
  ——這裡`targets`是`range(SUBSTRATE_COLUMN) x range(SUBSTRATE_ROW)`的
  全部組合(column-major)，因為這次是從零開始蓋，不是在既有基板上補洞。
  沒有引入`bingomap/assignment.py`的`assign_dies()`(雖然語意上更接近)，
  因為那套函式需要一個「`die_info`已經窮舉所有合法位置」的真正blank
  skeleton StrateFile當輸入，這裡沒有這種骨架可用(只有宣告的
  列數x欄數)，硬塞進去還要多一層「造一個假骨架」的轉換，不如直接寫
  這段迴圈來得直接。
- **前端即時預覽、不用「先暫存再送出套用」**：補缺口版需要分「暫存
  (stagedPicks)→按套用→後端幫忙套進既有基板」三步，是因為要跟既有真實
  資料做column-major配對；這次重新設計成純前端狀態——選的picks本身就是
  要蓋的全新基板全部內容，框選的當下直接重畫這張空白BINGO MAP(不用等
  後端來回)，只有真正「下載」那一刻才呼叫後端把picks轉成正式`.strate`
  格式文字。
- **下載沿用既有`downloadSubstrate()`**：後端回傳的物件跟`_substrate_summary()`
  其他地方回傳的形狀完全一樣(positions/wafer_positions/filename/text)，
  前端直接丟進既有的下載+稽核記錄函式，不用另外寫一套。

2026/10/30再補上：這支工具最早的docstring(見本文件最上面)寫的範圍其實是
「A. 資料本身已經完整(**SECS log或現成.strate**)」——但實際上線的只有
SECS log那一半，使用者手上已經是現成`.strate`檔案(例如直接從SMAP網路
磁碟機`F:/SMAP/SECS/SubstrateMap/...`抓下來的，截圖裡那個資料夾整個
都是`.strate`檔案)時，上傳進來會被當成log解析、找不到任何`StrateMap`
交易而報錯——這不是新需求，是原始設計漏掉的一半，現在補齊：`_is_strate_text()`
用檔案第一行是不是`ASSY_LOT=`(`.strate`檔案16行header的第一個固定欄位，
SECS log不可能這樣開頭)分辨這份上傳內容是log還是現成.strate，是的話
直接`StrateFile.parse()`讀成一枚基板，不用假裝它是log硬塞給
`extract_strate_files()`。`.strate`檔案本身沒有WaferStart資料，不會
貢獻wafer_map(左邊wafer圖會顯示跟平常log涵蓋範圍不夠一樣的「找不到」
訊息，這是正確行為)——想同時看到wafer圖，把對應的SECS log一起多選上傳
即可，跟「選整個資料夾」同一套多檔合併機制自然就支援混合log+.strate。
"""
from __future__ import annotations

import base64
import binascii
import csv
import io
import os
import sys
import zipfile
from dataclasses import replace
from datetime import datetime, timedelta

from flask import Flask, jsonify, render_template, request

# 2026/10/30新增：打包成桌機.exe(PyInstaller)——原本REPO_ROOT/WEBAPP_DIR
# 單純用`__file__`往上推兩層，假設這支檔案真的躺在磁碟上的`webapp/`資料夾
# 底下；但PyInstaller的`--onefile`打包模式執行時，所有東西(templates/
# static/bingomap原始碼)其實是解壓縮到一個每次啟動都重新建立的暫存資料夾
# (`sys._MEIPASS`)，不是`__file__`指向的那個位置，而且這個暫存資料夾
# 關閉程式後就會被清掉——下載紀錄CSV如果照原本邏輯寫進WEBAPP_DIR底下，
# 會寫進這個暫存資料夾，程式一關資料就不見了，完全達不到「可追溯」的
# 目的。`getattr(sys,"frozen",False)`是PyInstaller官方文件建議的「目前
# 是不是跑在打包後的exe裡」判斷方式：是的話，樣板檔案(templates/static)
# 從`sys._MEIPASS`這個唯讀的暫存解壓縮資料夾讀，但下載紀錄CSV改寫到
# `.exe`檔案本身所在的那個資料夾(使用者看得到、不會被清掉的真實位置)；
# 不是frozen(一般用`python webapp/simple_bingo_viewer.py`開發執行)時，
# 行為完全不變，維持原本「兩者都在repo的webapp/資料夾底下」。
if getattr(sys, "frozen", False):
    WEBAPP_DIR = os.path.join(sys._MEIPASS, "webapp")
    DOWNLOAD_LOG_PATH = os.path.join(os.path.dirname(sys.executable), "simple_bingo_viewer_downloads.csv")
else:
    REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    WEBAPP_DIR = os.path.join(REPO_ROOT, "webapp")
    DOWNLOAD_LOG_PATH = os.path.join(WEBAPP_DIR, "simple_bingo_viewer_downloads.csv")

app = Flask(
    __name__,
    template_folder=os.path.join(WEBAPP_DIR, "templates"),
    static_folder=os.path.join(WEBAPP_DIR, "static"),
)

from bingomap.secs_log import decode_secs_log, extract_strate_files, extract_wafer_maps  # noqa: E402
from bingomap.strate import DieInfo, StrateFile, StrateFormatError  # noqa: E402


def _is_zip(raw: bytes) -> bool:
    return raw[:2] == b"PK"


def _collect_log_bytes(raw: bytes, out: list[bytes], *, depth: int = 0) -> None:
    """Recursively unzip: a plain .log/.txt file's bytes go straight into
    `out`; a .zip's entries are each recursed into (handles both a single
    `<name>.log.zip` and a whole-folder zip that contains several nested
    `.log.zip` entries, per the user's description of how v87 reads
    these). Depth-capped at 5 — real folders are at most one level of
    nesting, this is just a guard against a maliciously/accidentally
    self-referential zip looping forever."""
    if depth > 5:
        return
    if not _is_zip(raw):
        out.append(raw)
        return
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for name in zf.namelist():
                if name.endswith("/"):
                    continue
                if not name.lower().endswith((".log", ".txt", ".zip", ".strate")):
                    continue
                _collect_log_bytes(zf.read(name), out, depth=depth + 1)
    except zipfile.BadZipFile:
        # Starts with "PK" but isn't actually a valid zip — fall back to
        # treating it as raw log bytes rather than silently dropping it;
        # decode_secs_log()/extract_strate_files() will just find nothing
        # useful and the caller gets the existing "找不到StrateMap" error.
        out.append(raw)


def _decode_uploaded_logs(data: dict) -> tuple[list[str] | None, tuple[dict, int] | None]:
    """Same base64 contract as webapp/app.py's _decode_uploaded_log() —
    duplicated here on purpose (this file is meant to stand completely on
    its own, see module docstring) rather than importing from webapp.app,
    which would pull in that module's whole dependency chain (openpyxl
    etc.) just for this one helper. Returns a LIST of decoded log texts
    (one per .log/.txt found after unzipping, could be more than one if
    a whole-folder zip was uploaded) instead of a single string — see
    2026/10/29 docstring note above for why zip support was added."""
    log_b64 = data.get("log_base64", "")
    if not log_b64:
        return None, ({"error": "請提供SECS log檔案"}, 400)
    try:
        raw = base64.b64decode(log_b64)
    except (ValueError, binascii.Error) as exc:
        return None, ({"error": f"檔案內容解碼失敗：{exc}"}, 400)

    raw_logs: list[bytes] = []
    _collect_log_bytes(raw, raw_logs)
    if not raw_logs:
        return None, ({"error": "這份zip裡沒有找到任何.log/.txt檔案"}, 400)
    return [decode_secs_log(b) for b in raw_logs], None


def _substrate_positions(sf: StrateFile) -> list[dict]:
    """Every substrate (BINGO MAP) position this die-attach run actually
    used, across DIE_INFO and DIE_INFO_OTHER_LAYER — `sub_pos` is already
    the substrate's own col:row placement (see strate.py's module
    docstring), no transform needed. Dies sharing the same position
    (stacked layers) collapse into one cell — this viewer only answers
    "is there a die here", not which layer, per the user's "simpler"
    request."""
    positions: dict[tuple[int, int], str] = {}
    for d in sf.die_info + sf.other_layer_die_info:
        col_str, _, row_str = d.sub_pos.partition(":")
        try:
            col, row = int(col_str), int(row_str)
        except ValueError:
            continue
        positions[(col, row)] = d.bin
    return [{"col": c, "row": r, "bin": b} for (c, r), b in positions.items()]


def _wafer_positions(sf: StrateFile) -> list[dict]:
    """This substrate's die positions in terms of the SOURCE WAFER's own
    col:row (`wafer_xy`, not `sub_pos`) — used to highlight, on the left-
    pane wafer grid, which of that wafer's cells this one substrate
    actually drew from. Same col:row convention as the WaferStart wafer
    map below (see bingomap/secs_log.py's module docstring — no swap
    needed, this project's real DB machine)."""
    positions: dict[tuple[int, int], str] = {}
    for d in sf.die_info + sf.other_layer_die_info:
        col_str, _, row_str = d.wafer_xy.partition(":")
        try:
            col, row = int(col_str), int(row_str)
        except ValueError:
            continue
        positions[(col, row)] = d.bin
    return [{"col": c, "row": r, "bin": b} for (c, r), b in positions.items()]


def _wafer_map_summary(wm, index: int) -> dict:
    cells = wm.wafer_map.cells
    return {
        "index": index,
        "frame_id": wm.frame_id,
        "wafer_id": wm.wafer_id,
        "columns": wm.wafer_map.columns,
        "rows": wm.wafer_map.rows,
        "cells": [{"col": x, "row": y, "bin": bin_} for (x, y), bin_ in cells.items()],
    }


def _substrate_summary(sf: StrateFile, index: int) -> dict:
    last_ts = max((d.timestamp for d in sf.die_info), default="")
    wafer_ring = sf.die_info[0].wafer_ring if sf.die_info else ""
    base_name = sf.substrate_id or f"substrate_{index + 1}"
    positions = _substrate_positions(sf)
    # Grid bounds: the header's declared ROW/COLUMN is the normal case, but
    # real data occasionally has a position outside that (e.g. a log from a
    # machine using 1-based indexing) — union with the actual data range so
    # nothing silently gets clipped off the drawn grid.
    data_max_col = max((p["col"] for p in positions), default=-1)
    data_max_row = max((p["row"] for p in positions), default=-1)
    data_min_col = min((p["col"] for p in positions), default=0)
    data_min_row = min((p["row"] for p in positions), default=0)
    return {
        "index": index,
        "substrate_id": sf.substrate_id,
        "wafer_ring": wafer_ring,
        "eqpid": sf.eqpid,
        "num_dies": len(sf.die_info),
        "num_other_layer_dies": len(sf.other_layer_die_info),
        "total_bond_die_qty": sf.total_bond_die_qty,
        "good_die": sf.good_die,
        "min_col": min(0, data_min_col),
        "max_col": max(sf.substrate_column - 1, data_max_col),
        "min_row": min(0, data_min_row),
        "max_row": max(sf.substrate_row - 1, data_max_row),
        "positions": positions,
        "wafer_positions": _wafer_positions(sf),
        "filename": f"{base_name}_{last_ts}.strate" if last_ts else f"{base_name}.strate",
        "text": sf.to_text(),
    }


DOWNLOAD_LOG_HEADER = ["時間", "工號", "流水號", "檔名", "Wafer Ring", "EQPID", "方向"]


def _append_download_log(row: dict) -> None:
    """Append one line to the local download-audit CSV — see this
    module's 2026/10/29 docstring section for why a flat CSV (not a
    database) and why this never blocks the actual download. utf-8-sig
    (BOM) so Excel on Windows (this tool's only real audience) opens the
    file with correct 中文 encoding instead of guessing wrong and showing
    mojibake — a plain utf-8 CSV is the classic "opens as garbled text in
    Excel" trap on Windows."""
    is_new = not os.path.exists(DOWNLOAD_LOG_PATH)
    with open(DOWNLOAD_LOG_PATH, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(DOWNLOAD_LOG_HEADER)
        writer.writerow(
            [
                row["time"],
                row["employee_id"],
                row["substrate_id"],
                row["filename"],
                row["wafer_ring"],
                row["eqpid"],
                row["orientation"],
            ]
        )


@app.get("/")
def index():
    return render_template("simple_bingo_viewer.html")


@app.post("/api/simple_bingo/log_download")
def api_log_download():
    data = request.get_json(force=True)
    employee_id = (data.get("employee_id") or "").strip()
    if not employee_id:
        return jsonify({"error": "缺少工號"}), 400
    _append_download_log(
        {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "employee_id": employee_id,
            "substrate_id": data.get("substrate_id", ""),
            "filename": data.get("filename", ""),
            "wafer_ring": data.get("wafer_ring", ""),
            "eqpid": data.get("eqpid", ""),
            "orientation": "反向" if data.get("orientation") == "reverse" else "正向",
        }
    )
    return jsonify({"ok": True})


@app.post("/api/simple_bingo/build_new_substrate")
def api_build_new_substrate():
    data = request.get_json(force=True)
    template_text = data.get("template_text", "")
    substrate_id = (data.get("substrate_id") or "").strip()
    wafer_ring = data.get("wafer_ring", "")
    picks = data.get("picks", [])
    if not template_text:
        return jsonify({"error": "缺少參考基板的資料(用來帶入批號/EQPID/形狀等欄位)"}), 400
    if not substrate_id:
        return jsonify({"error": "請輸入這枚基板的流水號(SUBSTRATE_ID)"}), 400
    if not picks:
        return jsonify({"error": "還沒有從wafer圖選取任何die"}), 400
    try:
        template = StrateFile.parse(template_text)
    except StrateFormatError as exc:
        return jsonify({"error": f"參考基板資料格式錯誤：{exc}"}), 400

    # 全新基板，不是補既有基板的缺口——可填目標是「參考基板宣告的形狀
    # (SUBSTRATE_COLUMN x SUBSTRATE_ROW)裡的每一個位置」，column-major
    # 排序(跟_build_die_info_list()/blank_generator.py同一種慣例)，不是
    # 「扣掉已經有的」。
    targets = [
        f"{col}:{row}"
        for col in range(template.substrate_column)
        for row in range(template.substrate_row)
    ]
    if len(picks) > len(targets):
        return jsonify({"error": f"選了{len(picks)}顆，但這個形狀只有{len(targets)}個位置"}), 400

    now = datetime.now()
    die_info = [
        DieInfo(
            index=i + 1,
            wafer_ring=wafer_ring,
            wafer_xy=f"{pick.get('x')}:{pick.get('y')}",
            sub_pos=pos,
            bin=str(pick.get("bin", "1")),
            f6="0",
            f7="0",
            timestamp=(now + timedelta(seconds=i)).strftime("%Y%m%d%H%M%S"),
            f9="1",
        )
        for i, (pick, pos) in enumerate(zip(picks, targets))
    ]

    new_sf = replace(
        template,
        substrate_id=substrate_id,
        die_info=die_info,
        other_layer_die_info=[],
        total_bond_die_qty=len(die_info),
        good_die=len(die_info),
    )
    return jsonify({"substrate": _substrate_summary(new_sf, -1)})


def _is_strate_text(text: str) -> bool:
    """A raw `.strate` file (16 `KEY=VALUE` header lines then
    `[DIE_INFO_BEG]`, see strate.py's module docstring) vs a SECS/AFC log
    (XML `<Transaction>` blocks). 2026/10/30：使用者實際上有時候手上已經
    是現成的`.strate`檔案(例如直接從SMAP網路磁碟機抓下來的，這個工具
    最早的module docstring其實就寫過「A. 資料本身已經完整(SECS log或
    現成.strate)」——但一直只做了log那一半，現成.strate那一半從來沒有
    真的接起來)，要能直接選這種檔案上傳來看圖核對/下載，不是只能選log。
    `.strate`檔案的第一行固定是`ASSY_LOT=...`(HEADER_FIELDS的第一個
    欄位)，SECS log不可能以這個開頭，用這個當判斷依據最直接。"""
    first_line = text.lstrip("﻿").split("\n", 1)[0].strip()
    return first_line.startswith("ASSY_LOT=")


@app.post("/api/simple_bingo/extract")
def api_extract():
    data = request.get_json(force=True)
    texts, err = _decode_uploaded_logs(data)
    if err:
        return jsonify(err[0]), err[1]

    # 一次上傳可能解出好幾份log(整個資料夾壓成一個zip的情況)、也可能混著
    # 現成的.strate檔案——每份各自解析，基板/wafer清單合併成同一批，
    # index重新編號讓前端的清單/下載檔名不會互相撞號。.strate檔案本身
    # 沒有WaferStart資料，不會貢獻任何wafer_map——如果想連這枚基板的
    # 來源wafer圖都看到，要把對應的SECS log一起多選上傳(既有的多檔合併
    # 行為本來就支援)。
    strate_files: list[StrateFile] = []
    wafer_maps = []
    strate_parse_errors: list[str] = []
    for text in texts:
        if _is_strate_text(text):
            try:
                strate_files.append(StrateFile.parse(text))
            except StrateFormatError as exc:
                strate_parse_errors.append(str(exc))
            continue
        strate_files.extend(extract_strate_files(text))
        wafer_maps.extend(extract_wafer_maps(text))

    if not strate_files:
        error_msg = "解壓縮後的log裡沒有找到StrateMap(基板)資料，也不是看得懂的.strate檔案格式"
        if strate_parse_errors:
            error_msg += f"（{strate_parse_errors[0]}）"
        return jsonify({"error": error_msg}), 400

    return jsonify(
        {
            "substrates": [_substrate_summary(sf, i) for i, sf in enumerate(strate_files)],
            "wafer_maps": [_wafer_map_summary(wm, i) for i, wm in enumerate(wafer_maps)],
        }
    )


if __name__ == "__main__":
    app.run(port=5050, debug=False)
