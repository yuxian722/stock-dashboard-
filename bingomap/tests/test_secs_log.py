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
    # 2026/08/26大更正：StrateMap的<DIE_INFO> wafer_xy不需要swap——直接
    # 拿使用者提供的完整真實log交叉比對真正的.strate檔案(同一顆Z25709007096
    # 基板)確認：log的DIE_INFO跟真正machine產生的.strate檔案逐行byte-for-
    # byte完全一致(224顆die，0個不一樣)，wafer_xy本來就已經是.strate格式
    # 自己的col:row，不需要任何轉換。之前那次「swap才對」的結論來自另一個
    # 獨立的bug(frm.die_map/BinList的欄位語意搞反，見secs_log.py模組
    # docstring的完整說明)，兩個bug剛好互相抵消，掩蓋了真正的問題。
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
    # 2026/08/26大更正：WaferStart的<ColCount>/<RowCount>標籤名稱跟
    # .strate格式自己的col/row軸向是對調的(見secs_log.py模組docstring
    # /wafer_map_from_element()的完整說明)，這裡建構WaferBinMap時已經
    # 把columns/rows對調成(RowCount, ColCount)，所以columns看起來是24
    # (原始RowCount)、rows是46(原始ColCount)。
    assert wm.wafer_map.columns == 24
    assert wm.wafer_map.rows == 46

    # Every HD66D5 die in the fixture's second StrateMap must resolve to
    # the SAME bin in the wafer map — this is the exact cross-check that
    # confirmed BinList's true col/row orientation against the real log.
    # 2026/09/11大更正：本來這裡只要求>=0.9(52/55)，剩下的當成真實
    # reclassification雜訊——但窮舉全部8種swap/flip_x/flip_y組合後發現，
    # 加上這次extract_wafer_maps()新增的自動偵測(對同一份log自己的
    # StrateMap位置+bin自我校驗)，這裡其實能到100.0%(220/220，用完整
    # log而非trimmed樣本驗證過)，不是雜訊——是原本ColCount/RowCount對調
    # 之外還漏了一次180度整體翻轉。trimmed樣本資料量小，這裡保留>=0.9
    # 門檻只是避免trimming意外丟資料造成脆弱測試，不代表允許有雜訊。
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


def test_extract_strate_files_die_info_matches_real_strate_byte_for_byte():
    """2026/08/26 regression test: the user reported "補資料" pick positions
    from a SECS-log STRATE補檔 extraction landing outside the wafer, and gave
    both a real BAB14 log AND the real `.strate` file the SAME machine
    produced for the SAME substrate (Z25709007096) so the two could be
    cross-checked directly rather than guessed. Root cause: `_swap_wafer_xy()`
    (removed) had it backwards — a `StrateMap`'s `<DIE_INFO>`/
    `<DIE_INFO_OTHER_LAYER>` `wafer_xy` is ALREADY in the exact `.strate`-
    native col:row format, needing NO transform at all. Proof: every single
    DIE_INFO/DIE_INFO_OTHER_LAYER line this fixture log extracts is
    byte-for-byte IDENTICAL to the corresponding line in the real machine-
    produced `.strate` file below — not just "close", not a coincidence on a
    handful of dies, the full 56+168=224 entries. (The earlier, wrong "swap
    needed" conclusion came from a completely separate, since-fixed bug: the
    old code cross-checked wafer_xy against `frm.die_map`/`BinList` using the
    wrong (col,row) vs (row,col) key order for THOSE structures — a second,
    independent mislabeling that happened to cancel out the first one just
    well enough to look like "swapping wafer_xy" was the fix. See this
    module's docstring and `wafer_map_from_element()` for that half of the
    story.)"""
    from bingomap.strate import StrateFile

    log_path = Path(__file__).parent / "fixtures" / "BAB1420260801_04_Z25709007096.log"
    text = decode_secs_log(log_path.read_bytes())
    extracted = extract_strate_files(text)
    assert len(extracted) == 1
    extracted_strate = extracted[0]

    # Same real substrate as _parse_strate_fixture()'s FRM cross-check below
    # — confirmed byte-identical to the file this test's log fixture was
    # trimmed from (a copy of the exact file the user attached, verified
    # 2026/08/26 via `diff` against the untrimmed original before this test
    # was written), so reusing that fixture here isn't a coincidence.
    real_strate = _parse_strate_fixture()

    assert extracted_strate.substrate_id == real_strate.substrate_id == "Z25709007096"
    assert len(extracted_strate.die_info) == len(real_strate.die_info) == 56
    assert len(extracted_strate.other_layer_die_info) == len(real_strate.other_layer_die_info) == 168
    assert extracted_strate.die_info == real_strate.die_info
    assert extracted_strate.other_layer_die_info == real_strate.other_layer_die_info


def test_extract_wafer_maps_matches_real_frm_die_map_no_string_swap():
    """Same real log/substrate as the test above, cross-checked the other
    direction: every FC2643 die position this log's `WaferStart` BinList
    resolves to bin='1' at the die's own (unswapped) `wafer_xy` — confirming
    `wafer_map_from_element()`'s corrected ColCount/RowCount handling lines
    up with `_die_list()`'s now-untransformed wafer_xy.

    2026/09/11大更正：本來這裡只要求>=0.85(44/49)，多出來的5顆算成真實
    reclassification雜訊——但`extract_wafer_maps()`新增自動偵測8種swap/
    flip組合(對同一份log自己的StrateMap位置+bin自我校驗)後，這裡其實是
    100.0%(49/49)：原本的公式除了ColCount/RowCount對調，還漏了一次180度
    整體翻轉，那5顆不是雜訊，是座標算錯了。"""
    log_path = Path(__file__).parent / "fixtures" / "BAB1420260801_04_Z25709007096.log"
    text = decode_secs_log(log_path.read_bytes())
    wafer_maps = extract_wafer_maps(text)
    assert len(wafer_maps) == 1
    wm = wafer_maps[0]
    assert wm.frame_id == "FC2643"

    strate = _parse_strate_fixture()
    fc2643_dies = [d for d in strate.die_info + strate.other_layer_die_info if d.wafer_ring == "FC2643"]
    assert len(fc2643_dies) == 49

    matches = sum(1 for d in fc2643_dies if wm.wafer_map.bin_at(*map(int, d.wafer_xy.split(":"))) == "1")
    assert matches == 49, f"only {matches}/{len(fc2643_dies)} matched"


def test_extract_wafer_maps_auto_detects_different_axis_convention_per_machine():
    """2026/09/11: the user reported a real wafer (BB93AE, LOT=8N027703A1,
    EQPID=BAA03 — a *different* machine from the BAB14 wafers above) whose
    picks looked like they landed on bin='7' (pink) in a screenshot when
    they should have been bin='1' (green), and gave both the real
    `.strate` STRATE補檔 (`2070_V36AWAQ_J8204486_20260906135238.strate`,
    304 dies, all wafer_ring=BB93AE, all bin='1') and the SECS log for the
    SAME substrate/wafer to check directly.

    Exhaustively trying all 8 swap/flip_x/flip_y readings of BB93AE's own
    `WaferStart` BinList against these same 304 die positions: the
    convention that already works for BAB14 (swap, both flips — see the
    FC2643/HD66D5 tests above) only gets 244/304=80.3% here; the *raw*,
    un-swapped reading with only Y flipped gets a clean 304/304=100.0%
    instead. Different real machines need different axis conventions here,
    same pattern as `frm_reader.py`'s per-wafer `swap_xy`/`mirror_x` — so
    `extract_wafer_maps()` now auto-detects per wafer via this exact
    exhaustive self-cross-check against the same log's own StrateMap data,
    rather than assuming one fixed convention for every log."""
    log_path = Path(__file__).parent / "fixtures" / "BAA0320260906_17.0_BB93AE.log"
    text = decode_secs_log(log_path.read_bytes())

    strate_files = extract_strate_files(text)
    assert len(strate_files) == 1
    sf = strate_files[0]
    assert sf.substrate_id == "J8204486"
    assert len(sf.die_info) == 304
    assert all(d.wafer_ring == "BB93AE" and d.bin == "1" for d in sf.die_info)

    wafer_maps = extract_wafer_maps(text)
    assert len(wafer_maps) == 1
    wm = wafer_maps[0]
    assert wm.frame_id == "BB93AE"

    matches = sum(1 for d in sf.die_info if wm.wafer_map.bin_at(*map(int, d.wafer_xy.split(":"))) == "1")
    assert matches == 304, f"only {matches}/304 landed on bin1 — expected a clean 100%"

    # The real .strate the user uploaded, byte-for-byte, to lock in that
    # extract_strate_files() reproduces exactly what the machine produced.
    from bingomap.strate import StrateFile

    real_strate = StrateFile.parse(
        (Path(__file__).parent / "fixtures" / "2070_V36AWAQ_J8204486_20260906135238.strate").read_text(
            encoding="utf-8"
        )
    )
    assert sf.die_info == real_strate.die_info


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
