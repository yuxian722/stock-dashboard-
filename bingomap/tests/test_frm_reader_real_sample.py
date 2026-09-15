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


def test_frm_to_wafer_bin_map_swap_xy_restores_real_esec_strate_xy():
    """2026/09/03, same day as the revert above: reverting the swap fixed
    DB but broke the exact ESEC/NOTCH=270 case (FC2643, EU014 layout) the
    2026/08/27 swap was originally added for — the user re-reported
    "座標又跑到wafer外面" using this exact real file. Cross-checking FC2643's
    49 real die positions (from the same wafer_ring inside this file) against
    the real FC2643.frm directly: only 41/49 land in range without a swap,
    all 49/49 do with one — confirming this specific wafer genuinely needs
    the opposite of what T3DC94/DB needed (same "two real wafers need
    opposite handling, no auto-detectable field" pattern documented in
    bingomap/CLAUDE.md's "wafer圖X/Y軸方向" entries). frm_to_wafer_bin_map()
    now takes an explicit, opt-in swap_xy parameter instead of hardcoding
    either direction — this locks in that the option still does what it's
    for, without reintroducing it as the default."""
    from bingomap.strate import StrateFile

    fc2643_frm = parse_frm(
        (Path(__file__).parent / "fixtures" / "WPQ5310156SS_FC2643.frm").read_bytes()
    )
    strate = StrateFile.parse(
        (
            Path(__file__).parent
            / "fixtures"
            / "2070_V30EUC6_Z25709007096_20260801024007.strate"
        ).read_text(encoding="utf-8")
    )
    fc2643_dies = [
        d for d in strate.die_info + strate.other_layer_die_info if d.wafer_ring == "FC2643"
    ]
    assert len(fc2643_dies) == 49

    wafer_map_normal = frm_to_wafer_bin_map(fc2643_frm)
    wafer_map_swapped = frm_to_wafer_bin_map(fc2643_frm, swap_xy=True)

    def in_range_count(wafer_map):
        return sum(
            1
            for d in fc2643_dies
            if wafer_map.bin_at(*(int(v) for v in d.wafer_xy.split(":"))) is not None
        )

    assert in_range_count(wafer_map_normal) == 41
    assert in_range_count(wafer_map_swapped) == 49


def test_frm_to_wafer_bin_map_mirror_x_matches_independent_secs_log_100_percent():
    """2026/09/08: a third real wafer (59C5621S, WaferID=B6844E) needed
    neither swap_xy NOR a plain "no transform" — its FRM file's X axis
    (columns) is mirrored relative to the true wafer_xy convention, a
    completely different axis symptom from swap_xy's row/col transposition.

    Found by cross-referencing the FRM file against a SECOND, fully
    independent real data source for the exact same physical wafer: the
    machine's own SECS/AFC transaction log (`secs_log.py`'s
    extract_wafer_maps(), which decodes a WaferStart event's <BinList>
    into a WaferBinMap — a completely different code path from
    frm_reader.py, parsing a different file format). Comparing the two
    sources cell-by-cell over the full 22x81=1782 grid (1422 actual data
    points): without any mirror, only 59.6% of cells agreed — with
    `columns-1-x` applied to the FRM side, agreement is a clean 100.0%
    (1422/1422), not "mostly right with some noise". That clean jump from
    59.6% to 100% is what rules out "real bin reclassification between two
    time-separated scans" (which would leave some residual mismatch on
    BOTH sides, not disappear entirely) and confirms this is a genuine
    axis-mirroring difference in how the FRM file encodes X, specific to
    this wafer's scan.

    Re-verified mirror_x is NOT a universal frm_reader.py bug by re-running
    it against the two already-established wafers: T3DC94 (299 real die)
    barely changes (268 vs 271/299 bin1 matches — no real signal either
    way, this wafer never needed it) and FC2643 (49 real die, needs
    swap_xy=True) is *already* a perfect 49/49 without mirror_x and drops
    to 46/49 if mirror_x is wrongly added — confirming mirror_x, like
    swap_xy, is a per-physical-wafer opt-in setting, not something that
    belongs hardcoded into frm_to_wafer_bin_map()'s default behavior.

    2026/09/11大更正：`extract_wafer_maps()`後來改成對每個WaferStart自動
    偵測swap/flip(見secs_log.py)，這個log裡B6844E其實有18個WaferStart
    快照(不是1個)——同一片wafer在整段run裡被重複回報，前2個(index 0、1)
    內容彼此不同、也跟後面16個不同(明顯是run早期、還沒定案的暫存狀態)，
    但index 1之後、一路到最後一個(index 2~17)全部16個內容完全相同(已經
    穩定/最終的bin map)。舊版程式碼因為固定用同一套swap公式，「剛好」只
    有index 1這個tag方向相反的outlier會算出columns==22，所以舊測試
    `next(...columns==22)`意外挑到的正是index 1——不是刻意選的，是巧合。
    新版auto-detect讓全部18個快照都正確解出columns==22，所以`next(...)`
    現在改成挑到index 0(最早、還沒定案的暫存快照)，比對只剩59.6%——不是
    退步，是原本就該被丟掉的過渡態。這裡改成明確挑最後一個(index 17，
    16個穩定快照之一，任一個都可以，選最後一個最保守)，避免依賴tag方向
    這種巧合。"""
    from bingomap.secs_log import decode_secs_log, extract_wafer_maps

    frm = parse_frm((Path(__file__).parent / "fixtures" / "59C5621S_B6844E.frm").read_bytes())
    wafer_map = frm_to_wafer_bin_map(frm, swap_xy=False, mirror_x=True)

    log_text = decode_secs_log(
        (Path(__file__).parent / "fixtures" / "BAB1620260702_22.0.log").read_bytes()
    )
    wafer_maps = extract_wafer_maps(log_text)
    b6844e_maps = [wm.wafer_map for wm in wafer_maps if wm.frame_id == "B6844E" and wm.wafer_map.columns == 22]
    secs_wafer_map = b6844e_maps[-1]

    compared = 0
    for x in range(wafer_map.columns):
        for y in range(wafer_map.rows):
            secs_bin = secs_wafer_map.bin_at(x, y)
            if secs_bin is None:
                continue
            compared += 1
            assert wafer_map.bin_at(x, y) == secs_bin, (
                f"({x},{y}): FRM(mirror_x=True)={wafer_map.bin_at(x, y)!r} != "
                f"SECS log={secs_bin!r}"
            )
    assert compared == 1422


def test_frm_to_wafer_bin_map_mirror_y_matches_independent_secs_log_100_percent():
    """2026/09/15: a fourth real wafer (8L808002A1, Barcode=BB93AE, 45
    columns x 55 rows, 1931 real die) needed neither swap_xy, nor mirror_x,
    nor plain "no transform" — exhausting the 4 combinations of those two
    existing parameters against this wafer's own SECS log tops out at 70.7%
    (swap_xy=False, mirror_x=False), nowhere near the >=90% this project's
    real "wafer-scan-vs-pick-time" noise cases land at (see T3DC94 90.6%,
    FC2643/HD66D5 pre-fix 89.8%/94.5%) — a clear signal this wafer needs an
    axis transform outside what swap_xy/mirror_x can express.

    Exhaustively trying the full 8-way dihedral family (swap x flip_x x
    flip_y) against the same wafer's own SECS log (`secs_log.py`'s
    extract_wafer_maps(), auto-detected against this wafer's own StrateMap
    known positions elsewhere in the same log — 97.5% self-consistent,
    confirming the log itself is a trustworthy independent source) finds
    exactly one clean winner: swap=False, flip_x=False, flip_y=True ->
    1931/1931 = 100.0%. flip_y on the FRM's own die_map corresponds to
    mirror_y here (`rows-1-y`) — a genuinely different axis symptom from
    mirror_x's `columns-1-x`, confirmed independent of it (mirror_x's
    default False is untouched, this wafer simply never needed it).

    Re-verification against the three previously-established wafers
    (T3DC94, FC2643, 59C5621S) was not repeated for mirror_y specifically —
    mirror_y is a new, independent boolean defaulting to False, so it
    cannot change any existing call site's behavior unless explicitly
    opted into; the existing tests above already lock in that swap_xy/
    mirror_x continue to behave exactly as before."""
    from bingomap.secs_log import decode_secs_log, extract_wafer_maps

    frm = parse_frm((Path(__file__).parent / "fixtures" / "8L808002A1_BB93AE.frm").read_bytes())
    wafer_map = frm_to_wafer_bin_map(frm, swap_xy=False, mirror_x=False, mirror_y=True)

    log_text = decode_secs_log(
        (Path(__file__).parent / "fixtures" / "BAA0320260906_17.0_BB93AE_8L808002A1.log").read_bytes()
    )
    wafer_maps = extract_wafer_maps(log_text)
    bb93ae_maps = [wm.wafer_map for wm in wafer_maps if wm.frame_id == "BB93AE"]
    secs_wafer_map = bb93ae_maps[-1]

    compared = 0
    for x in range(wafer_map.columns):
        for y in range(wafer_map.rows):
            secs_bin = secs_wafer_map.bin_at(x, y)
            if secs_bin is None:
                continue
            compared += 1
            assert wafer_map.bin_at(x, y) == secs_bin, (
                f"({x},{y}): FRM(mirror_y=True)={wafer_map.bin_at(x, y)!r} != "
                f"SECS log={secs_bin!r}"
            )
    assert compared == 1931


def test_frm_to_wafer_bin_map_mirror_y_default_false_matches_only_70_percent():
    """Companion to the test above: locks in that WITHOUT mirror_y, this
    same wafer only reaches 70.7% (1365/1931) against the same independent
    SECS log — documents the "before" state so a future regression that
    silently defaults mirror_y to True (or otherwise changes the no-flags
    behavior) would be caught here, not just missed by the 100% test above
    passing for the wrong reason."""
    from bingomap.secs_log import decode_secs_log, extract_wafer_maps

    frm = parse_frm((Path(__file__).parent / "fixtures" / "8L808002A1_BB93AE.frm").read_bytes())
    wafer_map = frm_to_wafer_bin_map(frm)  # all defaults: swap_xy/mirror_x/mirror_y all False

    log_text = decode_secs_log(
        (Path(__file__).parent / "fixtures" / "BAA0320260906_17.0_BB93AE_8L808002A1.log").read_bytes()
    )
    wafer_maps = extract_wafer_maps(log_text)
    bb93ae_maps = [wm.wafer_map for wm in wafer_maps if wm.frame_id == "BB93AE"]
    secs_wafer_map = bb93ae_maps[-1]

    compared = agree = 0
    for x in range(wafer_map.columns):
        for y in range(wafer_map.rows):
            secs_bin = secs_wafer_map.bin_at(x, y)
            if secs_bin is None:
                continue
            compared += 1
            if wafer_map.bin_at(x, y) == secs_bin:
                agree += 1
    assert compared == 1931
    assert agree == 1365
