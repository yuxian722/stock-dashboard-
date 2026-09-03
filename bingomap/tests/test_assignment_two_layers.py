"""Tests for assign_two_layers() — the 疊層(一次上兩顆) assignment path.

Picks below are lifted from the same real 2-layer sample used in
test_strate_multi_layer.py (V32NVED / Z2571802826E), so this validates
that generate_blank() + assign_two_layers() together reproduce that real
file's structure, the same way test_assignment.py's
test_reproduces_real_sample_structure_end_to_end does for the single-layer
case.
"""
from datetime import datetime

from bingomap.assignment import DieCountMismatch, DiePick, assign_two_layers
from bingomap.blank_generator import generate_blank

BASE_KWARGS = dict(
    assy_lot="V32NVED",
    mapping_lot="DP1970111.00C",
    eqpid="BAA02",
    oper="2070",
    substrate_id="Z2571802826E",
    substrate_row=5,
    substrate_column=12,
    substrate_block=1,
    notch="270",
    ref="0,14",
)

# First 3 real rows of each section from the confirmed real file.
PRIMARY_ROWS = [  # f9=2 section
    ("0:0", "I4F247", "21:24"),
    ("0:1", "I4F247", "19:24"),
    ("0:2", "I4F247", "17:24"),
]
OTHER_ROWS = [  # f9=1 section, OTHER_LAYER
    ("0:0", "I4F247", "22:24"),
    ("0:1", "I4F247", "20:24"),
    ("0:2", "I4F247", "18:24"),
]


def _picks(rows):
    return [
        DiePick(sub_pos=pos, wafer_ring=ring, wafer_xy=xy)
        for pos, ring, xy in rows
    ]


def test_assign_two_layers_matches_real_sample_structure():
    blank = generate_blank(**BASE_KWARGS, convention="EPOXY")
    filled = assign_two_layers(
        blank,
        _picks(PRIMARY_ROWS),
        _picks(OTHER_ROWS),
        start_time=datetime(2026, 8, 12, 16, 15, 21),
        interval_seconds=3,
        expected_qty=3,
    )

    assert [d.sub_pos for d in filled.die_info] == ["0:0", "0:1", "0:2"]
    assert all(d.f9 == "2" for d in filled.die_info)
    assert [d.wafer_xy for d in filled.die_info] == ["21:24", "19:24", "17:24"]

    assert [d.sub_pos for d in filled.other_layer_die_info] == ["0:0", "0:1", "0:2"]
    assert all(d.f9 == "1" for d in filled.other_layer_die_info)
    assert [d.wafer_xy for d in filled.other_layer_die_info] == ["22:24", "20:24", "18:24"]

    assert filled.total_bond_die_qty == 3
    assert filled.good_die == 3


def test_assign_two_layers_writes_valid_two_section_file():
    blank = generate_blank(**BASE_KWARGS, convention="EPOXY")
    filled = assign_two_layers(
        blank, _picks(PRIMARY_ROWS), _picks(OTHER_ROWS),
        start_time=datetime(2026, 8, 12, 16, 15, 21), expected_qty=3,
    )
    text = filled.to_text()
    assert "[DIE_INFO_BEG]" in text
    assert "[DIE_INFO_OTHER_LAYER_BEG]" in text
    assert "[DIE_INFO_OTHER_LAYER_END]" in text
    # round-trips cleanly
    from bingomap.strate import StrateFile
    reparsed = StrateFile.parse(text)
    assert len(reparsed.other_layer_die_info) == 3


def test_assign_two_layers_checks_primary_count_independently():
    blank = generate_blank(**BASE_KWARGS, convention="EPOXY")
    try:
        assign_two_layers(
            blank, _picks(PRIMARY_ROWS[:2]), _picks(OTHER_ROWS),
            start_time=datetime(2026, 8, 12, 16, 15, 21), expected_qty=3,
        )
        assert False, "expected DieCountMismatch"
    except DieCountMismatch as exc:
        assert exc.expected == 3 and exc.actual == 2


def test_assign_two_layers_checks_other_count_independently():
    blank = generate_blank(**BASE_KWARGS, convention="EPOXY")
    try:
        assign_two_layers(
            blank, _picks(PRIMARY_ROWS), _picks(OTHER_ROWS[:1]),
            start_time=datetime(2026, 8, 12, 16, 15, 21), expected_qty=3,
        )
        assert False, "expected DieCountMismatch"
    except DieCountMismatch as exc:
        assert exc.expected == 3 and exc.actual == 1


def test_assign_two_layers_default_layer_labels():
    blank = generate_blank(**BASE_KWARGS, convention="EPOXY")
    filled = assign_two_layers(
        blank, _picks(PRIMARY_ROWS), _picks(OTHER_ROWS),
        start_time=datetime(2026, 8, 12, 16, 15, 21), expected_qty=3,
    )
    assert filled.die_info[0].f9 == "2"
    assert filled.other_layer_die_info[0].f9 == "1"
