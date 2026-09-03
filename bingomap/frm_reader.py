"""Parser for WaferCoordinate.exe's binary "FRM" wafer die-map files.

This is the real source of the green(bin1)/magenta(bin7) wafer grid — not
a document we were ever handed, but reverse-engineered by decompiling
WaferCoordinate.exe (ilspycmd) on 2026-08-14 and reading its
`DieAttachFmtRW.ReadMap()` method directly. Every field/offset below is
copied from that decompiled logic, not guessed or inferred from a sample
file — see bingomap/CLAUDE.md for how this was found and why the
alternative (SOAP API) approach was a dead end.

File location (also decompiled, from Main.cbBarcodeID_SelectedIndexChanged
and Main.GetBarcodeID): given a LotNo and a wafer Barcode ID, the FRM file
lives at:

    {FRM_PATH}\\{LotNo}\\{barcode[0:2]}\\{barcode[2:6]}

where FRM_PATH is WaferCoordinate.exe.config's FRM_PATH setting
(F:\\SMAP\\FRM\\ in the one config sample we have) — see frm_file_path().
That whole path is only reachable from ChipMOS's internal network, same
caveat as mapping_service.py.

Binary layout: the first byte doubles as both the `reverse_fixed` field
*and* a format discriminator — 0 selects the older, narrower "format I"
layout, 2 selects "format II" (wider row/col/qty fields, wider wafer_type).
After the fixed-size header comes `bin_kind_count` groups, each a
(bin_kind, bin_qty) pair followed by `bin_qty` (x, y) coordinate entries
belonging to that bin. bin_kind itself is stored as the ASCII code of the
digit character (e.g. the 2-byte big-endian value 49 means the character
'1', i.e. bin 1) — not the raw integer 1.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .wafer_map import WaferBinMap


class FrmFormatError(ValueError):
    """Raised when FRM bytes don't match either known header format."""


@dataclass
class FrmMap:
    format_version: int  # 0 ("format I") or 2 ("format II")
    row: int
    col: int
    reverse_fixed: int
    gross_dices: int
    lot_no: str
    wafer_id: str
    wafer_id_seq: str
    wafer_type: str
    reference_point_x: int
    reference_point_y: int
    bin_kind_count: int
    die_map: dict[tuple[int, int], int] = field(default_factory=dict)
    """(x, y) -> bin kind digit. x in [0, col), y in [0, row) — matches
    WaferCoordinate.exe's own DieMap[CorrY, CorrX] indexing."""


def frm_file_path(frm_root: str, lot_no: str, barcode_id: str) -> str:
    """Reproduces WaferCoordinate.exe's own path construction exactly."""
    barcode_id = barcode_id.strip()
    if len(barcode_id) < 6:
        raise ValueError(f"barcode_id must be at least 6 characters, got {barcode_id!r}")
    root = frm_root.rstrip("\\/")
    return f"{root}\\{lot_no.strip()}\\{barcode_id[0:2]}\\{barcode_id[2:6]}"


def _decode_ascii_bytes(chunk: bytes, *, skip_zero: bool) -> str:
    chars = []
    for byte in chunk:
        if skip_zero and byte == 0:
            continue
        chars.append(chr(byte))
    return "".join(chars).strip()


def _decode_bin_kind(chunk: bytes) -> int:
    value = chunk[0] * 256 + chunk[1]
    return int(chr(value))


_HEADER_V1_SIZE = 55
_HEADER_V2_SIZE = 63


def _parse_v1(data: bytes) -> FrmMap:
    if len(data) < _HEADER_V1_SIZE:
        raise FrmFormatError(f"FRM data too short for format-I header: {len(data)} bytes")

    reverse_fixed = data[0]
    row = data[1]
    col = data[2]
    gross_dices = data[3] * 256 + data[4]
    lot_no = _decode_ascii_bytes(data[5:25], skip_zero=False)
    wafer_id = _decode_ascii_bytes(data[25:33], skip_zero=False)
    wafer_id_seq = _decode_ascii_bytes(data[33:35], skip_zero=False)
    # data[35:37] reserved
    wafer_type = _decode_ascii_bytes(data[37:49], skip_zero=False)
    reference_point_x = data[49]
    reference_point_y = data[50]
    # data[51:53] reserved1
    bin_kind_count = data[53] * 256 + data[54]

    die_map: dict[tuple[int, int], int] = {}
    offset = _HEADER_V1_SIZE
    for _ in range(bin_kind_count):
        if offset + 4 > len(data):
            raise FrmFormatError("FRM data truncated inside a format-I bin-summary group")
        bin_kind = _decode_bin_kind(data[offset : offset + 2])
        bin_qty = data[offset + 2] * 256 + data[offset + 3]
        offset += 4
        for _ in range(bin_qty):
            if offset + 2 > len(data):
                raise FrmFormatError("FRM data truncated inside a format-I coordinate list")
            x, y = data[offset], data[offset + 1]
            die_map[(x, y)] = bin_kind
            offset += 2

    return FrmMap(
        format_version=0,
        row=row,
        col=col,
        reverse_fixed=reverse_fixed,
        gross_dices=gross_dices,
        lot_no=lot_no,
        wafer_id=wafer_id,
        wafer_id_seq=wafer_id_seq,
        wafer_type=wafer_type,
        reference_point_x=reference_point_x,
        reference_point_y=reference_point_y,
        bin_kind_count=bin_kind_count,
        die_map=die_map,
    )


def _parse_v2(data: bytes) -> FrmMap:
    if len(data) < _HEADER_V2_SIZE:
        raise FrmFormatError(f"FRM data too short for format-II header: {len(data)} bytes")

    reverse_fixed = data[0]
    row = data[1] * 256 + data[2]
    col = data[3] * 256 + data[4]
    gross_dices = data[5] * 16777216 + data[6] * 65536 + data[7] * 256 + data[8]
    lot_no = _decode_ascii_bytes(data[9:29], skip_zero=True)
    wafer_id = _decode_ascii_bytes(data[29:37], skip_zero=True)
    wafer_id_seq = _decode_ascii_bytes(data[37:39], skip_zero=True)
    # data[39:41] reserved
    wafer_type = _decode_ascii_bytes(data[41:57], skip_zero=True)
    reference_point_x = data[57]
    reference_point_y = data[58]
    # data[59:61] reserved1
    bin_kind_count = data[61] * 256 + data[62]

    die_map: dict[tuple[int, int], int] = {}
    offset = _HEADER_V2_SIZE
    for _ in range(bin_kind_count):
        if offset + 6 > len(data):
            raise FrmFormatError("FRM data truncated inside a format-II bin-summary group")
        bin_kind = _decode_bin_kind(data[offset : offset + 2])
        bin_qty = (
            data[offset + 2] * 16777216
            + data[offset + 3] * 65536
            + data[offset + 4] * 256
            + data[offset + 5]
        )
        offset += 6
        for _ in range(bin_qty):
            if offset + 4 > len(data):
                raise FrmFormatError("FRM data truncated inside a format-II coordinate list")
            x = data[offset] * 256 + data[offset + 1]
            y = data[offset + 2] * 256 + data[offset + 3]
            die_map[(x, y)] = bin_kind
            offset += 4

    return FrmMap(
        format_version=2,
        row=row,
        col=col,
        reverse_fixed=reverse_fixed,
        gross_dices=gross_dices,
        lot_no=lot_no,
        wafer_id=wafer_id,
        wafer_id_seq=wafer_id_seq,
        wafer_type=wafer_type,
        reference_point_x=reference_point_x,
        reference_point_y=reference_point_y,
        bin_kind_count=bin_kind_count,
        die_map=die_map,
    )


def parse_frm(data: bytes) -> FrmMap:
    """Parse raw FRM file bytes. The first byte selects format I (0) or
    format II (2) — any other value means this isn't an FRM file, or a
    format we haven't seen."""
    if not data:
        raise FrmFormatError("empty FRM data")
    format_byte = data[0]
    if format_byte == 0:
        return _parse_v1(data)
    if format_byte == 2:
        return _parse_v2(data)
    raise FrmFormatError(f"unrecognised FRM format byte {format_byte!r} (expected 0 or 2)")


def frm_to_wafer_bin_map(frm: FrmMap) -> WaferBinMap:
    """Adapt a parsed FRM file to the source-agnostic WaferBinMap that
    wafer_map.py's scan_rectangle()/build_picks_from_scan() consume. bin
    kinds are stringified to match DiePick/WaferBinMap's existing "1"/"7"
    string convention.

    2026/09/03再次更正，這次是撤銷2026/08/27那次的x/y對調：那次的證據
    (49顆FC2643 die，互換後49/49對到bin=1)本身沒錯，但下錯了結論的適用
    範圍——FC2643是EQPID=BAB14、NOTCH=270的ESEC類型wafer，`mispick_analysis.py`
    模組文件早就講明「DB(這個專案實際的機台)跟ESEC是兩套完全獨立的座標
    模型」，可是2026/08/27的修正卻直接把只驗證過ESEC案例的對調，寫死進了
    DB、ESEC共用的這個函式，等於用一個機種的個案結論覆蓋了另一個機種本來
    正確的行為。

    這次是使用者拿真實DB基板(EQPID=BAA08，wafer T3DC94，NOTCH=180，見
    `tests/fixtures/2130_V32AWCW_Z26306101253_20260814064943.strate`)回報
    第1顆die(`wafer_xy="23:48"`)完全沒出現在wafer預覽圖上、畫面上其餘的
    die全部擠在圖的一側——直接拿這299顆真實die座標去對同一Layout(AW191)
    的真實FRM(`8P065800A1_T3_DA62.frm`)原始`die_map`(不透過這個函式、
    完全繞開)重新交叉驗證：不對調的話299/299都落在wafer的合法(x,y)範圍
    內；套用2026/08/27對調後的版本只剩155/299——包括第1顆(Y=48)在內的
    144顆，Y座標超出對調後誤植的45上限(該軸實際上到55)，直接從圖上消失。

    也就是說：`frm.die_map`的key`(x,y)`原始命名——x對應`frm.col`(0..col)、
    y對應`frm.row`(0..row)——這次用DB真實資料驗證是正確的，不需要對調；
    2026/08/27對調後恰好能通過FC2643(ESEC/NOTCH=270)的驗證，是因為那片
    wafer的NOTCH跟DB案例不同、物理裝載方向不同，需要的是ESEC自己那條
    (`mispick_analysis.py`的`_wafer_xy_to_raw_map(machine_type="ESEC")`)
    座標轉換，不該靠這個共用函式裡硬幫所有機型對調座標軸來湊——這正好是
    這個專案第三次遇到「兩片真實wafer需要相反處理、沒有找到能自動判斷的
    通用欄位」(前兩次見bingomap/CLAUDE.md「wafer圖X/Y軸方向」)，解法一樣
    是不要把其中一個案例的結論當成放諸四海皆準的規則，寫死進共用邏輯。"""
    wafer_map = WaferBinMap(columns=frm.col, rows=frm.row)
    for (x, y), bin_kind in frm.die_map.items():
        wafer_map.set_bin(x, y, str(bin_kind))
    return wafer_map
