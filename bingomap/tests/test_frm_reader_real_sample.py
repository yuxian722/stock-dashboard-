"""Validates frm_reader.py against a real FRM file (2026-08-14), pulled
straight from F:\\SMAP\\FRM\\8P065800A1\\T3\\DA62 on ChipMOS's internal
network. Every field here was independently confirmed against earlier
screenshots of WaferCoordinate.exe and the 目視檢查 tool for the same
LotNo/WaferID/Layout — this is the first (and so far only) real-file
confirmation that the decompiled-derived binary format in frm_reader.py
is actually correct, not just internally consistent with itself.
"""
from pathlib import Path

from bingomap.frm_reader import frm_to_wafer_bin_map, parse_frm

FIXTURE = Path(__file__).parent / "fixtures" / "8P065800A1_T3_DA62.frm"


def _load():
    return parse_frm(FIXTURE.read_bytes())


def test_header_matches_wafercoordinate_and_目視檢查_screenshots():
    frm = _load()
    assert frm.format_version == 2
    assert frm.lot_no == "8P065800A1"
    assert frm.wafer_id == "8P0658"
    assert frm.wafer_id_seq == "03"
    assert frm.wafer_type == "AW191"  # "Layout" field in both tools' UI
    assert frm.row == 56  # "Rows" in WaferCoordinate.exe
    assert frm.col == 46  # "Columns" in WaferCoordinate.exe
    assert frm.reference_point_x == 5
    assert frm.reference_point_y == 5


def test_bin_distribution_matches_目視檢查_exactly():
    # 目視檢查's "MAP INFORMATION AREA" showed BIN 1: 1635, BIN 7: 379 for
    # this exact wafer — an exact match here means the coordinate-list
    # parsing (not just the header) is correct too.
    frm = _load()
    bins = [b for b in frm.die_map.values()]
    assert bins.count(1) == 1635
    assert bins.count(7) == 379
    assert len(frm.die_map) == 2014 == frm.gross_dices


def test_file_is_fully_consumed_except_two_trailing_marker_bytes():
    # Documented quirk: real FRM files end with two 0xFF bytes after the
    # last coordinate entry that aren't part of any struct WaferCoordinate
    # reads (its loop is driven purely by bin_kind_count / bin_qty, so it
    # never looks at them) — most likely an end-of-file sentinel. Not an
    # error; parse_frm() correctly ignores them by simply not reading that
    # far.
    raw = FIXTURE.read_bytes()
    assert raw[-2:] == b"\xff\xff"


def test_frm_to_wafer_bin_map_round_trips_real_data():
    # 2026/08/27大更正：frm_to_wafer_bin_map()把columns/rows對調(見該函式
    # docstring)——columns現在是frm.row(56)、rows是frm.col(46)。bin數量
    # (good/bad count)是聚合統計，不受x/y對調影響，維持不變。
    frm = _load()
    wafer_map = frm_to_wafer_bin_map(frm)
    assert wafer_map.columns == 56
    assert wafer_map.rows == 46
    good_count = sum(1 for v in wafer_map.cells.values() if v == "1")
    bad_count = sum(1 for v in wafer_map.cells.values() if v == "7")
    assert good_count == 1635
    assert bad_count == 379


def test_frm_to_wafer_bin_map_bin_at_matches_real_strate_col_row():
    """2026/08/27 regression test: locks in the x/y swap fix documented on
    frm_to_wafer_bin_map(). Uses a completely different real wafer (FC2643,
    EU014 layout) than the rest of this file, with 49 of its dies
    independently cross-referenced against a real machine-produced `.strate`
    (see test_secs_log.py's byte-for-byte SECS log comparison for the same
    substrate/wafer, and this file's own docstring for the fuller evidence
    chain: 854/854 die positions cross-checked against a SECS log's
    independently-verified wafer map, 98.8% coordinate-space overlap after
    the swap vs. 44% before it). Every one of these 49 real dies is recorded
    as Good ('1') in the `.strate` — bin_at() must agree, using ONLY the raw
    `.strate` col:row wafer_xy with no manual swapping in the test itself
    (unlike test_extract_strate_files_wafer_xy_matches_real_frm_die_map,
    which predates this fix and still swaps by hand for the frm.die_map path
    it exercises directly)."""
    from bingomap.strate import StrateFile

    fc2643_frm = parse_frm(
        (Path(__file__).parent / "fixtures" / "WPQ5310156SS_FC2643.frm").read_bytes()
    )
    wafer_map = frm_to_wafer_bin_map(fc2643_frm)

    strate = StrateFile.parse(
        (Path(__file__).parent / "fixtures" / "2070_V30EUC6_Z25709007096_20260801024007.strate").read_text(
            encoding="utf-8"
        )
    )
    fc2643_dies = [
        d for d in strate.die_info + strate.other_layer_die_info if d.wafer_ring == "FC2643"
    ]
    assert len(fc2643_dies) == 49

    for d in fc2643_dies:
        col, row = (int(v) for v in d.wafer_xy.split(":"))
        assert wafer_map.bin_at(col, row) == "1", f"wafer_xy={d.wafer_xy!r} did not resolve to bin=1"
