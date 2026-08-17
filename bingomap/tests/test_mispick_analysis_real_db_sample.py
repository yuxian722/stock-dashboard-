"""Regression test using a real DB STRATE file the user provided on
2026/08/17 to confirm mispick_analysis.py's DB coordinate transform really
is an identity mapping (no X-flip/rotation) for this project's actual
machine type — see bingomap/CLAUDE.md for the full evidence chain: a
screenshot of ChipMOS's internal "WaferCoordinate" tool with its
機型(machine type) selector explicitly set to "DB系列", whose own
picked-coordinate list (X, Y, Bin columns) matched this exact file's
`wafer_xy` column entry-for-entry, plus the matching 目視檢查 wafer bin map
screenshot and the matching EAS "Bingo Map Query" report for the same
SUBSTRATE_ID (which independently confirms Fail Qty=0, i.e. every recorded
position here is Good).
"""
from pathlib import Path

from bingomap.mispick_analysis import analyze_substrate, make_offset
from bingomap.strate import StrateFile
from bingomap.wafer_map import WaferBinMap

FIXTURE = Path(__file__).parent / "fixtures" / "2070_V32AWE6_Z26306101030_20260811072811.strate"


def _read_fixture() -> str:
    with open(FIXTURE, encoding="ascii", newline="") as f:
        return f.read()


def test_real_db_header_fields():
    strate = StrateFile.parse(_read_fixture())
    assert strate.assy_lot == "V32AWE6"
    assert strate.mapping_lot == "8P964000A1"
    assert strate.eqpid == "BAA04"
    assert strate.oper == "2070"
    assert strate.substrate_id == "Z26306101030"
    assert strate.substrate_row == 11
    assert strate.substrate_column == 28
    assert strate.substrate_block == 1
    assert strate.total_bond_die_qty == 308
    assert strate.good_die == 308
    assert strate.notch == "180"
    assert strate.ref == "-27,55"
    assert len(strate.die_info) == 308


def test_real_db_wafer_xy_matches_wafercoordinate_tool_picked_list():
    # First 15 rows (all at wafer FY=30) verified against a real screenshot
    # of ChipMOS's internal "WaferCoordinate" tool's own X,Y,Bin picked-list
    # panel for this exact LotNo/BarcodeID (8P964000A1 / NBAE2D) — same
    # values, same order, no transform.
    strate = StrateFile.parse(_read_fixture())
    expected = [
        "16:30", "15:30", "14:30", "13:30", "12:30", "11:30", "10:30", "8:30",
        "7:30", "6:30", "5:30", "4:30", "3:30", "2:30", "1:30",
    ]
    actual = [d.wafer_xy for d in strate.die_info[:15]]
    assert actual == expected


def test_real_db_nominal_transform_is_identity():
    # The core claim this file exists to prove: for machine_type="DB",
    # STRATE wafer_xy IS the wafer MAP's own raw coordinate directly, with
    # no X-flip/rotation. Build a wafer map straight from this file's own
    # wafer_xy values (all Good, since GOOD_DIE == TOTAL_BOND_DIE_QTY ==
    # 308, matching the Bingo Map Query report's Fail Qty=0 for this same
    # SUBSTRATE_ID) and confirm every row's nominal lookup succeeds and is
    # Good with an *identity* nominal_map_xy.
    strate = StrateFile.parse(_read_fixture())
    wafer_map = WaferBinMap(columns=46, rows=56)
    for d in strate.die_info:
        x_str, y_str = d.wafer_xy.split(":")
        wafer_map.set_bin(int(x_str), int(y_str), "1")

    result = analyze_substrate(
        strate,
        wafer_map,
        wafer_ring="NBAE2D",
        offset=make_offset("X", 1),  # any nonzero offset — only nominal_* is under test here
        good_bins={"1"},
        ng_bins={"7", "9"},
        review_bins={"2"},
        machine_type="DB",
    )
    assert len(result.rows) == 308
    for row, die in zip(result.rows, strate.die_info):
        fx, fy = (int(v) for v in die.wafer_xy.split(":"))
        assert row.nominal_map_xy == (fx, fy)  # identity, no X-flip
        assert row.nominal_bin == "1"
