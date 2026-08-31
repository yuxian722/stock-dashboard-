import pytest

from bingomap.strate import DieInfo, StrateFile
from webapp.app import app


def _ascii(text: str, length: int) -> bytes:
    data = text.encode("ascii")
    assert len(data) <= length
    return data + b"\x00" * (length - len(data))


def _u16(value: int) -> bytes:
    return bytes([(value >> 8) & 0xFF, value & 0xFF])


def _build_format_i(*, row, col, lot_no, wafer_id, bins):
    header = bytes([0])
    header += bytes([row, col])
    header += _u16(999)
    header += _ascii(lot_no, 20)
    header += _ascii(wafer_id, 8)
    header += _ascii("01", 2)
    header += b"\x00\x00"
    header += _ascii("TESTTYPE", 12)
    header += bytes([0, 0])
    header += b"\x00\x00"
    header += _u16(len(bins))
    body = b""
    for bin_kind, coords in bins:
        body += _u16(ord(str(bin_kind)))
        body += _u16(len(coords))
        for x, y in coords:
            body += bytes([x, y])
    return header + body


def _wafer_map_frm_bytes():
    # Same 5x5 layout as bingomap/tests/test_mispick_analysis.py's
    # synthetic wafer map: all Good("1") except (2,2)=NG("7"), (3,3)=Review("2").
    good = [(x, y) for x in range(5) for y in range(5) if (x, y) not in [(2, 2), (3, 3)]]
    bins = [("1", good), ("7", [(2, 2)]), ("2", [(3, 3)])]
    return _build_format_i(row=5, col=5, lot_no="LOT001", wafer_id="TESTWFR", bins=bins)


WAFER_RING = "TESTWAFER"


def _die(index, sub_pos, wafer_xy, wafer_ring=WAFER_RING):
    return DieInfo(index=index, wafer_ring=wafer_ring, wafer_xy=wafer_xy, sub_pos=sub_pos, bin="1")


def _strate_text(die_info, notch="270"):
    strate = StrateFile(
        assy_lot="V27NVJH", mapping_lot="S7MJS", eqpid="BAB12", oper="2070",
        substrate_id="Z281226C", substrate_row=3, substrate_column=3, substrate_block=1,
        notch=notch, die_info=die_info,
    )
    return strate.to_text()


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def frm_root(tmp_path):
    d = tmp_path / "8P065800A1" / "T3"
    d.mkdir(parents=True)
    (d / "DA62").write_bytes(_wafer_map_frm_bytes())
    return str(tmp_path)


def test_mispick_page_loads(client):
    res = client.get("/mispick")
    assert res.status_code == 200
    assert "誤吸".encode() in res.data


def test_analyze_esec_classifies_force_delete_review_and_ok(client, frm_root):
    # machine_type="ESEC" — the reference-tool math, not this project's
    # real machine type. See test_analyze_db_* below for the default.
    dies = [
        _die(1, "0:0", "1:1"),  # -> OK (see test_mispick_analysis.py derivation)
        _die(2, "1:0", "2:3"),  # -> FORCE_DELETE
        _die(3, "2:0", "1:4"),  # -> REVIEW
    ]
    payload = {
        "wafer_ring": WAFER_RING,
        "offset_axis": "X",
        "offset_value": 1,
        "good_bins": "1",
        "ng_bins": "7,9",
        "review_bins": "2",
        "machine_type": "ESEC",
        "frm": {"lot_no": "8P065800A1", "barcode_id": "T3DA62", "frm_path": frm_root},
        "strate_files": [{"name": "test.strate", "text": _strate_text(dies)}],
    }
    res = client.post("/api/mispick/analyze", json=payload)
    assert res.status_code == 200
    data = res.get_json()
    assert data["wafer"]["columns"] == 5
    assert data["wafer"]["rows"] == 5
    assert len(data["substrates"]) == 1
    sub = data["substrates"][0]
    assert sub["error"] is None
    assert sub["summary"] == {"force_delete": 1, "review": 1, "anomaly": 0, "ok": 1, "other": 0}
    assert len(sub["action_rows"]) == 2
    assert sub["action_rows"][0]["decision"] == "REVIEW_ACTUAL_BIN_REVIEW"
    assert sub["action_rows"][1]["decision"] == "FORCE_DELETE_ACTUAL_BIN_NG"
    assert "FORCE_DELETE_ACTUAL_BIN_NG" in data["csv"]


def test_analyze_esec_rejects_notch_other_than_270_per_substrate(client, frm_root):
    payload = {
        "wafer_ring": WAFER_RING,
        "offset_axis": "X",
        "offset_value": 1,
        "machine_type": "ESEC",
        "frm": {"lot_no": "8P065800A1", "barcode_id": "T3DA62", "frm_path": frm_root},
        "strate_files": [{"name": "bad_notch.strate", "text": _strate_text([_die(1, "0:0", "1:1")], notch="180")}],
    }
    res = client.post("/api/mispick/analyze", json=payload)
    assert res.status_code == 200
    sub = res.get_json()["substrates"][0]
    assert sub["error"] is not None
    assert "NOTCH" in sub["error"]


def test_analyze_db_is_default_and_classifies_correctly(client, frm_root):
    # DB (default, no machine_type field at all): wafer_xy is the raw
    # wafer MAP coordinate directly (identity), no X-flip/rotation. Same
    # hand-derivation as bingomap/tests/test_mispick_analysis.py's DB
    # section, adapted to this endpoint's 3x3 substrate.
    dies = [
        _die(1, "0:0", "0:0"),  # -> OK
        _die(2, "1:0", "1:2"),  # -> FORCE_DELETE (nominal (1,2)=Good, +X1 -> (2,2)="7")
        _die(3, "2:0", "2:3"),  # -> REVIEW (nominal (2,3)=Good, +X1 -> (3,3)="2")
    ]
    payload = {
        "wafer_ring": WAFER_RING,
        "offset_axis": "X",
        "offset_value": 1,
        "good_bins": "1",
        "ng_bins": "7,9",
        "review_bins": "2",
        "frm": {"lot_no": "8P065800A1", "barcode_id": "T3DA62", "frm_path": frm_root},
        "strate_files": [{"name": "test.strate", "text": _strate_text(dies, notch="180")}],
    }
    res = client.post("/api/mispick/analyze", json=payload)
    assert res.status_code == 200
    sub = res.get_json()["substrates"][0]
    assert sub["error"] is None
    assert sub["summary"] == {"force_delete": 1, "review": 1, "anomaly": 0, "ok": 1, "other": 0}


def test_analyze_returns_wafer_cells_and_substrate_grid_cells(client, frm_root):
    # Same scenario as test_analyze_db_is_default_and_classifies_correctly
    # — checks the visual-grid data added 2026/08/18 so the mispick page
    # can draw the actual wafer MAP and outline each substrate's own
    # force-delete/review positions directly on its BINGO MAP, instead of
    # only listing them in a table.
    dies = [
        _die(1, "0:0", "0:0"),  # -> OK
        _die(2, "1:0", "1:2"),  # -> FORCE_DELETE
        _die(3, "2:0", "2:3"),  # -> REVIEW
    ]
    payload = {
        "wafer_ring": WAFER_RING,
        "offset_axis": "X",
        "offset_value": 1,
        "frm": {"lot_no": "8P065800A1", "barcode_id": "T3DA62", "frm_path": frm_root},
        "strate_files": [{"name": "test.strate", "text": _strate_text(dies, notch="180")}],
    }
    res = client.post("/api/mispick/analyze", json=payload)
    assert res.status_code == 200
    data = res.get_json()

    wafer = data["wafer"]
    assert wafer["columns"] == 5
    assert wafer["rows"] == 5
    assert len(wafer["cells"]) == 25  # full 5x5 synthetic wafer map
    assert {"x": 2, "y": 2, "bin": "7"} in wafer["cells"]

    sub = data["substrates"][0]
    assert sub["substrate_column"] == 3
    assert sub["substrate_row"] == 3
    assert len(sub["grid_cells"]) == 3  # one per placed die, regardless of decision
    by_pos = {(c["tx"], c["ty"]): c["decision"] for c in sub["grid_cells"]}
    assert by_pos[(0, 0)] == "OK_ACTUAL_GOOD_BIN"
    assert by_pos[(1, 0)] == "FORCE_DELETE_ACTUAL_BIN_NG"
    assert by_pos[(2, 0)] == "REVIEW_ACTUAL_BIN_REVIEW"


def test_analyze_db_accepts_any_notch(client, frm_root):
    payload = {
        "wafer_ring": WAFER_RING,
        "offset_axis": "X",
        "offset_value": 1,
        "frm": {"lot_no": "8P065800A1", "barcode_id": "T3DA62", "frm_path": frm_root},
        "strate_files": [{"name": "x.strate", "text": _strate_text([_die(1, "0:0", "0:0")], notch="180")}],
    }
    res = client.post("/api/mispick/analyze", json=payload)
    assert res.status_code == 200
    sub = res.get_json()["substrates"][0]
    assert sub["error"] is None


def test_analyze_reports_actual_wafer_rings_when_all_dies_excluded(client, frm_root):
    # 2026/08/27新增：使用者回報一份STRATE分析結果全部被排除(非目標
    # Wafer)、BINGO MAP整片空白，看不出來是自己Wafer ID打錯還是這份
    # STRATE真的是另一片wafer——排除清單本身要能告訴使用者「這份STRATE
    # 裡實際記錄的wafer_ring是什麼」，不用自己開檔案找。
    dies = [_die(1, "0:0", "0:0", wafer_ring="OTHERWAFER")]
    payload = {
        "wafer_ring": WAFER_RING,  # 跟die自己記錄的"OTHERWAFER"不一樣
        "offset_axis": "X",
        "offset_value": 0,
        "frm": {"lot_no": "8P065800A1", "barcode_id": "T3DA62", "frm_path": frm_root},
        "strate_files": [{"name": "x.strate", "text": _strate_text(dies)}],
    }
    res = client.post("/api/mispick/analyze", json=payload)
    assert res.status_code == 200
    sub = res.get_json()["substrates"][0]
    assert sub["excluded_count"] == 1
    assert sub["excluded_wafer_rings"] == ["OTHERWAFER"]
    assert sub["summary"] == {"force_delete": 0, "review": 0, "anomaly": 0, "ok": 0, "other": 0}
    # 2026/08/31新增：使用者回報「0:0,0:1明明有die，BINGO MAP卻顯示空白」
    # ——排除的die也要能在BINGO MAP畫出來(用不同樣式)，不能讓它們完全
    # 從grid_cells/excluded_grid_cells裡消失，變得跟真正沒上片的位置
    # 分不出來。
    assert sub["grid_cells"] == []
    assert sub["excluded_grid_cells"] == [{"tx": 0, "ty": 0, "wafer_ring": "OTHERWAFER"}]


def test_analyze_requires_wafer_ring(client):
    res = client.post("/api/mispick/analyze", json={})
    assert res.status_code == 400


def test_analyze_missing_frm_file_returns_404(client, tmp_path):
    payload = {
        "wafer_ring": WAFER_RING,
        "offset_axis": "X",
        "offset_value": 1,
        "frm": {"lot_no": "NOPE", "barcode_id": "T3DA62", "frm_path": str(tmp_path)},
        "strate_files": [{"name": "x.strate", "text": _strate_text([_die(1, "0:0", "1:1")])}],
    }
    res = client.post("/api/mispick/analyze", json=payload)
    assert res.status_code == 404


def test_analyze_accepts_zero_offset_as_identity(client, frm_root):
    # 2026/08/27更正：0代表T點沒有偏移的基準狀態，不再被拒絕(見
    # bingomap/mispick_analysis.py的make_offset()) —— nominal座標等於
    # 實際座標，wafer_xy=1:1在5x5合成wafer map上是Good("1")，應該分類成OK。
    payload = {
        "wafer_ring": WAFER_RING,
        "offset_axis": "X",
        "offset_value": 0,
        "frm": {"lot_no": "8P065800A1", "barcode_id": "T3DA62", "frm_path": frm_root},
        "strate_files": [{"name": "x.strate", "text": _strate_text([_die(1, "0:0", "1:1")])}],
    }
    res = client.post("/api/mispick/analyze", json=payload)
    assert res.status_code == 200
    sub = res.get_json()["substrates"][0]
    assert sub["error"] is None
    assert sub["summary"] == {"force_delete": 0, "review": 0, "anomaly": 0, "ok": 1, "other": 0}
