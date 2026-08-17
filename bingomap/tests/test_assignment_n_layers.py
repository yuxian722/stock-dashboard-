"""Tests for assign_layers() — the N-layer (一次上N顆, N possibly > 2)
generalization of assign_dies()/assign_two_layers(). Picks below are
lifted from the real 8-layer sample (V25NVDY / F2006908, 2026-08-17) used
in test_strate_eight_layer_real_sample.py, so this validates that
generate_blank() + assign_layers() together reproduce that real file's
DIE_INFO/OTHER_LAYER split — the same way test_assignment_two_layers.py
does for the 2-layer case.
"""
from datetime import datetime

from bingomap.assignment import DieCountMismatch, DiePick, assign_layers
from bingomap.blank_generator import generate_blank

BASE_KWARGS = dict(
    assy_lot="V25NVDY",
    mapping_lot="59C5621S",
    eqpid="BAB16",
    oper="2070",
    substrate_id="F2006908",
    substrate_row=5,
    substrate_column=19,
    substrate_block=1,
    notch="180",
    ref="-14,80",
)

POSITIONS = ["0:1", "0:2", "0:3", "0:4", "2:0", "2:1", "2:2"]

# All 8 layers' wafer_xy picks, in substrate-position order, transcribed
# from the real fixture (bingomap/tests/fixtures/2070_V25NVDY_...strate).
LAYER_WAFER_XY = [
    ["3:66", "15:66", "9:65", "12:64", "7:63", "14:62", "10:61"],  # layer 1
    ["8:66", "19:66", "8:65", "13:64", "4:62", "16:62", "9:61"],  # layer 2
    ["9:66", "15:65", "3:65", "15:64", "6:62", "18:62", "8:61"],  # layer 3
    ["10:66", "14:65", "7:64", "13:63", "8:62", "20:61", "7:61"],  # layer 4
    ["11:66", "13:65", "8:64", "11:63", "9:62", "16:61", "6:61"],  # layer 5
    ["12:66", "12:65", "9:64", "10:63", "10:62", "15:61", "1:61"],  # layer 6
    ["13:66", "11:65", "10:64", "9:63", "11:62", "12:61", "1:60"],  # layer 7
    ["14:66", "10:65", "11:64", "8:63", "12:62", "11:61", "7:60"],  # layer 8 (DIE_INFO)
]


def _layer_picks():
    return [
        [DiePick(sub_pos=pos, wafer_ring="B6844E", wafer_xy=xy) for pos, xy in zip(POSITIONS, layer_xy)]
        for layer_xy in LAYER_WAFER_XY
    ]


def test_assign_layers_reproduces_real_8layer_sample_structure():
    blank = generate_blank(**BASE_KWARGS, convention="EPOXY", machine_type="DB")
    filled = assign_layers(
        blank,
        _layer_picks(),
        start_time=datetime(2026, 7, 2, 20, 26, 40),
        expected_qty=7,
    )

    # DIE_INFO = only the last (8th) layer
    assert [d.sub_pos for d in filled.die_info] == POSITIONS
    assert all(d.f9 == "8" for d in filled.die_info)
    assert [d.wafer_xy for d in filled.die_info] == LAYER_WAFER_XY[7]

    # OTHER_LAYER = layers 1-7, grouped in ascending f9 blocks of 7
    assert len(filled.other_layer_die_info) == 49
    for layer_num in range(1, 8):
        block = filled.other_layer_die_info[(layer_num - 1) * 7 : layer_num * 7]
        assert all(d.f9 == str(layer_num) for d in block), layer_num
        assert [d.sub_pos for d in block] == POSITIONS, layer_num
        assert [d.wafer_xy for d in block] == LAYER_WAFER_XY[layer_num - 1], layer_num

    # continuous index across the whole OTHER_LAYER section
    assert [d.index for d in filled.other_layer_die_info] == list(range(1, 50))

    assert filled.total_bond_die_qty == 7
    assert filled.good_die == 7


def test_assign_layers_writes_a_valid_file_that_round_trips():
    blank = generate_blank(**BASE_KWARGS, convention="EPOXY", machine_type="DB")
    filled = assign_layers(
        blank, _layer_picks(), start_time=datetime(2026, 7, 2, 20, 26, 40), expected_qty=7,
    )
    text = filled.to_text()
    from bingomap.strate import StrateFile

    reparsed = StrateFile.parse(text)
    assert reparsed.die_info == filled.die_info
    assert reparsed.other_layer_die_info == filled.other_layer_die_info


def test_assign_layers_checks_every_layer_independently():
    blank = generate_blank(**BASE_KWARGS, convention="EPOXY", machine_type="DB")
    picks = _layer_picks()
    picks[3] = picks[3][:5]  # layer 4 short by 2
    try:
        assign_layers(blank, picks, start_time=datetime(2026, 7, 2, 20, 26, 40), expected_qty=7)
        assert False, "expected DieCountMismatch"
    except DieCountMismatch as exc:
        assert exc.expected == 7 and exc.actual == 5


def test_assign_layers_rejects_empty_layer_list():
    blank = generate_blank(**BASE_KWARGS, convention="EPOXY", machine_type="DB")
    try:
        assign_layers(blank, [], start_time=datetime(2026, 7, 2, 20, 26, 40))
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_assign_layers_with_a_single_layer_matches_assign_dies_shape():
    # N=1 degenerates to "no OTHER_LAYER section at all" — same as
    # assign_dies()'s plain single-layer output.
    blank = generate_blank(**BASE_KWARGS, convention="EPOXY", machine_type="DB")
    picks = _layer_picks()[:1]
    filled = assign_layers(blank, picks, start_time=datetime(2026, 7, 2, 20, 26, 40), expected_qty=7)
    assert filled.other_layer_die_info == []
    assert all(d.f9 == "1" for d in filled.die_info)
    assert "OTHER_LAYER" not in filled.to_text()
