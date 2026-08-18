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
    assert first_die.wafer_xy == "10:42"
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
