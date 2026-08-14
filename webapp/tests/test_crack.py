import pytest

from bingomap.strate import DieInfo, StrateFile
from webapp.app import app

WAFER_RING = "TESTWAFER"


def _die(index, sub_pos, wafer_xy, wafer_ring=WAFER_RING):
    return DieInfo(index=index, wafer_ring=wafer_ring, wafer_xy=wafer_xy, sub_pos=sub_pos, bin="1")


def _strate_text(die_info, notch="270", substrate_id="Z281226C"):
    strate = StrateFile(
        assy_lot="V27NVJH", mapping_lot="S7MJS", eqpid="BAB12", oper="2070",
        substrate_id=substrate_id, substrate_row=3, substrate_column=3, substrate_block=1,
        notch=notch, die_info=die_info,
    )
    return strate.to_text()


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_crack_page_loads(client):
    res = client.get("/crack")
    assert res.status_code == 200
    assert "Crack".encode() in res.data


def test_analyze_builds_docs_and_scatter(client):
    dies = [_die(1, "0:0", "3:7"), _die(2, "1:0", "1:5")]
    payload = {
        "strate_files": [{"name": "a.strate", "text": _strate_text(dies)}],
        "marked_keys": [],
    }
    res = client.post("/api/crack/analyze", json=payload)
    assert res.status_code == 200
    data = res.get_json()
    assert len(data["docs"]) == 1
    assert len(data["docs"][0]["cells"]) == 2
    assert data["wafer_ids"] == [WAFER_RING]
    assert data["focus_wafer_id"] == WAFER_RING
    assert data["scatter"]["notch"] == 270
    assert len(data["scatter"]["points"]) == 2
    assert data["crack_table"] == []
    assert "crack_no" in data["csv"]


def test_analyze_marks_crack_and_reports_in_table_and_csv(client):
    dies = [_die(1, "0:0", "3:7"), _die(2, "1:0", "1:5")]
    key = None
    # First call with no marks to discover the candidate key.
    res0 = client.post(
        "/api/crack/analyze",
        json={"strate_files": [{"name": "a.strate", "text": _strate_text(dies)}], "marked_keys": []},
    )
    key = res0.get_json()["docs"][0]["cells"][0]["key"]

    res = client.post(
        "/api/crack/analyze",
        json={
            "strate_files": [{"name": "a.strate", "text": _strate_text(dies)}],
            "marked_keys": [key],
        },
    )
    assert res.status_code == 200
    data = res.get_json()
    assert len(data["crack_table"]) == 1
    assert data["crack_table"][0]["crack_no"] == 1
    assert data["crack_table"][0]["key"] == key
    marked_points = [p for p in data["scatter"]["points"] if p["is_crack"]]
    assert len(marked_points) == 1
    assert "C1" in data["csv"]


def test_analyze_pools_multiple_docs_sharing_wafer_id(client):
    doc_a = _strate_text([_die(1, "0:0", "1:5")], substrate_id="Z1")
    doc_b = _strate_text([_die(1, "0:0", "3:7")], substrate_id="Z2")
    payload = {
        "strate_files": [{"name": "a.strate", "text": doc_a}, {"name": "b.strate", "text": doc_b}],
        "marked_keys": [],
    }
    res = client.post("/api/crack/analyze", json=payload)
    assert res.status_code == 200
    data = res.get_json()
    assert len(data["docs"]) == 2
    assert len(data["scatter"]["points"]) == 2  # both docs' points pooled into one wafer's scatter


def test_analyze_requires_strate_files(client):
    res = client.post("/api/crack/analyze", json={})
    assert res.status_code == 400


def test_analyze_rejects_missing_notch(client):
    payload = {
        "strate_files": [{"name": "a.strate", "text": _strate_text([_die(1, "0:0", "1:1")], notch="")}],
        "marked_keys": [],
    }
    res = client.post("/api/crack/analyze", json=payload)
    assert res.status_code == 422
    assert "NOTCH" in res.get_json()["error"]


def test_analyze_accepts_notch_other_than_270_unlike_mispick(client):
    payload = {
        "strate_files": [{"name": "a.strate", "text": _strate_text([_die(1, "0:0", "1:1")], notch="90")}],
        "marked_keys": [],
    }
    res = client.post("/api/crack/analyze", json=payload)
    assert res.status_code == 200


def test_analyze_rejects_bad_strate_text(client):
    payload = {"strate_files": [{"name": "bad.strate", "text": "not a strate file"}], "marked_keys": []}
    res = client.post("/api/crack/analyze", json=payload)
    assert res.status_code == 422
