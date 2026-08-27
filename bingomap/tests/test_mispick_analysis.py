import pytest

from bingomap.mispick_analysis import (
    DECISION_FORCE_DELETE,
    DECISION_NOMINAL_NOT_GOOD,
    DECISION_OK,
    DECISION_REVIEW,
    InvalidGeometryError,
    UnknownMachineTypeError,
    UnsupportedNotchError,
    analyze_substrate,
    col_name,
    make_offset,
    output_coord,
    output_position,
    parse_bin_set,
)
from bingomap.strate import DieInfo, StrateFile
from bingomap.wafer_map import WaferBinMap

WAFER_RING = "TESTWAFER"


def _wafer_map():
    # 5x5 (x,y in 0..4), all Good ("1") except (2,2)=NG("7") and (3,3)=Review("2").
    m = WaferBinMap(columns=5, rows=5)
    for x in range(5):
        for y in range(5):
            m.set_bin(x, y, "1")
    m.set_bin(2, 2, "7")
    m.set_bin(3, 3, "2")
    return m


def _substrate(die_info, other_layer_die_info=None, notch="270"):
    return StrateFile(
        assy_lot="V27NVJH",
        mapping_lot="S7MJS",
        eqpid="BAB12",
        oper="2070",
        substrate_id="Z281226C",
        substrate_row=3,
        substrate_column=3,
        substrate_block=1,
        notch=notch,
        die_info=die_info,
        other_layer_die_info=other_layer_die_info or [],
    )


def _die(index, sub_pos, wafer_xy, wafer_ring=WAFER_RING, bin="1"):
    return DieInfo(index=index, wafer_ring=wafer_ring, wafer_xy=wafer_xy, sub_pos=sub_pos, bin=bin)


# --- ESEC coordinate math (machine_type="ESEC" — NOT this project's real
# machine type; DB is, see the tests below and module docstring) ---


def test_offset_lands_on_ng_bin_is_force_delete():
    # Hand-derived (see PR/commit description): fx=2,fy=3 -> nominal raw-MAP
    # (2,3)=Good -> machine (1,2) -> +X1 -> machine (2,2) -> raw-MAP (2,2)="7".
    substrate = _substrate([_die(1, "1:0", "2:3")])
    result = analyze_substrate(
        substrate,
        _wafer_map(),
        wafer_ring=WAFER_RING,
        offset=make_offset("X", 1),
        good_bins={"1"},
        ng_bins={"7", "9"},
        review_bins={"2"},
        machine_type="ESEC",
    )
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.nominal_bin == "1"
    assert row.actual_map_xy == (2, 2)
    assert row.actual_bin == "7"
    assert row.decision == DECISION_FORCE_DELETE
    assert row.action_no == 1  # the only action row here; see the ordering test for multi-row numbering


def test_offset_lands_on_review_bin():
    # fx=1,fy=4 -> nominal raw-MAP (3,4)=Good -> machine (0,3) -> +X1 ->
    # machine (1,3) -> raw-MAP (3,3)="2" (review).
    substrate = _substrate([_die(1, "2:0", "1:4")])
    result = analyze_substrate(
        substrate,
        _wafer_map(),
        wafer_ring=WAFER_RING,
        offset=make_offset("X", 1),
        good_bins={"1"},
        ng_bins={"7", "9"},
        review_bins={"2"},
        machine_type="ESEC",
    )
    row = result.rows[0]
    assert row.actual_map_xy == (3, 3)
    assert row.decision == DECISION_REVIEW
    assert row.action_no == 1  # output_xy (0,0) sorts before the force-delete row's (1,0)


def test_offset_lands_back_on_good_bin_is_ok():
    substrate = _substrate([_die(1, "0:0", "1:1")])
    result = analyze_substrate(
        substrate,
        _wafer_map(),
        wafer_ring=WAFER_RING,
        offset=make_offset("X", 1),
        good_bins={"1"},
        ng_bins={"7", "9"},
        review_bins={"2"},
        machine_type="ESEC",
    )
    row = result.rows[0]
    assert row.decision == DECISION_OK
    assert row.action_no is None


def test_nominal_position_not_good_is_dropped_not_an_action():
    # fx=2,fy=2 -> nominal raw-MAP (2,2)="7", never Good in the first place.
    substrate = _substrate([_die(1, "0:2", "2:2")])
    result = analyze_substrate(
        substrate,
        _wafer_map(),
        wafer_ring=WAFER_RING,
        offset=make_offset("X", 1),
        good_bins={"1"},
        ng_bins={"7", "9"},
        review_bins={"2"},
        machine_type="ESEC",
    )
    row = result.rows[0]
    assert row.decision == DECISION_NOMINAL_NOT_GOOD
    assert row.action_no is None


def test_action_numbering_ordered_by_output_position():
    force_delete = _die(1, "1:0", "2:3")
    review = _die(2, "2:0", "1:4")
    substrate = _substrate([force_delete, review])
    result = analyze_substrate(
        substrate,
        _wafer_map(),
        wafer_ring=WAFER_RING,
        offset=make_offset("X", 1),
        good_bins={"1"},
        ng_bins={"7", "9"},
        review_bins={"2"},
        machine_type="ESEC",
    )
    by_index = {r.source_die.index: r for r in result.rows}
    assert by_index[2].output_xy == (0, 0)
    assert by_index[1].output_xy == (1, 0)
    assert by_index[2].action_no == 1
    assert by_index[1].action_no == 2


def test_wrong_wafer_ring_is_excluded_not_classified():
    matching = _die(1, "0:0", "1:1", wafer_ring=WAFER_RING)
    other_wafer = _die(2, "1:0", "2:3", wafer_ring="SOME_OTHER_WAFER")
    substrate = _substrate([matching, other_wafer])
    result = analyze_substrate(
        substrate,
        _wafer_map(),
        wafer_ring=WAFER_RING,
        offset=make_offset("X", 1),
        good_bins={"1"},
        ng_bins={"7", "9"},
        review_bins={"2"},
        machine_type="ESEC",
    )
    assert len(result.rows) == 1
    assert result.rows[0].source_die.index == 1
    assert len(result.excluded) == 1
    assert result.excluded[0].index == 2


def test_wafer_ring_matching_is_case_and_whitespace_insensitive():
    # Matches the reference tool's own comparison
    # (String(r.strateWaferId||'').trim().toUpperCase()), not a stricter
    # exact match.
    die = _die(1, "0:0", "1:1", wafer_ring="  testwafer  ")
    substrate = _substrate([die])
    result = analyze_substrate(
        substrate,
        _wafer_map(),
        wafer_ring="TestWafer",
        offset=make_offset("X", 1),
        good_bins={"1"},
        ng_bins={"7", "9"},
        review_bins={"2"},
        machine_type="ESEC",
    )
    assert len(result.rows) == 1
    assert not result.excluded


def test_stacked_other_layer_is_processed_too():
    # The reference tool silently ignored OTHER_LAYER; this module doesn't.
    primary = _die(1, "0:0", "1:1")
    other = _die(1, "1:0", "2:3")  # same shape as the force-delete case above
    substrate = _substrate([primary], other_layer_die_info=[other])
    result = analyze_substrate(
        substrate,
        _wafer_map(),
        wafer_ring=WAFER_RING,
        offset=make_offset("X", 1),
        good_bins={"1"},
        ng_bins={"7", "9"},
        review_bins={"2"},
        machine_type="ESEC",
    )
    layers = {r.layer for r in result.rows}
    assert layers == {"primary", "other"}
    other_row = next(r for r in result.rows if r.layer == "other")
    assert other_row.decision == DECISION_FORCE_DELETE


def test_esec_rejects_notch_other_than_270():
    substrate = _substrate([_die(1, "0:0", "1:1")], notch="180")
    with pytest.raises(UnsupportedNotchError):
        analyze_substrate(
            substrate,
            _wafer_map(),
            wafer_ring=WAFER_RING,
            offset=make_offset("X", 1),
            good_bins={"1"},
            ng_bins={"7", "9"},
            review_bins={"2"},
            machine_type="ESEC",
        )


def test_rejects_block_count_that_does_not_divide_evenly():
    substrate = _substrate([_die(1, "0:0", "1:1")])
    substrate.substrate_block = 2  # 3 columns / 2 blocks doesn't divide evenly
    with pytest.raises(InvalidGeometryError):
        analyze_substrate(
            substrate,
            _wafer_map(),
            wafer_ring=WAFER_RING,
            offset=make_offset("X", 1),
            good_bins={"1"},
            ng_bins={"7", "9"},
            review_bins={"2"},
        )


def test_make_offset_allows_zero():
    # 2026/08/27更正：0代表T點沒有偏移的基準狀態，不再是錯誤輸入(見
    # make_offset()的docstring)。
    offset = make_offset("X", 0)
    assert offset.dx == 0
    assert offset.dy == 0
    offset_y = make_offset("Y", 0)
    assert offset_y.dx == 0
    assert offset_y.dy == 0


def test_make_offset_rejects_bad_axis():
    with pytest.raises(ValueError):
        make_offset("Z", 1)


def test_parse_bin_set_handles_separators_and_default():
    assert parse_bin_set("7,9") == {"7", "9"}
    assert parse_bin_set("7，9；2 8") == {"7", "9", "2", "8"}
    assert parse_bin_set("", default="1") == {"1"}
    assert parse_bin_set("  ") == set()


def test_col_name_spreadsheet_style():
    assert col_name(0) == "A"
    assert col_name(25) == "Z"
    assert col_name(26) == "AA"
    assert col_name(-1) == ""


def test_output_coord_combines_col_name_and_1_based_row():
    substrate = _substrate([_die(1, "1:0", "2:3")])
    result = analyze_substrate(
        substrate,
        _wafer_map(),
        wafer_ring=WAFER_RING,
        offset=make_offset("X", 1),
        good_bins={"1"},
        ng_bins={"7", "9"},
        review_bins={"2"},
        machine_type="ESEC",
    )
    row = result.rows[0]
    assert row.output_xy == (1, 0)
    assert output_coord(row) == "B1"


# --- DB coordinate math (machine_type="DB", the default — this project's
# real machine type, confirmed 2026/08/17 against a real DB case the user
# provided: wafer_xy is the wafer MAP's own raw coordinate directly, no
# X-flip/rotation at all — unlike ESEC above. See module docstring. ---


def test_db_is_the_default_machine_type():
    # Omitting machine_type entirely behaves exactly like machine_type="DB".
    substrate = _substrate([_die(1, "0:0", "1:2")], notch="180")  # nominal (1,2)="1" Good
    result = analyze_substrate(
        substrate,
        _wafer_map(),
        wafer_ring=WAFER_RING,
        offset=make_offset("X", 1),
        good_bins={"1"},
        ng_bins={"7", "9"},
        review_bins={"2"},
    )
    row = result.rows[0]
    assert row.nominal_map_xy == (1, 2)  # identity, no X-flip
    assert row.actual_map_xy == (2, 2)  # offset added directly, no machine-frame rotation
    assert row.decision == DECISION_FORCE_DELETE


def test_db_offset_lands_on_review_bin():
    substrate = _substrate([_die(1, "0:0", "2:3")], notch="180")  # nominal (2,3)="1" Good
    result = analyze_substrate(
        substrate,
        _wafer_map(),
        wafer_ring=WAFER_RING,
        offset=make_offset("X", 1),
        good_bins={"1"},
        ng_bins={"7", "9"},
        review_bins={"2"},
        machine_type="DB",
    )
    row = result.rows[0]
    assert row.actual_map_xy == (3, 3)
    assert row.decision == DECISION_REVIEW


def test_db_offset_lands_back_on_good_bin_is_ok():
    substrate = _substrate([_die(1, "0:0", "0:0")], notch="180")
    result = analyze_substrate(
        substrate,
        _wafer_map(),
        wafer_ring=WAFER_RING,
        offset=make_offset("X", 1),
        good_bins={"1"},
        ng_bins={"7", "9"},
        review_bins={"2"},
        machine_type="DB",
    )
    row = result.rows[0]
    assert row.decision == DECISION_OK
    assert row.action_no is None


def test_db_output_position_is_identity_not_flipped():
    # substrate_column=3: DB keeps tx as-is; ESEC would flip 0 -> 2.
    assert output_position(0, 0, substrate_column=3, machine_type="DB") == (0, 0)
    assert output_position(0, 0, substrate_column=3, machine_type="ESEC") == (2, 0)


def test_db_accepts_any_notch_unlike_esec():
    # The real DB sample the user provided had NOTCH=180 — DB has no
    # NOTCH restriction at all (unlike ESEC's NOTCH=270 lock).
    for notch in ("180", "270", "0", "90", ""):
        substrate = _substrate([_die(1, "0:0", "0:0")], notch=notch)
        result = analyze_substrate(
            substrate,
            _wafer_map(),
            wafer_ring=WAFER_RING,
            offset=make_offset("X", 1),
            good_bins={"1"},
            ng_bins={"7", "9"},
            review_bins={"2"},
            machine_type="DB",
        )
        assert len(result.rows) == 1


def test_unknown_machine_type_is_rejected():
    substrate = _substrate([_die(1, "0:0", "0:0")])
    with pytest.raises(UnknownMachineTypeError):
        analyze_substrate(
            substrate,
            _wafer_map(),
            wafer_ring=WAFER_RING,
            offset=make_offset("X", 1),
            good_bins={"1"},
            ng_bins={"7", "9"},
            review_bins={"2"},
            machine_type="CM700",
        )
