from datetime import datetime
from pathlib import Path

import pytest

from bingomap.assignment import DieCountMismatch, DiePick, assign_dies
from bingomap.blank_generator import generate_blank
from bingomap.strate import StrateFile

FIXTURE = Path(__file__).parent / "fixtures" / "2070_V27NVJH_Z281226C_20260812221959.strate"


def _read_fixture() -> str:
    with open(FIXTURE, encoding="ascii", newline="") as f:
        return f.read()


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


def test_reproduces_real_sample_structure_end_to_end():
    """blank_generator + assignment, fed the real file's own picks in its own
    order, must reproduce that file's DIE_INFO structurally (everything
    except the timestamps, which real hardware doesn't space evenly)."""
    real = StrateFile.parse(_read_fixture())
    blank = generate_blank(**BASE_KWARGS, convention="EPOXY")
    picks = [
        DiePick(sub_pos=d.sub_pos, wafer_ring=d.wafer_ring, wafer_xy=d.wafer_xy, bin=d.bin)
        for d in real.die_info
    ]

    filled = assign_dies(
        blank, picks, start_time=datetime(2026, 8, 12, 22, 16, 33), expected_qty=75
    )

    assert len(filled.die_info) == len(real.die_info) == 75
    assert filled.total_bond_die_qty == 75
    assert filled.good_die == 75
    for got, want in zip(filled.die_info, real.die_info):
        assert got.index == want.index
        assert got.sub_pos == want.sub_pos
        assert got.wafer_ring == want.wafer_ring
        assert got.wafer_xy == want.wafer_xy
        assert got.bin == want.bin


def test_unpicked_positions_are_dropped_and_survivors_renumbered():
    blank = generate_blank(**BASE_KWARGS, convention="EPOXY")
    picks = [
        DiePick(sub_pos="0:0", wafer_ring="W1", wafer_xy="1:1"),
        DiePick(sub_pos="1:0", wafer_ring="W1", wafer_xy="1:2"),
    ]
    filled = assign_dies(blank, picks, start_time=datetime(2026, 1, 1))
    assert [d.sub_pos for d in filled.die_info] == ["0:0", "1:0"]
    assert [d.index for d in filled.die_info] == [1, 2]
    assert filled.total_bond_die_qty == 2
    assert filled.good_die == 2


def test_timestamps_increment_by_interval():
    blank = generate_blank(**BASE_KWARGS, convention="EPOXY")
    picks = [
        DiePick(sub_pos="0:0", wafer_ring="W1", wafer_xy="1:1"),
        DiePick(sub_pos="0:1", wafer_ring="W1", wafer_xy="1:2"),
    ]
    filled = assign_dies(
        blank, picks, start_time=datetime(2026, 1, 1, 0, 0, 0), interval_seconds=5
    )
    assert filled.die_info[0].timestamp == "20260101000000"
    assert filled.die_info[1].timestamp == "20260101000005"


def test_quantity_mismatch_over_selection_matches_dialog_wording():
    big_blank = generate_blank(**{**BASE_KWARGS, "substrate_row": 20, "substrate_column": 20}, convention="EPOXY")
    picks = [DiePick(sub_pos=d.sub_pos, wafer_ring="W1", wafer_xy="0:0") for d in big_blank.die_info[:108]]
    with pytest.raises(DieCountMismatch) as exc_info:
        assign_dies(big_blank, picks, start_time=datetime(2026, 1, 1), expected_qty=80)
    assert "需要 Die 數量80" in str(exc_info.value)
    assert "已選擇數量108" in str(exc_info.value)
    assert "需減少28顆" in str(exc_info.value)


def test_quantity_mismatch_under_selection_matches_dialog_wording():
    # Verified against a live screenshot of the real dialog: undershooting
    # says "還需選擇N顆", not "需增加N顆".
    blank = generate_blank(**BASE_KWARGS, convention="EPOXY")
    with pytest.raises(DieCountMismatch) as exc_info:
        assign_dies(blank, [], start_time=datetime(2026, 1, 1), expected_qty=299)
    assert "需要 Die 數量299" in str(exc_info.value)
    assert "已選擇數量0" in str(exc_info.value)
    assert "還需選擇299顆" in str(exc_info.value)


def test_rejects_pick_at_invalid_substrate_position():
    blank = generate_blank(**BASE_KWARGS, convention="EPOXY")
    picks = [DiePick(sub_pos="99:99", wafer_ring="W1", wafer_xy="0:0")]
    with pytest.raises(ValueError, match="not a valid substrate position"):
        assign_dies(blank, picks, start_time=datetime(2026, 1, 1))


def test_rejects_duplicate_pick_for_same_position():
    blank = generate_blank(**BASE_KWARGS, convention="EPOXY")
    picks = [
        DiePick(sub_pos="0:0", wafer_ring="W1", wafer_xy="0:0"),
        DiePick(sub_pos="0:0", wafer_ring="W2", wafer_xy="0:1"),
    ]
    with pytest.raises(ValueError, match="duplicate pick"):
        assign_dies(blank, picks, start_time=datetime(2026, 1, 1))
