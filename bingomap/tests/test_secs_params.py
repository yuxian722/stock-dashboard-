"""Tests against a real (trimmed) SECS/AFC transaction log — see
bingomap/secs_params.py's module docstring for the real S7F25 structure
this was built from (199 items, always 6 PPARM fields each, in the real
untrimmed log; 2 Reply captures, TID=58151 and TID=58203, back-to-back
with no other transaction between the second Request and its own Reply —
kept that way deliberately, see secs_params.py's _TRANSACTION_RE comment:
that adjacency is exactly what triggered the self-closing-tag regex bug
this fixture now guards against)."""
from pathlib import Path

import pytest

from bingomap.secs_log import decode_secs_log
from bingomap.secs_params import (
    ChecklistRow,
    SecsParam,
    SecsParamsFormatError,
    compare_checklist,
    extract_pp_param_snapshots,
)

FIXTURE = Path(__file__).parent / "fixtures" / "secs_params_sample.log"


def _load_text() -> str:
    return decode_secs_log(FIXTURE.read_bytes())


def test_extract_pp_param_snapshots_from_real_fixture():
    snaps = extract_pp_param_snapshots(_load_text())
    assert len(snaps) == 2
    snap = snaps[0]
    assert snap.pp_id == "RECIPE@AEU132X2C001A-2070"
    assert snap.mdln == "DB800"
    assert snap.softrev == "01.172/01"
    assert snap.tid == "58151"
    assert len(snap.params) == 10

    first = snap.params[0]
    assert first.ccode == "285278212"
    assert first.name == "No. of blocks"
    assert first.unit == ""
    assert first.format == "F8"
    assert first.value == "1"
    assert first.min == "0"
    assert first.max == "999"

    # Every CCODE in the fixture must be unique (matches the real log).
    ccodes = [p.ccode for p in snap.params]
    assert len(ccodes) == len(set(ccodes))


def test_extract_pp_param_snapshots_second_capture_not_dropped():
    """Regression test for the self-closing-tag regex bug found
    2026/08/19: TID=58203's Request is immediately followed by its own
    Reply with no other transaction's closing tag in between — the exact
    adjacency that made the naive regex merge the two and silently drop
    both. See secs_params.py's _TRANSACTION_RE comment."""
    snaps = extract_pp_param_snapshots(_load_text())
    assert len(snaps) == 2
    snap = snaps[1]
    assert snap.tid == "58203"
    assert snap.pp_id == "RECIPE@AEU132X2C001A-2070"
    assert len(snap.params) == 3
    assert snap.params[0].ccode == "285278212"


def test_extract_pp_param_snapshots_ignores_other_transactions():
    text = _load_text()
    assert "PickDie" not in text  # sanity: fixture really is just these transaction pairs
    snaps = extract_pp_param_snapshots(text)
    assert len(snaps) == 2  # only the Replies, not the paired empty Requests


def test_extract_pp_param_snapshots_empty_log_returns_empty_list():
    assert extract_pp_param_snapshots("INFO nothing here\r\n") == []


def test_item_with_wrong_pparm_count_raises():
    from bingomap.secs_params import _param_from_item
    from xml.etree import ElementTree as ET

    bad_item = ET.fromstring("<Item><CCODE>123</CCODE><PPARM>only one</PPARM></Item>")
    with pytest.raises(SecsParamsFormatError):
        _param_from_item(bad_item)


# ---- compare_checklist() — 2026/08/20 real Excel checklist matching ----
# (CCODE-based, confirmed against the user's real target-parameter Excel:
# 185/199 baseline CCODEs matched by exact CCODE, 4 of those had a minor
# name difference, 14 baseline CCODEs weren't in the checklist, 56 checklist
# CCODEs weren't in the baseline yet, and 9 CCODEs appeared twice in the
# checklist — every one of those five outcomes gets its own test below.)


def _param(ccode, name="", unit="", format="F8", value="0", min="0", max="999"):
    return SecsParam(ccode=ccode, name=name, unit=unit, format=format, value=value, min=min, max=max)


def test_compare_checklist_matched_and_name_mismatch():
    baseline = [_param("111", name="Same Name"), _param("222", name="Old Name")]
    checklist = [
        ChecklistRow(category="A", name="Same Name", ccode="111", id_name="DT_A"),
        ChecklistRow(category="A", name="New Name", ccode="222", id_name="DT_B"),
    ]
    result = compare_checklist(baseline, checklist)
    assert len(result.matched) == 2
    by_ccode = {m["ccode"]: m for m in result.matched}
    assert by_ccode["111"]["name_mismatch"] is False
    assert by_ccode["222"]["name_mismatch"] is True
    assert by_ccode["222"]["baseline_name"] == "Old Name"
    assert by_ccode["222"]["checklist_name"] == "New Name"
    assert result.machine_only == []
    assert result.checklist_only == []


def test_compare_checklist_machine_only_and_checklist_only():
    baseline = [_param("111", name="On machine"), _param("222", name="Also on machine")]
    checklist = [ChecklistRow(category="A", name="Target only", ccode="333", id_name="DT_C")]
    result = compare_checklist(baseline, checklist)
    assert result.matched == []
    assert {m["ccode"] for m in result.machine_only} == {"111", "222"}
    assert [r.ccode for r in result.checklist_only] == ["333"]
    assert result.checklist_only[0].name == "Target only"


def test_compare_checklist_reports_duplicate_ccodes_without_dropping_them():
    baseline = [_param("111", name="On machine")]
    checklist = [
        ChecklistRow(category="A", name="First occurrence", ccode="999", id_name="DT_X"),
        ChecklistRow(category="B", name="Second occurrence (probably a paste slip)", ccode="999", id_name="DT_X2"),
    ]
    result = compare_checklist(baseline, checklist)
    # comparison itself only counts each CCODE once (first occurrence)
    assert [r.ccode for r in result.checklist_only] == ["999"]
    assert result.checklist_only[0].name == "First occurrence"
    # but the duplicate is fully reported, not silently dropped
    assert len(result.duplicate_ccodes) == 1
    dup = result.duplicate_ccodes[0]
    assert dup["ccode"] == "999"
    assert [row.name for row in dup["rows"]] == ["First occurrence", "Second occurrence (probably a paste slip)"]
