import pytest

from bingomap.crack_recovery import (
    MissingNotchError,
    WaferPoolRange,
    build_session,
    crack_csv_rows,
    crack_direction_label,
    crack_output_coord,
    local_view,
    notch_degrees,
    wafer_notch,
    wafer_pool_range,
    wafer_scatter,
)
from bingomap.mispick_analysis import InvalidGeometryError
from bingomap.strate import DieInfo, StrateFile

WAFER_RING = "TESTWAFER"


def _die(index, sub_pos, wafer_xy, wafer_ring=WAFER_RING, bin="1"):
    return DieInfo(index=index, wafer_ring=wafer_ring, wafer_xy=wafer_xy, sub_pos=sub_pos, bin=bin)


def _substrate(die_info, other_layer_die_info=None, notch="270", substrate_id="Z1"):
    return StrateFile(
        assy_lot="V27NVJH",
        mapping_lot="S7MJS",
        eqpid="BAB12",
        oper="2070",
        substrate_id=substrate_id,
        substrate_row=3,
        substrate_column=3,
        substrate_block=1,
        notch=notch,
        die_info=die_info,
        other_layer_die_info=other_layer_die_info or [],
    )


# --- local_view geometry, hand-derived (range fx:1..3, fy:5..7) ---

RNG = WaferPoolRange(min_x=1, max_x=3, min_y=5, max_y=7)


def test_local_view_notch_270():
    assert local_view(2, 6, RNG, 270) == (1, 1)
    assert local_view(1, 5, RNG, 270) == (2, 2)
    assert local_view(3, 7, RNG, 270) == (0, 0)


def test_local_view_notch_0_is_plain_xflip():
    assert local_view(1, 5, RNG, 0) == (2, 0)
    assert local_view(3, 7, RNG, 0) == (0, 2)


def test_local_view_notch_180():
    assert local_view(1, 5, RNG, 180) == (0, 2)
    assert local_view(3, 7, RNG, 180) == (2, 0)


def test_local_view_notch_90():
    assert local_view(1, 5, RNG, 90) == (0, 0)
    assert local_view(3, 7, RNG, 90) == (2, 2)


def test_local_view_unrecognized_notch_falls_back_to_xflip_like_0deg():
    # The reference tool's v78WaferView only special-cases 90/180/270;
    # anything else (e.g. 45) takes the same branch as notch=0.
    assert local_view(1, 5, RNG, 45) == local_view(1, 5, RNG, 0)


def test_notch_degrees_extracts_first_integer_tolerantly():
    assert notch_degrees("270") == 270
    assert notch_degrees(" 270 ") == 270
    assert notch_degrees("NOTCH=270deg") == 270
    assert notch_degrees("") is None
    assert notch_degrees(None) is None


def test_crack_direction_label():
    assert crack_direction_label(270) == "270_RIGHT"
    assert crack_direction_label(90) == "NOTCH_90"
    assert crack_direction_label(None) == "NOTCH_None"


# --- build_session ---


def test_build_session_creates_candidates_for_valid_rows():
    doc = ("a.strate", _substrate([_die(1, "0:0", "1:1"), _die(2, "1:0", "2:2")]))
    session = build_session([doc])
    assert len(session.candidates) == 2
    assert session.wafer_ids() == [WAFER_RING]


def test_build_session_normalizes_wafer_id():
    doc = ("a.strate", _substrate([_die(1, "0:0", "1:1", wafer_ring="  testwafer  ")]))
    session = build_session([doc])
    assert session.candidates[0].wafer_id == "TESTWAFER"


def test_build_session_skips_rows_missing_wafer_ring_or_wafer_xy():
    good = _die(1, "0:0", "1:1")
    no_ring = _die(2, "1:0", "2:2", wafer_ring="")
    bad_xy = DieInfo(index=3, wafer_ring=WAFER_RING, wafer_xy="", sub_pos="2:0", bin="1")
    doc = ("a.strate", _substrate([good, no_ring, bad_xy]))
    session = build_session([doc])
    assert len(session.candidates) == 1
    assert session.candidates[0].source_die.index == 1


def test_build_session_skips_rows_out_of_declared_geometry():
    out_of_bounds = _die(1, "9:9", "1:1")  # substrate is only 3x3
    good = _die(2, "0:0", "2:2")
    doc = ("a.strate", _substrate([out_of_bounds, good]))
    session = build_session([doc])
    assert len(session.candidates) == 1
    assert session.candidates[0].source_die.index == 2


def test_build_session_pools_multiple_docs_sharing_a_wafer_id():
    doc_a = ("a.strate", _substrate([_die(1, "0:0", "1:1")], substrate_id="Z1"))
    doc_b = ("b.strate", _substrate([_die(1, "0:0", "5:5")], substrate_id="Z2"))
    session = build_session([doc_a, doc_b])
    assert len(session.rows_for_wafer(WAFER_RING)) == 2


def test_build_session_raises_on_missing_notch():
    doc = ("a.strate", _substrate([_die(1, "0:0", "1:1")], notch=""))
    with pytest.raises(MissingNotchError):
        build_session([doc])


def test_build_session_any_notch_is_accepted_unlike_mispick_mode():
    # Crack mode has no NOTCH=270 lock, unlike mispick_analysis.
    doc = ("a.strate", _substrate([_die(1, "0:0", "1:1")], notch="90"))
    session = build_session([doc])
    assert len(session.candidates) == 1


def test_build_session_raises_on_invalid_geometry():
    bad = _substrate([_die(1, "0:0", "1:1")])
    bad.substrate_block = 2  # 3 columns / 2 blocks doesn't divide evenly
    with pytest.raises(InvalidGeometryError):
        build_session([("a.strate", bad)])


def test_build_session_raises_when_nothing_is_usable():
    doc = ("a.strate", _substrate([DieInfo(index=1, wafer_ring="", wafer_xy="", sub_pos="0:0", bin="1")]))
    with pytest.raises(ValueError):
        build_session([doc])


def test_build_session_processes_other_layer_too():
    primary = _die(1, "0:0", "1:1")
    other = _die(1, "1:0", "2:2")
    doc = ("a.strate", _substrate([primary], other_layer_die_info=[other]))
    session = build_session([doc])
    layers = {c.layer for c in session.candidates}
    assert layers == {"primary", "other"}


# --- wafer_pool_range / wafer_notch ---


def test_wafer_pool_range_and_notch_from_first_row():
    doc_a = ("a.strate", _substrate([_die(1, "0:0", "1:5")], notch="270", substrate_id="Z1"))
    doc_b = ("b.strate", _substrate([_die(1, "0:0", "3:7")], notch="90", substrate_id="Z2"))
    session = build_session([doc_a, doc_b])
    pool = session.rows_for_wafer(WAFER_RING)
    rng = wafer_pool_range(pool)
    assert (rng.min_x, rng.max_x, rng.min_y, rng.max_y) == (1, 3, 5, 7)
    # doc_a was appended first -> its row is first in the pool -> its NOTCH wins
    assert wafer_notch(pool) == 270


# --- CSV output ---


def test_crack_csv_rows_ordered_by_click_order_not_position():
    first_clicked = _die(1, "1:0", "3:7")  # will map to local (0,0) under notch270
    second_clicked = _die(2, "0:0", "1:5")  # will map to local (2,2) under notch270
    doc = ("a.strate", _substrate([first_clicked, second_clicked], notch="270"))
    session = build_session([doc])
    keys_by_index = {c.source_die.index: c.key for c in session.candidates}
    marked_keys = [keys_by_index[1], keys_by_index[2]]  # click order: die 1 then die 2

    rows = crack_csv_rows(session, marked_keys)
    assert rows[0] == crack_csv_rows(session, [])[0]  # header always present
    assert rows[1][0] == "C1"
    assert rows[1][9] == WAFER_RING  # complete_wafer_id column
    assert rows[1][12:14] == [0, 0]  # local_x, local_y for die 1
    assert rows[2][0] == "C2"
    assert rows[2][12:14] == [2, 2]  # local_x, local_y for die 2
    assert rows[1][15] == "1"  # crack_background_bin always "1"
    assert rows[1][16] == "270_RIGHT"
    assert rows[1][17] == "IMPORTED_LOCAL_ONLY"


def test_crack_csv_rows_ignores_unknown_keys():
    doc = ("a.strate", _substrate([_die(1, "0:0", "1:1")]))
    session = build_session([doc])
    rows = crack_csv_rows(session, ["not-a-real-key"])
    assert rows == [rows[0]]  # only the header


def test_crack_output_coord_matches_col_name_plus_1based_row():
    doc = ("a.strate", _substrate([_die(1, "1:0", "1:1")]))  # tx=1,ty=0 -> output (3-1-1,0)=(1,0)
    session = build_session([doc])
    assert crack_output_coord(session.candidates[0]) == "B1"


# --- wafer_scatter ---


def test_wafer_scatter_dedups_by_fxfy_and_flags_marked_points():
    a = _die(1, "0:0", "3:7")
    b = _die(2, "1:0", "1:5")
    # same FX:FY as `a` from a different substrate — should collapse to one point
    dup_of_a = _die(1, "0:0", "3:7", wafer_ring=WAFER_RING)
    doc1 = ("a.strate", _substrate([a, b], notch="270", substrate_id="Z1"))
    doc2 = ("b.strate", _substrate([dup_of_a], notch="270", substrate_id="Z2"))
    session = build_session([doc1, doc2])

    a_key = next(c.key for c in session.candidates if c.doc_index == 0 and c.source_die.index == 1)
    rng, notch, points = wafer_scatter(session, WAFER_RING, marked_keys=[a_key])

    assert (rng.min_x, rng.max_x, rng.min_y, rng.max_y) == (1, 3, 5, 7)
    assert notch == 270
    assert len(points) == 2  # deduped: 3 candidates but only 2 distinct fx:fy
    marked = [p for p in points if p.is_crack]
    assert len(marked) == 1
    assert marked[0].crack_no == 1
    assert marked[0].x == 0 and marked[0].y == 0  # matches local_view(3,7,RNG,270)


def test_wafer_scatter_unknown_wafer_id_raises():
    doc = ("a.strate", _substrate([_die(1, "0:0", "1:1")]))
    session = build_session([doc])
    with pytest.raises(KeyError):
        wafer_scatter(session, "NOPE", marked_keys=[])
