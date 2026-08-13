import pytest

from bingomap.blank_generator import generate_blank

BASE_KWARGS = dict(
    assy_lot="V27NVJH",
    mapping_lot="S7MJS",
    eqpid="BAB12",
    oper="2070",
    substrate_id="Z281226C",
    substrate_row=4,
    substrate_column=20,
    substrate_block=2,
    notch="180",
    ref="-72,340",
)


def test_epoxy_convention_starts_at_0_0():
    blank = generate_blank(**BASE_KWARGS, convention="EPOXY")
    assert blank.die_info[0].sub_pos == "0:0"
    assert blank.die_info[1].sub_pos == "0:1"
    # column-major: after ROW=4 entries (0:0..0:3) the column advances
    assert blank.die_info[4].sub_pos == "1:0"


def test_loc_convention_starts_at_1_1():
    blank = generate_blank(**BASE_KWARGS, convention="LOC")
    assert blank.die_info[0].sub_pos == "1:1"
    assert blank.die_info[4].sub_pos == "2:1"


def test_full_grid_generated_with_default_bin_and_blank_coords():
    blank = generate_blank(**BASE_KWARGS, convention="EPOXY")
    assert len(blank.die_info) == 4 * 20
    assert blank.total_bond_die_qty == 80
    assert blank.good_die == 80
    for d in blank.die_info:
        assert d.wafer_ring == ""
        assert d.wafer_xy == ""
        assert d.bin == "1"
        assert d.timestamp == "0"
    # sequential 1-based index, matching the real file's numbering
    assert [d.index for d in blank.die_info] == list(range(1, 81))


def test_last_position_matches_row_column_bounds():
    blank = generate_blank(**BASE_KWARGS, convention="EPOXY")
    assert blank.die_info[-1].sub_pos == "19:3"


def test_rejects_non_positive_dimensions():
    with pytest.raises(ValueError):
        generate_blank(**{**BASE_KWARGS, "substrate_row": 0})


def test_rejects_unknown_convention():
    with pytest.raises(ValueError):
        generate_blank(**BASE_KWARGS, convention="BOGUS")
