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
from bingomap.secs_params import SecsParamsFormatError, extract_pp_param_snapshots

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
