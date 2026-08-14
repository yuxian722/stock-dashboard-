import pytest

from bingomap.wafer_map import WaferBinMap, build_picks_from_scan, scan_rectangle


def _sample_map() -> WaferBinMap:
    # A small 3x3 patch: good (bin 1), bad (bin 7), and empty (outside wafer) cells mixed.
    wafer_map = WaferBinMap(columns=10, rows=10)
    wafer_map.set_bin(5, 5, "1")
    wafer_map.set_bin(5, 6, "7")  # bad, should be skipped
    wafer_map.set_bin(5, 7, "1")
    wafer_map.set_bin(6, 5, "1")
    wafer_map.set_bin(6, 6, "1")
    # (6, 7) left unset entirely -> outside wafer circle, should be skipped
    return wafer_map


def test_scan_rectangle_skips_bad_bin_and_empty_cells():
    wafer_map = _sample_map()
    picked = scan_rectangle(wafer_map, range(5, 7), range(5, 8))
    assert picked == [(5, 5), (5, 7), (6, 5), (6, 6)]


def test_scan_rectangle_respects_custom_good_bin():
    wafer_map = _sample_map()
    picked = scan_rectangle(wafer_map, range(5, 7), range(5, 8), good_bin="7")
    assert picked == [(5, 6)]


def test_scan_rectangle_empty_when_nothing_matches():
    wafer_map = WaferBinMap(columns=10, rows=10)
    assert scan_rectangle(wafer_map, range(0, 3), range(0, 3)) == []


def test_build_picks_from_scan_zips_in_order():
    scanned = [(5, 5), (5, 7), (6, 5)]
    sub_positions = ["0:0", "0:1", "0:2"]
    picks = build_picks_from_scan(scanned, sub_positions, wafer_ring="A27572")

    assert [p.sub_pos for p in picks] == sub_positions
    assert [p.wafer_xy for p in picks] == ["5:5", "5:7", "6:5"]
    assert all(p.wafer_ring == "A27572" for p in picks)
    assert all(p.bin == "1" for p in picks)


def test_build_picks_from_scan_rejects_count_mismatch():
    with pytest.raises(ValueError, match="counts must match"):
        build_picks_from_scan([(1, 1), (2, 2)], ["0:0"], wafer_ring="A27572")


def test_die_pick_from_xy_formats_wafer_xy():
    from bingomap.assignment import DiePick

    pick = DiePick.from_xy("0:0", "A27572", 23, 195)
    assert pick.wafer_xy == "23:195"
    assert pick.sub_pos == "0:0"
    assert pick.wafer_ring == "A27572"
    assert pick.bin == "1"
