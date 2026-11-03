"""Tests against a real (trimmed) excerpt of a Diebonder's own GUI trace
log the user provided 2026/11/03 — see bingomap/gui_trace_log.py's module
docstring for background (this is NOT a SECS/AFC log; `secs_log.py`
doesn't apply here).

The two fixture files are deliberately split to mirror what actually
happened with the user's real diagnostic zip: the SAME physical trace log
rotates to a new file every few minutes, so one substrate's dies can be
split across multiple files — `extract_strate_files_from_gui_trace()`
must be given the whole batch's texts at once to merge correctly, which
is exactly what these two fixtures exercise (same SUBSTRATE_ID across
both files, plus duplicate re-logged events within each file that must be
deduplicated, not double-counted)."""
from pathlib import Path

from bingomap.gui_trace_log import (
    extract_strate_files_from_gui_trace,
    is_gui_trace_log_text,
)

FIXTURE_1 = Path(__file__).parent / "fixtures" / "gui_trace_ecslog_part1.log"
FIXTURE_2 = Path(__file__).parent / "fixtures" / "gui_trace_ecslog_part2.log"


def _load(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_is_gui_trace_log_text():
    assert is_gui_trace_log_text(_load(FIXTURE_1))
    assert not is_gui_trace_log_text("some ordinary SECS log text")


def test_extracts_and_dedupes_within_one_file():
    sfs = extract_strate_files_from_gui_trace([_load(FIXTURE_1)])
    assert len(sfs) == 1
    sf = sfs[0]
    assert sf.substrate_id == "Z26912130176"
    # fixture_part1 has 3 distinct (fx,fy,tx,ty) events, the middle one
    # (TX=3,TY=1) re-logged 3 times by 3 different internal components at
    # the exact same timestamp — must collapse to exactly one die, not 3.
    assert len(sf.die_info) == 2
    positions = {d.sub_pos for d in sf.die_info}
    assert positions == {"3:0", "3:1"}


def test_merges_same_substrate_across_files():
    sfs = extract_strate_files_from_gui_trace([_load(FIXTURE_1), _load(FIXTURE_2)])
    assert len(sfs) == 1
    sf = sfs[0]
    assert sf.substrate_id == "Z26912130176"
    assert len(sf.die_info) == 3
    positions = {d.sub_pos for d in sf.die_info}
    assert positions == {"3:0", "3:1", "16:1"}
    # sorted by timestamp, so the die from the later-rotated file comes last
    assert sf.die_info[-1].sub_pos == "16:1"


def test_die_info_fields_have_no_job_metadata_and_bin_1():
    sfs = extract_strate_files_from_gui_trace([_load(FIXTURE_1)])
    sf = sfs[0]
    assert sf.assy_lot == ""
    assert sf.mapping_lot == ""
    assert sf.oper == ""
    assert sf.eqpid == ""
    for d in sf.die_info:
        assert d.bin == "1"
        assert d.wafer_ring == "JE9C1A"


def test_wafer_xy_and_timestamp_match_known_real_values():
    sfs = extract_strate_files_from_gui_trace([_load(FIXTURE_1)])
    die = next(d for d in sfs[0].die_info if d.sub_pos == "3:0")
    assert die.wafer_xy == "27:15"
    assert die.timestamp == "20261103080119"


def test_empty_when_no_trace_marker_present():
    assert extract_strate_files_from_gui_trace(["not a trace log at all"]) == []


def test_round_trips_through_strate_parse():
    from bingomap.strate import StrateFile

    sf = extract_strate_files_from_gui_trace([_load(FIXTURE_1), _load(FIXTURE_2)])[0]
    reparsed = StrateFile.parse(sf.to_text())
    assert reparsed.substrate_id == sf.substrate_id
    assert len(reparsed.die_info) == len(sf.die_info)
