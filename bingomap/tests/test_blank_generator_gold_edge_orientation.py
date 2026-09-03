"""2026/08/31: user reported the machine's real substrate loading is
"金邊朝下"(gold-edge-down), while the real ChipMOS "Bingo Map Query" web
report (and the SOP-documented, already-verified convention — see
bingomap/CLAUDE.md's blank_generator.py section) shows "金邊朝上"
(gold-edge-up), and asked whether generate_blank()'s DB/EPOXY position
convention needs a 180-degree correction for this case.

Real evidence used to answer this (see bingomap/CLAUDE.md for the full
story): the user provided a real SECS/AFC log (BAA0820260814_07.0.log)
containing the actual StrateMap transaction for substrate Z26306101253 —
a real strip confirmed (via the machine's own FASFORD Direct Bond screen,
Good Paddles=299/NG Paddles=9, matching Bingo Map Query's own
Pass Qty=299/Fail Qty=9 for the same Strip ID) to have been processed
gold-edge-down that day.

The decisive check: the real DIE_INFO's sub_pos walk ORDER exactly
matches generate_blank(convention="EPOXY")'s own generated order,
position-for-position (byte-for-byte), once the 9 real
gaps (unfilled/NG positions — simply absent rows, per this project's
established "unloaded positions are omitted, not written bin=0" rule)
are removed from the predicted sequence. This alone answers the
practical question — generate_blank()'s raw sub_pos convention is the
machine's own fixed internal coordinate frame, independent of which way
gold-edge faced during that run, and needs NO code change.

(Separately, and now confirmed with a clear, legible screenshot of the
same real Bingo Map Query report — 2026/08/31, after an earlier blurry
photo left 1 of 9 labels ambiguous: converting those same 9 gaps to
Bingo Map Query's own 1-indexed letter-column/number-row labels lines up
EXACTLY, 9 of 9, with the real fail labels Bingo Map Query reports
(G9, G10, H10, I10, I11, O6, P6, Y5, AA11) under a "reflect ROW only,
column unchanged" relabeling (`row_label = row_count - row_0indexed`,
column letter untouched) — confirming Bingo Map Query applies its own
orientation-aware display correction downstream of the raw file. This
doesn't change the conclusion above — that relabeling is Bingo Map
Query's own display concern, not something the raw .strate needs to
reproduce — but it is now fully pinned down rather than 8/9-confirmed.)
"""
from pathlib import Path

from bingomap.blank_generator import generate_blank
from bingomap.secs_log import decode_secs_log, extract_strate_files

FIXTURE = Path(__file__).parent / "fixtures" / "BAA0820260814_07_Z26306101253.log"

# The 9 real gap positions (0-indexed col:row, as written in DIE_INFO's own
# sub_pos convention) — substrate positions this real, gold-edge-down strip
# has NO die_info row for (NG/unfilled, omitted per this project's
# established rule).
REAL_GAP_POSITIONS = {
    (6, 1), (6, 2), (7, 1), (8, 0), (8, 1),
    (14, 5), (15, 5), (24, 6), (26, 0),
}

# Bingo Map Query's own real fail-position labels for the same strip
# (Strip ID Z26306101253, Fail Qty=9) — read straight off a clear, legible
# screenshot of the real report (2026/08/31, superseding an earlier blurry
# photo that left one label ambiguous).
BINGO_MAP_QUERY_FAIL_LABELS = {
    "G9", "G10", "H10", "I10", "I11", "O6", "P6", "Y5", "AA11",
}


def _col_letter(col_1indexed: int) -> str:
    """Spreadsheet-style column letters (1=A, 26=Z, 27=AA, 28=AB, ...)."""
    letters = ""
    n = col_1indexed
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def _load_real_strate_map():
    text = decode_secs_log(FIXTURE.read_bytes())
    files = extract_strate_files(text)
    assert len(files) == 1
    return files[0]


def test_real_gold_edge_down_die_info_gaps_match_declared_constant():
    sf = _load_real_strate_map()
    assert sf.substrate_id == "Z26306101253"
    assert sf.substrate_row == 11
    assert sf.substrate_column == 28
    assert len(sf.die_info) == 299  # 308 - 9 real gaps

    positions = {tuple(int(v) for v in d.sub_pos.split(":")) for d in sf.die_info}
    full_grid = {(c, r) for c in range(28) for r in range(11)}
    assert full_grid - positions == REAL_GAP_POSITIONS


def test_generate_blank_db_epoxy_already_matches_real_gold_edge_down_walk_order():
    # The core finding: NO gold-edge-orientation correction is needed in
    # generate_blank() at all — its existing default (DB/EPOXY) output,
    # order and all, is already byte-for-byte identical to what this real
    # gold-edge-down strip's machine actually produced, once the same 9
    # real gaps are removed from the predicted sequence.
    sf = _load_real_strate_map()
    real_positions = [d.sub_pos for d in sf.die_info]

    blank = generate_blank(
        assy_lot="V32AWCW01", mapping_lot="", eqpid="BAA08", oper="2070",
        substrate_id="Z26306101253", substrate_row=11, substrate_column=28,
        substrate_block=1, notch="180", ref="",
        convention="EPOXY",
    )
    predicted_positions = [
        p for p in (d.sub_pos for d in blank.die_info)
        if tuple(int(v) for v in p.split(":")) not in REAL_GAP_POSITIONS
    ]
    assert predicted_positions == real_positions


def test_real_gap_positions_match_bingo_map_query_labels_reflecting_row_only():
    # The secondary finding, now fully confirmed (9/9, see module docstring):
    # Bingo Map Query's own row-relabeling is a ROW-only reflection — the
    # column letter is untouched. This is Bingo Map Query's own downstream
    # display transform, not something generate_blank()/the raw .strate
    # needs to apply — see the two tests above for why no code change is
    # needed regardless of this.
    row_count = 11
    reflected_labels = {
        f"{_col_letter(col + 1)}{row_count - row}" for col, row in REAL_GAP_POSITIONS
    }
    assert reflected_labels == BINGO_MAP_QUERY_FAIL_LABELS
