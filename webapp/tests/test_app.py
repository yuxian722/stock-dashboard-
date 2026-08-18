from pathlib import Path

import pytest

from webapp.app import app

REAL_FRM_FIXTURE = (
    Path(__file__).parent.parent.parent / "bingomap" / "tests" / "fixtures" / "8P065800A1_T3_DA62.frm"
)
REAL_FRM_WITH_REF_POINT_FIXTURE = (
    Path(__file__).parent.parent.parent / "bingomap" / "tests" / "fixtures" / "8P964000_K8_4E13.frm"
)
REAL_STRATE_FIXTURE = (
    Path(__file__).parent.parent.parent
    / "bingomap"
    / "tests"
    / "fixtures"
    / "2070_V27NVJH_Z281226C_20260812221959.strate"
)
REAL_EIGHT_LAYER_STRATE_FIXTURE = (
    Path(__file__).parent.parent.parent
    / "bingomap"
    / "tests"
    / "fixtures"
    / "2070_V25NVDY_F2006908_20260702203138.strate"
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


def test_api_generate_skip_positions_reduces_required_qty(client):
    res = client.post("/api/blank", json=BASE_HEADER)
    positions = res.get_json()["positions"]
    skip_positions = positions[:2]  # mark 2 substrate sites "不上片"

    selections = [{"x": 23, "y": 195 + i, "bin": "1"} for i in range(78)]  # 80 - 2 skipped
    payload = {
        **BASE_HEADER,
        "wafer_ring": "A27572",
        "start_time": "2026-08-12T22:16:33",
        "interval_seconds": 2,
        "selections": selections,
        "skip_positions": skip_positions,
    }
    res = client.post("/api/generate", json=payload)
    assert res.status_code == 200
    text = res.get_data(as_text=True)
    assert "TOTAL_BOND_DIE_QTY=78" in text
    for pos in skip_positions:
        assert f",{pos},1,0,0," not in text  # never written as a DIE_INFO row


def test_api_generate_skip_positions_mismatch_uses_adjusted_target(client):
    res = client.post("/api/blank", json=BASE_HEADER)
    positions = res.get_json()["positions"]
    skip_positions = positions[:2]

    payload = {
        **BASE_HEADER,
        "wafer_ring": "A27572",
        "start_time": "2026-08-12T22:16:33",
        "selections": [{"x": 1, "y": 1, "bin": "1"}],  # only 1, need 78 (80-2 skipped)
        "skip_positions": skip_positions,
    }
    res = client.post("/api/generate", json=payload)
    assert res.status_code == 409
    assert "需要 Die 數量78" in res.get_json()["error"]


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


def _fake_frm_root(tmp_path, lot_no, barcode_id, fixture=REAL_FRM_FIXTURE):
    # Mirrors WaferCoordinate.exe's own layout: {root}\{LotNo}\{barcode[0:2]}\{barcode[2:6]}
    d = tmp_path / lot_no / barcode_id[0:2]
    d.mkdir(parents=True)
    (d / barcode_id[2:6]).write_bytes(fixture.read_bytes())
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


def test_api_frm_returns_reference_point_from_real_file(client, tmp_path):
    # Real file the user sent 2026/08/18 while tracking down what "T點" in
    # WaferCoordinate.exe's status bar actually is. This confirms the FRM
    # header's own reference_point_x/y field parses correctly (matches the
    # MAP INFORMATION AREA panel's bin1=1746/bin7=268) — NOT that this
    # field is T點 itself: a follow-up photo proved that guess wrong (the
    # field sits outside the wafer's actual die area, nowhere near the
    # real on-screen crosshair). See webapp/README.md and app.js's
    # refPointByPanel comment for how T點 is actually derived now.
    root = _fake_frm_root(tmp_path, "8P964000", "K84E13", fixture=REAL_FRM_WITH_REF_POINT_FIXTURE)
    res = client.post(
        "/api/frm",
        json={"lot_no": "8P964000", "barcode_id": "K84E13", "frm_path": root},
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["lot_no"] == "8P964000"
    assert data["wafer_id"] == "8P9640"
    assert data["reference_point_x"] == 5
    assert data["reference_point_y"] == 5
    bins = [c["bin"] for c in data["cells"]]
    assert bins.count("1") == 1746
    assert bins.count("7") == 268
    # The reference point itself isn't a real die.
    assert not any(c["x"] == 5 and c["y"] == 5 for c in data["cells"])


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

    # layers[-1] is the current/topmost layer -> f9=2 (DIE_INFO);
    # layers[0] -> f9=1 (DIE_INFO_OTHER_LAYER)
    other = [{"x": 21 - i, "y": 24, "bin": "1"} for i in range(total_qty)]
    primary = [{"x": 22 - i, "y": 24, "bin": "1"} for i in range(total_qty)]
    payload = {
        **BASE_HEADER,
        "wafer_ring": "I4F247",
        "start_time": "2026-08-12T16:15:21",
        "interval_seconds": 3,
        "layers": [other, primary],
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
        "layers": [
            [{"x": 2, "y": 2, "bin": "1"}] * total_qty,
            [{"x": 1, "y": 1, "bin": "1"}],  # short (this is the last/current layer)
        ],
    }
    res = client.post("/api/generate", json=payload)
    assert res.status_code == 409
    data = res.get_json()
    assert f"需要 Die 數量{total_qty}" in data["error"]
    assert "已選擇數量1" in data["error"]


def test_api_generate_eight_layer_success(client):
    header = dict(BASE_HEADER, substrate_row=1, substrate_column=7, substrate_block=1)
    res = client.post("/api/blank", json=header)
    total_qty = res.get_json()["total_qty"]
    assert total_qty == 7

    layers = [[{"x": layer * 10 + i, "y": 1, "bin": "1"} for i in range(total_qty)] for layer in range(8)]
    payload = {
        **header,
        "wafer_ring": "B6844E",
        "start_time": "2026-07-02T20:26:40",
        "layers": layers,
    }
    res = client.post("/api/generate", json=payload)
    assert res.status_code == 200
    text = res.get_data(as_text=True)
    assert "[DIE_INFO_OTHER_LAYER_BEG]" in text
    for f9 in range(1, 9):
        assert text.count(f",{f9}\r\n") == total_qty, f9


def _read_real_strate_text():
    with open(REAL_STRATE_FIXTURE, encoding="ascii", newline="") as f:
        return f.read()


def test_api_parse_strate_extracts_header_positions_and_picks(client):
    res = client.post("/api/parse_strate", json={"text": _read_real_strate_text()})
    assert res.status_code == 200
    data = res.get_json()
    assert data["assy_lot"] == "V27NVJH"
    assert data["substrate_id"] == "Z281226C"
    assert data["substrate_row"] == 4
    assert data["substrate_column"] == 20
    assert data["wafer_ring"] == "A27572"
    assert data["total_qty"] == 75
    assert len(data["positions"]) == 75
    assert data["positions"][0] == "0:0"
    assert data["positions"][-1] == "19:3"
    assert len(data["picks"]) == 75
    assert data["picks"][0] == {"x": 23, "y": 195, "bin": "1"}
    assert data["num_layers"] == 1
    assert data["layer_picks"] == [data["picks"]]


def test_api_parse_strate_splits_real_eight_layer_file_by_f9(client):
    with open(REAL_EIGHT_LAYER_STRATE_FIXTURE, encoding="ascii", newline="") as f:
        text = f.read()
    res = client.post("/api/parse_strate", json={"text": text})
    assert res.status_code == 200
    data = res.get_json()
    assert data["num_layers"] == 8
    assert len(data["layer_picks"]) == 8
    assert all(len(layer) == 7 for layer in data["layer_picks"])
    # layer_picks[-1] is the DIE_INFO (topmost/current) layer
    assert data["layer_picks"][-1] == data["picks"]
    # layer_picks[0] is f9=1's picks — first row's wafer_xy is "3:66"
    assert data["layer_picks"][0][0] == {"x": 3, "y": 66, "bin": "1"}


def test_api_parse_strate_rejects_malformed_text(client):
    res = client.post("/api/parse_strate", json={"text": "not a strate file"})
    assert res.status_code == 422


def test_api_parse_strate_rejects_empty_text(client):
    res = client.post("/api/parse_strate", json={"text": ""})
    assert res.status_code == 400


def test_api_generate_with_template_positions_bypasses_machine_type(client):
    parsed = client.post("/api/parse_strate", json={"text": _read_real_strate_text()}).get_json()
    payload = {
        "assy_lot": parsed["assy_lot"],
        "mapping_lot": parsed["mapping_lot"],
        "eqpid": parsed["eqpid"],
        "oper": parsed["oper"],
        "substrate_id": "Z999999Z",  # deliberately changed, as a real re-use would
        "substrate_row": parsed["substrate_row"],
        "substrate_column": parsed["substrate_column"],
        "substrate_block": parsed["substrate_block"],
        "notch": parsed["notch"],
        "ref": parsed["ref"],
        # No convention/machine_type at all — template_positions must win
        # regardless, proving this path never touches generate_blank().
        "wafer_ring": parsed["wafer_ring"],
        "start_time": "2026-08-14T09:00:00",
        "interval_seconds": 2,
        "template_positions": parsed["positions"],
        "selections": parsed["picks"],
    }
    res = client.post("/api/generate", json=payload)
    assert res.status_code == 200
    text = res.get_data(as_text=True)
    assert "SUBSTRATE_ID=Z999999Z" in text
    assert "TOTAL_BOND_DIE_QTY=75" in text
    # exact same position order as the original real file, not a
    # DB/ESEC-regenerated one
    assert "0:0" in text
    assert "19:3" in text
