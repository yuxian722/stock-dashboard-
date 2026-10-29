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
"""
from __future__ import annotations

import base64
import binascii
import io
import os
import zipfile

from flask import Flask, jsonify, render_template, request

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBAPP_DIR = os.path.join(REPO_ROOT, "webapp")

app = Flask(
    __name__,
    template_folder=os.path.join(WEBAPP_DIR, "templates"),
    static_folder=os.path.join(WEBAPP_DIR, "static"),
)

from bingomap.secs_log import decode_secs_log, extract_strate_files, extract_wafer_maps  # noqa: E402
from bingomap.strate import StrateFile  # noqa: E402


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
                if not (name.lower().endswith(".log") or name.lower().endswith(".txt") or name.lower().endswith(".zip")):
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


@app.get("/")
def index():
    return render_template("simple_bingo_viewer.html")


@app.post("/api/simple_bingo/extract")
def api_extract():
    data = request.get_json(force=True)
    texts, err = _decode_uploaded_logs(data)
    if err:
        return jsonify(err[0]), err[1]

    # 一次上傳可能解出好幾份log(整個資料夾壓成一個zip的情況)——每份各自
    # 解析，基板/wafer清單合併成同一批，index重新編號讓前端的清單/下載
    # 檔名不會互相撞號。
    strate_files: list[StrateFile] = []
    wafer_maps = []
    for text in texts:
        strate_files.extend(extract_strate_files(text))
        wafer_maps.extend(extract_wafer_maps(text))

    if not strate_files:
        return jsonify({"error": "解壓縮後的log裡沒有找到StrateMap(基板)資料"}), 400

    return jsonify(
        {
            "substrates": [_substrate_summary(sf, i) for i, sf in enumerate(strate_files)],
            "wafer_maps": [_wafer_map_summary(wm, i) for i, wm in enumerate(wafer_maps)],
        }
    )


if __name__ == "__main__":
    app.run(port=5050, debug=False)
