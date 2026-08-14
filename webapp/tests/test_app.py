import pytest

from webapp.app import app

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
