from pathlib import Path

import pytest

from webapp.app import app

REAL_FRM_FIXTURE = (
    Path(__file__).parent.parent.parent / "bingomap" / "tests" / "fixtures" / "8P065800A1_T3_DA62.frm"
)

BASE_HEADER = dict(
    assy_lot="V27NVJH",
    mapping_lot="S7MJS",
    eqpid="BAB12",
    oper="2070",
    substrate_id="Z281226C",
    substrate_row=4,
    substrate_column=20,
    substrate_block=2,
    notch="180",
    ref="-72,340",
    convention="EPOXY",
)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_index_page_loads(client):
    res = client.get("/")
    assert res.status_code == 200
    assert b"BINGO MAP" in res.data


def test_api_blank_esec_machine_type_starts_at_last_position(client):
    res = client.post("/api/blank", json={**BASE_HEADER, "machine_type": "ESEC"})
    assert res.status_code == 200
    positions = res.get_json()["positions"]
    assert positions[0] == "19:3"  # COLUMN-1:ROW-1 for ROW=4, COLUMN=20


def test_api_blank_defaults_to_db_machine_type(client):
    res = client.post("/api/blank", json=BASE_HEADER)  # no machine_type key at all
    positions = res.get_json()["positions"]
    assert positions[0] == "0:0"


def test_api_blank_returns_positions_and_qty(client):
    res = client.post("/api/blank", json=BASE_HEADER)
    assert res.status_code == 200
    data = res.get_json()
    assert data["total_qty"] == 80
    assert len(data["positions"]) == 80
    assert data["positions"][0] == "0:0"


def test_api_blank_missing_field_returns_400(client):
    bad = {k: v for k, v in BASE_HEADER.items() if k != "substrate_row"}
    res = client.post("/api/blank", json=bad)
    assert res.status_code == 400


def test_api_generate_success_downloads_strate_file(client):
    res = client.post("/api/blank", json=BASE_HEADER)
    positions = res.get_json()["positions"]

    selections = [{"x": 23, "y": 195 + i, "bin": "1"} for i in range(80)]
    payload = {
        **BASE_HEADER,
        "wafer_ring": "A27572",
        "start_time": "2026-08-12T22:16:33",
        "interval_seconds": 2,
        "selections": selections,
    }
    res = client.post("/api/generate", json=payload)
    assert res.status_code == 200
    assert "attachment" in res.headers["Content-Disposition"]
    assert "2070_V27NVJH_Z281226C_20260812221633.strate" in res.headers["Content-Disposition"]

    text = res.get_data(as_text=True)
    assert "ASSY_LOT=V27NVJH" in text
    assert "TOTAL_BOND_DIE_QTY=80" in text
    assert text.count("\r\n") > 80
    assert positions[0] in text


def test_api_generate_quantity_mismatch_returns_dialog_wording(client):
    payload = {
        **BASE_HEADER,
        "wafer_ring": "A27572",
        "start_time": "2026-08-12T22:16:33",
        "interval_seconds": 2,
        "selections": [{"x": 1, "y": 1, "bin": "1"}],  # only 1, need 80
    }
    res = client.post("/api/generate", json=payload)
    assert res.status_code == 409
    data = res.get_json()
    assert "需要 Die 數量80" in data["error"]
    assert "已選擇數量1" in data["error"]
    assert "還需選擇79顆" in data["error"]


def test_api_generate_bad_start_time_returns_400(client):
    payload = {
        **BASE_HEADER,
        "wafer_ring": "A27572",
        "start_time": "not-a-date",
        "selections": [],
    }
    res = client.post("/api/generate", json=payload)
    assert res.status_code == 400


def _fake_frm_root(tmp_path, lot_no, barcode_id):
    # Mirrors WaferCoordinate.exe's own layout: {root}\{LotNo}\{barcode[0:2]}\{barcode[2:6]}
    d = tmp_path / lot_no / barcode_id[0:2]
    d.mkdir(parents=True)
    (d / barcode_id[2:6]).write_bytes(REAL_FRM_FIXTURE.read_bytes())
    return str(tmp_path)


def test_api_frm_loads_real_file_end_to_end(client, tmp_path):
    root = _fake_frm_root(tmp_path, "8P065800A1", "T3DA62")
    res = client.post(
        "/api/frm",
        json={"lot_no": "8P065800A1", "barcode_id": "T3DA62", "frm_path": root},
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["columns"] == 46
    assert data["rows"] == 56
    assert data["lot_no"] == "8P065800A1"
    assert data["wafer_id"] == "8P0658"
    assert data["wafer_type"] == "AW191"
    bins = [c["bin"] for c in data["cells"]]
    assert bins.count("1") == 1635
    assert bins.count("7") == 379


def test_api_frm_missing_file_returns_404_with_helpful_message(client, tmp_path):
    res = client.post(
        "/api/frm",
        json={"lot_no": "NOPE123", "barcode_id": "T3DA62", "frm_path": str(tmp_path)},
    )
    assert res.status_code == 404
    assert "找不到檔案" in res.get_json()["error"]


def test_api_frm_requires_lot_no_and_barcode(client):
    res = client.post("/api/frm", json={"lot_no": "", "barcode_id": ""})
    assert res.status_code == 400


def test_api_generate_two_layer_success(client):
    res = client.post("/api/blank", json=BASE_HEADER)
    total_qty = res.get_json()["total_qty"]  # 80 for BASE_HEADER's 4x20

    primary = [{"x": 21 - i, "y": 24, "bin": "1"} for i in range(total_qty)]
    other = [{"x": 22 - i, "y": 24, "bin": "1"} for i in range(total_qty)]
    payload = {
        **BASE_HEADER,
        "wafer_ring": "I4F247",
        "start_time": "2026-08-12T16:15:21",
        "interval_seconds": 3,
        "two_layer": True,
        "primary_selections": primary,
        "other_selections": other,
        "primary_layer": "2",
        "other_layer": "1",
    }
    res = client.post("/api/generate", json=payload)
    assert res.status_code == 200
    text = res.get_data(as_text=True)
    assert "[DIE_INFO_OTHER_LAYER_BEG]" in text
    assert "[DIE_INFO_OTHER_LAYER_END]" in text
    assert text.count(",2\r\n") == total_qty
    assert text.count(",1\r\n") == total_qty


def test_api_generate_two_layer_mismatch_reports_which_side(client):
    res = client.post("/api/blank", json=BASE_HEADER)
    total_qty = res.get_json()["total_qty"]

    payload = {
        **BASE_HEADER,
        "wafer_ring": "I4F247",
        "start_time": "2026-08-12T16:15:21",
        "two_layer": True,
        "primary_selections": [{"x": 1, "y": 1, "bin": "1"}],  # short
        "other_selections": [{"x": 2, "y": 2, "bin": "1"}] * total_qty,
    }
    res = client.post("/api/generate", json=payload)
    assert res.status_code == 409
    data = res.get_json()
    assert f"需要 Die 數量{total_qty}" in data["error"]
    assert "已選擇數量1" in data["error"]
