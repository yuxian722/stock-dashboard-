"""2026/10/28: simplified standalone viewer ("執行檔點進去就開啟", upload a
SECS log and see each substrate's own BINGO MAP grid before downloading).
Locks in the extract endpoint against the same real gold-edge-down fixture
bingomap/tests/test_blank_generator_gold_edge_orientation.py already
verified — this test doesn't re-derive the real gap positions, it reuses
that module's already-confirmed REAL_GAP_POSITIONS constant so a
regression in either place shows up as a mismatch, not two independently
-guessable "expected" sets."""
import base64
import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from bingomap.tests.test_blank_generator_gold_edge_orientation import (  # noqa: E402
    REAL_GAP_POSITIONS,
)
import webapp.simple_bingo_viewer as sbv  # noqa: E402
from webapp.simple_bingo_viewer import app  # noqa: E402

FIXTURE = Path(__file__).parent.parent.parent / "bingomap" / "tests" / "fixtures" / "BAA0820260814_07_Z26306101253.log"


def test_extract_real_gold_edge_down_fixture_matches_known_gaps():
    client = app.test_client()
    log_base64 = base64.b64encode(FIXTURE.read_bytes()).decode("ascii")

    res = client.post("/api/simple_bingo/extract", json={"log_base64": log_base64})
    assert res.status_code == 200
    substrates = res.get_json()["substrates"]
    assert len(substrates) == 1

    s = substrates[0]
    assert s["substrate_id"] == "Z26306101253"
    assert s["num_dies"] == 299
    assert (s["min_col"], s["max_col"], s["min_row"], s["max_row"]) == (0, 27, 0, 10)

    present = {(p["col"], p["row"]) for p in s["positions"]}
    full_grid = {(c, r) for c in range(28) for r in range(11)}
    assert full_grid - present == REAL_GAP_POSITIONS

    # The downloaded text is this module's own StrateFile.to_text() output
    # unchanged — "正向/反向" is purely a frontend display transform (see
    # simple_bingo_viewer.py's module docstring) and must never touch it.
    assert "SUBSTRATE_ID=Z26306101253" in s["text"]
    assert s["text"].count("\r\n") > 0  # .strate files are always CRLF


def test_extract_without_log_base64_returns_400():
    client = app.test_client()
    res = client.post("/api/simple_bingo/extract", json={})
    assert res.status_code == 400
    assert "log" in res.get_json()["error"]


MULTI_SUBSTRATE_FIXTURE = (
    Path(__file__).parent.parent.parent
    / "bingomap" / "tests" / "fixtures" / "BAA0320260906_17.0_BB93AE_8L808002A1.log"
)


def test_extract_includes_wafer_maps_matched_by_wafer_ring():
    """2026/10/29改版新增：左半wafer圖需要的資料——每枚基板都要能用
    wafer_ring找到它來源那片wafer的WaferStart bin map，而且每顆die
    的wafer_xy(不是sub_pos)位置數要跟num_dies對得上，不然前端疊加
    標示會漏顆或對不到格子。"""
    client = app.test_client()
    log_base64 = base64.b64encode(MULTI_SUBSTRATE_FIXTURE.read_bytes()).decode("ascii")

    res = client.post("/api/simple_bingo/extract", json={"log_base64": log_base64})
    assert res.status_code == 200
    data = res.get_json()

    assert len(data["substrates"]) == 6
    assert len(data["wafer_maps"]) > 0
    wafer_rings = {wm["frame_id"] for wm in data["wafer_maps"]}

    for s in data["substrates"]:
        assert s["wafer_ring"] in wafer_rings
        assert len(s["wafer_positions"]) == s["num_dies"]


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


def test_extract_accepts_a_zipped_log_directly():
    """2026/10/29：使用者真實的log資料夾裡，每個檔案本來就是`.log.zip`
    (壓縮過的)，不是解壓縮好的純文字——直接把zip的位元組丟給舊版的
    decode_secs_log()會解出亂碼，extract_strate_files()自然找不到任何
    StrateMap，使用者看到的錯誤訊息（「這份log裡沒有找到StrateMap資料」）
    因此是誤導的。這裡用真實的gold-edge-down fixture現場包成zip，鎖定
    「上傳.zip跟直接上傳解壓縮後的.log，結果要一模一樣」這件事。"""
    client = app.test_client()
    zipped = _zip_bytes({"BAB0820261002_18.0.log": FIXTURE.read_bytes()})
    log_base64 = base64.b64encode(zipped).decode("ascii")

    res = client.post("/api/simple_bingo/extract", json={"log_base64": log_base64})
    assert res.status_code == 200
    substrates = res.get_json()["substrates"]
    assert len(substrates) == 1
    assert substrates[0]["substrate_id"] == "Z26306101253"
    assert substrates[0]["num_dies"] == 299


def test_extract_accepts_a_folder_zip_containing_nested_log_zips():
    """同一批資料夾壓成一個zip、裡面每份log又各自是一個.log.zip(使用者
    提到v87支援這種巢狀結構)——兩份log合併解析，基板數量要是兩份log
    各自基板數量的總和，不能漏掉任何一份，也不能互相覆蓋掉。"""
    client = app.test_client()
    inner_zip = _zip_bytes({"BAB0820261002_18.0.log": FIXTURE.read_bytes()})
    folder_zip = _zip_bytes(
        {
            "BAB0820261002_18.0.log.zip": inner_zip,
            "BAB0820261003_03.0.log.zip": inner_zip,
        }
    )
    log_base64 = base64.b64encode(folder_zip).decode("ascii")

    res = client.post("/api/simple_bingo/extract", json={"log_base64": log_base64})
    assert res.status_code == 200
    substrates = res.get_json()["substrates"]
    assert len(substrates) == 2  # one from each nested .log.zip
    assert {s["substrate_id"] for s in substrates} == {"Z26306101253"}


def test_log_download_requires_employee_id():
    client = app.test_client()
    res = client.post("/api/simple_bingo/log_download", json={"substrate_id": "Z26306101253"})
    assert res.status_code == 400
    assert "工號" in res.get_json()["error"]


def test_log_download_appends_a_csv_row(tmp_path, monkeypatch):
    """2026/10/29新增：下載時記一筆到本機CSV(工號/時間/流水號/檔名/
    方向)——不是資料庫，用monkeypatch把寫入路徑導到tmp_path，確認不會
    動到repo裡真正的下載紀錄檔，也確認header只會在檔案第一次建立時寫
    一次(第二次呼叫不會重複插入header列)。"""
    log_path = tmp_path / "downloads.csv"
    monkeypatch.setattr(sbv, "DOWNLOAD_LOG_PATH", str(log_path))

    client = app.test_client()
    res = client.post(
        "/api/simple_bingo/log_download",
        json={
            "employee_id": "A12345",
            "substrate_id": "Z26306101253",
            "filename": "Z26306101253_20260814064920.strate",
            "wafer_ring": "T3DC94",
            "eqpid": "BAA08",
            "orientation": "reverse",
        },
    )
    assert res.status_code == 200
    assert res.get_json() == {"ok": True}

    # 再下載一次，確認header不會被插入第二次
    client.post(
        "/api/simple_bingo/log_download",
        json={"employee_id": "A12345", "substrate_id": "X", "filename": "x.strate"},
    )

    text = log_path.read_text(encoding="utf-8-sig")
    lines = [line for line in text.splitlines() if line]
    assert lines[0] == "時間,工號,流水號,檔名,Wafer Ring,EQPID,方向"
    assert lines.count("時間,工號,流水號,檔名,Wafer Ring,EQPID,方向") == 1
    assert len(lines) == 3  # header + 2 download rows
    assert "A12345" in lines[1]
    assert "Z26306101253" in lines[1]
    assert "反向" in lines[1]

def test_apply_picks_fills_blanks_in_column_major_order():
    """2026/10/29新增：手動補空白位置——使用者在wafer圖上框選/點選幾顆
    良品die後，不用自己指定填哪一格，依照這枚基板bounding box的
    column-major順序(跟bingomap/blank_generator.py同一種慣例)自動依序
    對應填入目前還空白的位置。這份真實gold-edge-down fixture的9個已知
    真實缺口(REAL_GAP_POSITIONS，跟①頁的blank_generator測試共用同一份
    已驗證資料)，column-major排序後最前面兩個是(6,1)/(6,2)，鎖定填入
    的前兩顆剛好落在這兩個位置，不是隨便哪裡。"""
    client = app.test_client()
    log_base64 = base64.b64encode(FIXTURE.read_bytes()).decode("ascii")
    extracted = client.post("/api/simple_bingo/extract", json={"log_base64": log_base64}).get_json()
    s = extracted["substrates"][0]
    assert s["num_dies"] == 299

    res = client.post(
        "/api/simple_bingo/apply_picks",
        json={
            "strate_text": s["text"],
            "wafer_ring": s["wafer_ring"],
            "index": 0,
            "picks": [{"x": 50, "y": 60, "bin": "1"}, {"x": 51, "y": 61, "bin": "1"}],
        },
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["filled_count"] == 2

    updated = data["substrate"]
    assert updated["num_dies"] == 301
    assert updated["total_bond_die_qty"] == 301
    assert updated["good_die"] == 301

    by_pos = {(p["col"], p["row"]): p for p in updated["positions"]}
    assert (6, 1) in by_pos and (6, 2) in by_pos
    # the other 7 known real gaps are still genuinely blank — only the
    # first two column-major targets got filled.
    assert (7, 1) not in by_pos

    # round-trips cleanly back through the real parser — not just "looks
    # like" valid text.
    reparsed = sbv.StrateFile.parse(updated["text"])
    assert len(reparsed.die_info) == 301
    new_rows = [d for d in reparsed.die_info if d.sub_pos in ("6:1", "6:2")]
    assert {d.wafer_xy for d in new_rows} == {"50:60", "51:61"}
    assert all(d.wafer_ring == s["wafer_ring"] for d in new_rows)
    assert all(d.bin == "1" for d in new_rows)


def test_apply_picks_rejects_more_picks_than_blank_positions():
    client = app.test_client()
    log_base64 = base64.b64encode(FIXTURE.read_bytes()).decode("ascii")
    extracted = client.post("/api/simple_bingo/extract", json={"log_base64": log_base64}).get_json()
    s = extracted["substrates"][0]

    res = client.post(
        "/api/simple_bingo/apply_picks",
        json={
            "strate_text": s["text"],
            "wafer_ring": s["wafer_ring"],
            "picks": [{"x": i, "y": i, "bin": "1"} for i in range(20)],  # only 9 real gaps
        },
    )
    assert res.status_code == 400
    assert "9" in res.get_json()["error"]


def test_apply_picks_requires_strate_text_and_picks():
    client = app.test_client()
    res = client.post("/api/simple_bingo/apply_picks", json={"picks": [{"x": 1, "y": 1}]})
    assert res.status_code == 400
    assert "基板" in res.get_json()["error"]

    res = client.post("/api/simple_bingo/apply_picks", json={"strate_text": "ASSY_LOT=\r\n"})
    assert res.status_code == 400
    assert "die" in res.get_json()["error"]
