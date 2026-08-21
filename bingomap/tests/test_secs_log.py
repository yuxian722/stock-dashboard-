"""Tests against a real (trimmed) SECS/AFC transaction log the user
provided 2026/08/18 — see bingomap/secs_log.py's module docstring for how
the row/column orientation of WaferStart's BinList was cross-validated
against a real StrateMap's DIE_INFO before writing any of this."""
from pathlib import Path

from bingomap.secs_log import (
    decode_secs_log,
    extract_strate_files,
    extract_wafer_maps,
    iter_transactions,
)

FIXTURE = Path(__file__).parent / "fixtures" / "secs_log_sample.log"


def _load_text() -> str:
    return decode_secs_log(FIXTURE.read_bytes())


def test_decode_secs_log_detects_utf16le_with_no_bom():
    text = _load_text()
    assert text.startswith("INFO")
    assert "\x00" not in text


def test_decode_secs_log_falls_back_to_utf8():
    text = decode_secs_log("INFO plain utf-8 log, no BOM".encode("utf-8"))
    assert text == "INFO plain utf-8 log, no BOM"


def test_decode_secs_log_handles_utf16_bom():
    payload = "INFO with a BOM".encode("utf-16")  # adds a BOM automatically
    assert decode_secs_log(payload) == "INFO with a BOM"


def test_iter_transactions_finds_all_known_types_in_fixture():
    text = _load_text()
    names = [name for name, _, _ in iter_transactions(text)]
    assert names.count("PickDie") == 2
    assert names.count("StrateMap") == 2
    assert names.count("WaferUpload") == 1
    assert names.count("WaferStart") == 1


def test_extract_strate_files_matches_real_substrate():
    text = _load_text()
    files = extract_strate_files(text)
    assert len(files) == 2

    first = files[0]
    # ASSY_LOT/MAPPING_LOT/OPER aren't in this transaction at all — left
    # blank rather than guessed, per the user's explicit instruction.
    assert first.assy_lot == ""
    assert first.mapping_lot == ""
    assert first.oper == ""
    assert first.eqpid == "BAB14"
    assert first.substrate_id == "Z2570900444F"
    assert first.substrate_row == 5
    assert first.substrate_column == 12
    assert first.total_bond_die_qty == 59
    assert first.good_die == 59
    assert len(first.die_info) == 59
    assert len(first.other_layer_die_info) == 177  # real 2-layer substrate

    first_die = first.die_info[0]
    assert first_die.wafer_ring == "HD56BA"
    # 2026/08/21: the log's raw DIE_INFO wafer_xy is row:col ("10:42"),
    # but a .strate file's wafer_xy is col:row (see secs_log.py's
    # _swap_wafer_xy()) — extraction now normalizes to "42:10".
    assert first_die.wafer_xy == "42:10"
    assert first_die.sub_pos == "0:0"
    assert first_die.bin == "1"


def test_extract_strate_files_round_trips_through_to_text_and_parse():
    from bingomap.strate import StrateFile

    text = _load_text()
    files = extract_strate_files(text)
    rendered = files[0].to_text()
    reparsed = StrateFile.parse(rendered)
    assert reparsed.die_info == files[0].die_info
    assert reparsed.other_layer_die_info == files[0].other_layer_die_info
    assert reparsed.substrate_id == files[0].substrate_id


def test_extract_wafer_maps_orientation_matches_real_strate_dies():
    text = _load_text()
    wafer_maps = extract_wafer_maps(text)
    assert len(wafer_maps) == 1
    wm = wafer_maps[0]
    assert wm.frame_id == "HD66D5"
    assert wm.wafer_id == "P0264807-24"
    assert wm.wafer_map.columns == 46
    assert wm.wafer_map.rows == 24

    # Most HD66D5 dies in the fixture's second StrateMap must resolve to
    # the SAME bin in the wafer map — this is the exact cross-check that
    # confirmed BinList's row=X/col=Y orientation against the real log
    # (189/196 = 96% on the full untrimmed log). A small mismatch rate is
    # expected and real, not a bug: a few dies the BinList (captured at
    # wafer-start) called good('1') were logged bin='7'/other by the time
    # they were actually picked minutes later — a real reclassification.
    strate_files = extract_strate_files(text)
    hd66d5_dies = [d for f in strate_files for d in f.die_info if d.wafer_ring == "HD66D5"]
    assert hd66d5_dies, "fixture must contain at least one HD66D5 die to make this check meaningful"
    matches = sum(
        1 for d in hd66d5_dies if wm.wafer_map.bin_at(*map(int, d.wafer_xy.split(":"))) == d.bin
    )
    assert matches / len(hd66d5_dies) >= 0.9, f"only {matches}/{len(hd66d5_dies)} matched"


def test_extract_wafer_maps_skips_events_without_binlist():
    # WaferUpload never has a <BinList> (only WaferStart does) — make sure
    # a transaction with no BinList element doesn't crash extraction.
    text = _load_text()
    wafer_maps = extract_wafer_maps(text)
    assert all(wm.wafer_map.cells for wm in wafer_maps)


def test_extract_strate_files_wafer_xy_matches_real_frm_die_map():
    """2026/08/21 regression test: the user reported "已寫入" picks from a
    SECS-log-extracted .strate landing outside the wafer's real bin data
    when loaded onto ①補資料/②誤吸偏移. Root cause: the log's own
    `<DIE_INFO>` wafer_xy field is row:col, but the .strate format's
    wafer_xy is col:row (identity-mapped onto the real wafer MAP for
    machine_type="DB", per test_mispick_analysis_real_db_sample.py's
    separate real-file verification) — two different real data sources,
    two different field orders. `_swap_wafer_xy()` normalizes to col:row
    on extraction; this locks that in against completely real files: every
    FC2643 wafer_xy from a real StrateMap (extracted from a real BAB14 log)
    must land on an actual bin='1' cell in FC2643's real .frm die map, with
    no collisions — the un-swapped (raw log) ordering only gets 35/49
    right, with 8 landing outside the wafer entirely and 6 on the wrong
    bin (see bingomap/CLAUDE.md for the full before/after comparison)."""
    from bingomap.frm_reader import parse_frm

    strate = _parse_strate_fixture()
    frm = parse_frm(
        (Path(__file__).parent / "fixtures" / "WPQ5310156SS_FC2643.frm").read_bytes()
    )

    fc2643_dies = [
        d
        for d in strate.die_info + strate.other_layer_die_info
        if d.wafer_ring == "FC2643"
    ]
    assert len(fc2643_dies) == 49, "fixture must have exactly the 49 FC2643 dies this test was built from"

    # This fixture .strate is the RAW file the user provided — its own
    # wafer_xy is still row:col (un-swapped), same as what a fresh
    # extract_strate_files() call would get straight from the log before
    # _swap_wafer_xy() runs. Swapping here reproduces exactly what that
    # function does, checked against real independent data (a real .frm),
    # not just the small trimmed log fixture the other tests use.
    seen_positions = set()
    for d in fc2643_dies:
        row_str, _, col_str = d.wafer_xy.partition(":")
        pos = (int(col_str), int(row_str))
        assert frm.die_map.get(pos) == 1, f"wafer_xy={d.wafer_xy!r} swapped -> {pos} is not a real bin=1 die"
        assert pos not in seen_positions, f"wafer_xy={d.wafer_xy!r} swapped -> {pos} collides with another die"
        seen_positions.add(pos)


def _parse_strate_fixture():
    from bingomap.strate import StrateFile

    path = Path(__file__).parent / "fixtures" / "2070_V30EUC6_Z25709007096_20260801024007.strate"
    return StrateFile.parse(path.read_text(encoding="utf-8"))


def test_iter_transactions_handles_self_closing_tag_immediately_before_real_one():
    # Regression test for a bug found 2026/08/19: a self-closing
    # `<Transaction ... />` (every empty Request half of a pair) has no
    # `</Transaction>` of its own. A naive single-alternative regex still
    # "matched" one by treating the `/>` as a plain `>` and then consuming
    # everything up to the NEXT transaction's closing tag — merging two
    # unrelated transactions into one invalid XML blob that ET.fromstring
    # then rejected, silently dropping BOTH. This only shows up when there
    # is no OTHER transaction's closing tag in between (as there normally
    # is in a busy real log) — reproduced here directly.
    text = (
        'INFO some log line\r\n'
        '<Transaction name="Foo" TID="1" Type="Request" DEID="X" />\r\n'
        '<Transaction name="Foo" TID="1" Type="Reply" DEID="X"><A>1</A></Transaction>\r\n'
    )
    results = list(iter_transactions(text))
    names_types = [(n, t) for n, t, _ in results]
    assert ("Foo", "Request") in names_types
    assert ("Foo", "Reply") in names_types
    reply_elem = next(e for n, t, e in results if t == "Reply")
    assert reply_elem.find("A").text == "1"
