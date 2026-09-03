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
    # 2026/09/03撤銷了2026/08/27的columns/rows對調(見frm_to_wafer_bin_map()
    # docstring的完整說明)——columns改回frm.col(46)、rows改回frm.row(56)。
    # bin數量(good/bad count)是聚合統計，不受x/y對調影響，維持不變。
    frm = _load()
    wafer_map = frm_to_wafer_bin_map(frm)
    assert wafer_map.columns == 46
    assert wafer_map.rows == 56
    good_count = sum(1 for v in wafer_map.cells.values() if v == "1")
    bad_count = sum(1 for v in wafer_map.cells.values() if v == "7")
    assert good_count == 1635
    assert bad_count == 379


def test_frm_to_wafer_bin_map_bin_at_matches_real_db_strate_xy():
    """2026/09/03 regression test replacing the 2026/08/27 one of the same
    shape: that earlier version used a completely different wafer (FC2643,
    EU014 layout, EQPID=BAB14, NOTCH=270 — an ESEC-orientation sample, see
    REQUIRED_NOTCH_ESEC in mispick_analysis.py) to lock in an x/y swap that
    turned out to only be valid for that ESEC-orientation case, not for this
    project's actual DB machine type (see frm_to_wafer_bin_map()'s current
    docstring for the full story of why that swap got reverted).

    This version instead uses a real DB substrate (EQPID=BAA08, wafer
    T3DC94, NOTCH=180) the user reported wafer_xy="23:48" — die #1 — was
    completely missing from the wafer preview under the (now-reverted)
    swapped code. T3DC94 itself has no committed `.frm` file, so this uses
    a same-lot/same-Layout(AW191) real wafer (T3DA62, this file's own
    FIXTURE) as a stand-in — same physical die-grid shape, so every real
    picked position must land on SOME valid die, even though the specific
    bin colors differ per physical wafer. Without the swap all 299/299 real
    die positions (including "23:48") land in range; with the (reverted)
    swap only 155/299 did."""
    from bingomap.strate import StrateFile

    frm = _load()
    wafer_map = frm_to_wafer_bin_map(frm)

    strate = StrateFile.parse(
        (
            Path(__file__).parent
            / "fixtures"
            / "2130_V32AWCW_Z26306101253_20260814064943.strate"
        ).read_text(encoding="utf-8")
    )
    assert len(strate.die_info) == 299
    assert strate.die_info[0].wafer_xy == "23:48"

    for d in strate.die_info:
        x, y = (int(v) for v in d.wafer_xy.split(":"))
        assert wafer_map.bin_at(x, y) is not None, (
            f"wafer_xy={d.wafer_xy!r} landed outside the AW191 wafer's real die positions"
        )
