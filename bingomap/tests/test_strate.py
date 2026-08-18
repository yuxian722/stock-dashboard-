from pathlib import Path

import pytest

from bingomap.strate import DieInfo, StrateFile, StrateFormatError

FIXTURE = Path(__file__).parent / "fixtures" / "2070_V27NVJH_Z281226C_20260812221959.strate"


def _read_fixture() -> str:
    # newline="" preserves the file's CRLF endings verbatim instead of
    # letting universal-newline translation collapse them to "\n".
    with open(FIXTURE, encoding="ascii", newline="") as f:
        return f.read()


def test_round_trip_matches_real_sample_byte_for_byte():
    original = FIXTURE.read_bytes()
    parsed = StrateFile.parse(original.decode("ascii"))
    assert parsed.to_text().encode("ascii") == original


def test_parse_accepts_bare_lf_line_endings():
    # Reproduces the real bug: a <textarea>'s .value normalizes CRLF to
    # LF on read (confirmed live in a browser), so the webapp's "貼上
    # 檔案內容"/複製既有.strate為範本 path can hand parse() perfectly
    # valid content with LF-only line endings. It must not be rejected
    # with the misleading "Missing [DIE_INFO_BEG] marker".
    crlf_text = _read_fixture()
    lf_only_text = crlf_text.replace("\r\n", "\n")
    assert "\r" not in lf_only_text  # sanity-check the test setup itself

    parsed = StrateFile.parse(lf_only_text)
    assert parsed.assy_lot == "V27NVJH"
    assert len(parsed.die_info) == 75
    # output is unaffected — always CRLF regardless of what parse() accepted
    assert parsed.to_text().encode("ascii") == FIXTURE.read_bytes()


def test_header_fields_parsed_correctly():
    parsed = StrateFile.parse(_read_fixture())
    assert parsed.assy_lot == "V27NVJH"
    assert parsed.mapping_lot == "S7MJS"
    assert parsed.eqpid == "BAB12"
    assert parsed.oper == "2070"
    assert parsed.substrate_id == "Z281226C"
    assert parsed.substrate_row == 4
    assert parsed.substrate_column == 20
    assert parsed.substrate_block == 2
    assert parsed.total_bond_die_qty == 75
    assert parsed.good_die == 75
    assert parsed.notch == "180"
    assert parsed.ref == "-72,340"
    assert parsed.t2_point == "NA"
    assert parsed.t2_flat == "NA"


def test_die_info_parsed_correctly():
    parsed = StrateFile.parse(_read_fixture())
    assert len(parsed.die_info) == 75
    first = parsed.die_info[0]
    assert first.index == 1
    assert first.wafer_ring == "A27572"
    assert first.wafer_xy == "23:195"
    assert first.sub_pos == "0:0"
    assert first.bin == "1"
    assert first.timestamp == "20260812221633"
    last = parsed.die_info[-1]
    assert last.index == 75
    assert last.sub_pos == "19:3"


def test_missing_substrate_positions_are_simply_absent():
    # SOP-confirmed behaviour: unbonded substrate sites are omitted from
    # DIE_INFO entirely rather than written with bin=0.
    parsed = StrateFile.parse(_read_fixture())
    positions = {d.sub_pos for d in parsed.die_info}
    for missing in ("0:3", "4:2", "6:2", "15:1", "19:2"):
        assert missing not in positions
    assert "0:0" in positions and "19:3" in positions


def test_filename_matches_naming_convention():
    parsed = StrateFile.parse(_read_fixture())
    assert parsed.filename("20260812221959") == "2070_V27NVJH_Z281226C_20260812221959.strate"


def test_die_info_line_must_have_nine_fields():
    with pytest.raises(StrateFormatError):
        DieInfo.from_line("1,A27572,23:195,0:0,1,0,0,20260812221633")


def test_parse_rejects_missing_die_info_end():
    text = "ASSY_LOT=X\r\n[DIE_INFO_BEG]\r\n1,,,0:0,1,0,0,0,1\r\n"
    with pytest.raises(StrateFormatError):
        StrateFile.parse(text)
