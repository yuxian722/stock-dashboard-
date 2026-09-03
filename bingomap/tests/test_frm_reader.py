"""Tests for frm_reader.py's binary FRM parser.

There's no real captured FRM file yet (it lives on ChipMOS's internal F:
network drive), so these bytes are hand-assembled to match the exact
struct layout read out of WaferCoordinate.exe's decompiled
DieAttachFmtRW.ReadMap()/CMAP_I_HEADER/CMAP_II_HEADER — see
bingomap/CLAUDE.md and the frm_reader.py module docstring for how that
layout was obtained. Once a real file is available it should get its own
byte-for-byte fixture test the same way strate.py's did.
"""
import pytest

from bingomap.frm_reader import FrmFormatError, frm_file_path, parse_frm
from bingomap.frm_reader import frm_to_wafer_bin_map


def _ascii(text: str, length: int) -> bytes:
    data = text.encode("ascii")
    assert len(data) <= length
    return data + b"\x00" * (length - len(data))


def _u16(value: int) -> bytes:
    return bytes([(value >> 8) & 0xFF, value & 0xFF])


def _u32(value: int) -> bytes:
    return bytes([(value >> 24) & 0xFF, (value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF])


def _build_format_ii(*, row, col, lot_no, wafer_id, wafer_id_seq, wafer_type, ref_x, ref_y, bins):
    header = bytes([2])  # reverse_fixed byte doubles as the format selector
    header += _u16(row)
    header += _u16(col)
    header += _u32(12345)  # gross_dices
    header += _ascii(lot_no, 20)
    header += _ascii(wafer_id, 8)
    header += _ascii(wafer_id_seq, 2)
    header += b"\x00\x00"  # reserve
    header += _ascii(wafer_type, 16)
    header += bytes([ref_x, ref_y])
    header += b"\x00\x00"  # reserve1
    header += _u16(len(bins))

    body = b""
    for bin_kind, coords in bins:
        body += _u16(ord(str(bin_kind)))
        body += _u32(len(coords))
        for x, y in coords:
            body += _u16(x) + _u16(y)
    return header + body


def _build_format_i(*, row, col, lot_no, wafer_id, wafer_id_seq, wafer_type, ref_x, ref_y, bins):
    header = bytes([0])  # format selector / reverse_fixed
    header += bytes([row, col])
    header += _u16(999)  # gross_dices
    header += _ascii(lot_no, 20)
    header += _ascii(wafer_id, 8)
    header += _ascii(wafer_id_seq, 2)
    header += b"\x00\x00"  # reserve
    header += _ascii(wafer_type, 12)
    header += bytes([ref_x, ref_y])
    header += b"\x00\x00"  # reserve1
    header += _u16(len(bins))

    body = b""
    for bin_kind, coords in bins:
        body += _u16(ord(str(bin_kind)))
        body += _u16(len(coords))
        for x, y in coords:
            body += bytes([x, y])
    return header + body


def test_parse_format_ii_header_fields():
    data = _build_format_ii(
        row=3, col=4, lot_no="V27NVJH", wafer_id="A27572", wafer_id_seq="01",
        wafer_type="AW191", ref_x=10, ref_y=20,
        bins=[(1, [(0, 0), (1, 0), (2, 1)]), (7, [(3, 2)])],
    )
    frm = parse_frm(data)
    assert frm.format_version == 2
    assert frm.row == 3
    assert frm.col == 4
    assert frm.lot_no == "V27NVJH"
    assert frm.wafer_id == "A27572"
    assert frm.wafer_id_seq == "01"
    assert frm.wafer_type == "AW191"
    assert frm.reference_point_x == 10
    assert frm.reference_point_y == 20
    assert frm.bin_kind_count == 2


def test_parse_format_ii_die_map_coordinates():
    data = _build_format_ii(
        row=3, col=4, lot_no="V27NVJH", wafer_id="A27572", wafer_id_seq="01",
        wafer_type="AW191", ref_x=0, ref_y=0,
        bins=[(1, [(0, 0), (1, 0), (2, 1)]), (7, [(3, 2)])],
    )
    frm = parse_frm(data)
    assert frm.die_map == {(0, 0): 1, (1, 0): 1, (2, 1): 1, (3, 2): 7}


def test_parse_format_i_header_and_die_map():
    data = _build_format_i(
        row=5, col=6, lot_no="M46ABC301", wafer_id="DD8FA5", wafer_id_seq="09",
        wafer_type="NV004", ref_x=1, ref_y=1,
        bins=[(1, [(0, 0), (1, 2)]), (9, [(5, 4)])],
    )
    frm = parse_frm(data)
    assert frm.format_version == 0
    assert frm.row == 5
    assert frm.col == 6
    # format I keeps null padding (see test below) — strip it here since
    # this test is about the other fields, not that quirk specifically.
    assert frm.wafer_type.rstrip("\x00") == "NV004"
    assert frm.die_map == {(0, 0): 1, (1, 2): 1, (5, 4): 9}


def test_format_i_lot_no_keeps_null_padding_format_ii_strips_it():
    # Documented quirk, not a bug to "fix": WaferCoordinate.exe's format-I
    # string getters never filter null bytes, format-II's always do — see
    # decompiled CMAP_I_HEADER.LotNo vs CMAP_II_HEADER.LotNo.
    data_i = _build_format_i(
        row=1, col=1, lot_no="AB", wafer_id="X", wafer_id_seq="0",
        wafer_type="T", ref_x=0, ref_y=0, bins=[],
    )
    assert "\x00" in parse_frm(data_i).lot_no

    data_ii = _build_format_ii(
        row=1, col=1, lot_no="AB", wafer_id="X", wafer_id_seq="0",
        wafer_type="T", ref_x=0, ref_y=0, bins=[],
    )
    assert "\x00" not in parse_frm(data_ii).lot_no
    assert parse_frm(data_ii).lot_no == "AB"


def test_parse_frm_rejects_unknown_format_byte():
    with pytest.raises(FrmFormatError, match="unrecognised FRM format byte"):
        parse_frm(bytes([9, 0, 0]))


def test_parse_frm_rejects_empty_data():
    with pytest.raises(FrmFormatError):
        parse_frm(b"")


def test_parse_frm_rejects_truncated_header():
    with pytest.raises(FrmFormatError):
        parse_frm(bytes([2, 0, 0]))


def test_frm_to_wafer_bin_map_converts_correctly():
    # 2026/09/03撤銷了2026/08/27那次的x/y對調(見frm_to_wafer_bin_map()
    # docstring的完整說明——那次對調只驗證過ESEC案例，套用到DB身上是錯的)，
    # 這裡改回直接對應die_map的raw key：columns=frm.col、rows=frm.row，
    # bin_at(x, y)直接吃die_map原始的(x, y)。
    data = _build_format_ii(
        row=2, col=3, lot_no="V27NVJH", wafer_id="A27572", wafer_id_seq="01",
        wafer_type="AW191", ref_x=0, ref_y=0,
        bins=[(1, [(0, 0), (1, 0)]), (7, [(2, 1)])],
    )
    frm = parse_frm(data)
    wafer_map = frm_to_wafer_bin_map(frm)
    assert wafer_map.columns == 3
    assert wafer_map.rows == 2
    assert wafer_map.bin_at(0, 0) == "1"
    assert wafer_map.bin_at(1, 0) == "1"
    assert wafer_map.bin_at(2, 1) == "7"
    assert wafer_map.bin_at(9, 9) is None


def test_frm_file_path_matches_wafercoordinate_construction():
    # F:\SMAP\FRM\<LotNo>\<barcode[0:2]>\<barcode[2:6]>, straight out of
    # Main.cbBarcodeID_SelectedIndexChanged in the decompiled source.
    path = frm_file_path("F:\\SMAP\\FRM\\", "8P065800A1", "T3DA62")
    assert path == "F:\\SMAP\\FRM\\8P065800A1\\T3\\DA62"


def test_frm_file_path_rejects_short_barcode():
    with pytest.raises(ValueError):
        frm_file_path("F:\\SMAP\\FRM\\", "8P065800A1", "T3D")
