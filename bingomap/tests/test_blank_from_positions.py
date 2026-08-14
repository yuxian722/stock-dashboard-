from pathlib import Path

from bingomap.assignment import DiePick, assign_dies
from bingomap.blank_generator import blank_from_positions
from bingomap.strate import StrateFile

FIXTURE = Path(__file__).parent / "fixtures" / "2070_V27NVJH_Z281226C_20260812221959.strate"

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


def test_builds_die_info_in_the_exact_given_order():
    blank = blank_from_positions(**BASE_KWARGS, positions=["5:2", "0:0", "3:1"])
    assert [d.sub_pos for d in blank.die_info] == ["5:2", "0:0", "3:1"]
    assert [d.index for d in blank.die_info] == [1, 2, 3]
    assert blank.total_bond_die_qty == 3
    assert blank.good_die == 3


def test_positions_field_not_read_from_convention_or_machine_type():
    # blank_from_positions has no convention/machine_type knobs at all —
    # whatever order the caller passes in is exactly what comes out. This
    # is the point: template mode must not re-derive ordering.
    blank = blank_from_positions(**BASE_KWARGS, positions=["19:3", "0:0"])
    assert [d.sub_pos for d in blank.die_info] == ["19:3", "0:0"]


def test_template_round_trip_preserves_positions_and_picks_from_real_sample():
    # The core promise of "複製既有.strate為範本": parse a real file, rebuild
    # a blank from its own DIE_INFO position order (not from
    # convention/machine_type), and refill it with the exact same picks —
    # every field should come back identical except timestamps (assign_dies
    # always paces those out at a fixed interval; the real sample's
    # intervals are not perfectly uniform, which is a pre-existing,
    # separately-documented simplification, not something this test is
    # about).
    from datetime import datetime

    original_bytes = FIXTURE.read_bytes()
    original = StrateFile.parse(original_bytes.decode("ascii"))

    positions = [d.sub_pos for d in original.die_info]
    blank = blank_from_positions(
        assy_lot=original.assy_lot,
        mapping_lot=original.mapping_lot,
        eqpid=original.eqpid,
        oper=original.oper,
        substrate_id=original.substrate_id,
        substrate_row=original.substrate_row,
        substrate_column=original.substrate_column,
        substrate_block=original.substrate_block,
        notch=original.notch,
        ref=original.ref,
        positions=positions,
    )
    assert [d.sub_pos for d in blank.die_info] == positions

    picks = [
        DiePick(sub_pos=d.sub_pos, wafer_ring=d.wafer_ring, wafer_xy=d.wafer_xy, bin=d.bin)
        for d in original.die_info
    ]
    rebuilt = assign_dies(
        blank,
        picks,
        start_time=datetime.strptime(original.die_info[0].timestamp, "%Y%m%d%H%M%S"),
        expected_qty=len(picks),
    )

    assert len(rebuilt.die_info) == len(original.die_info)
    for rebuilt_die, original_die in zip(rebuilt.die_info, original.die_info):
        assert rebuilt_die.sub_pos == original_die.sub_pos
        assert rebuilt_die.wafer_ring == original_die.wafer_ring
        assert rebuilt_die.wafer_xy == original_die.wafer_xy
        assert rebuilt_die.bin == original_die.bin
    # start_time carries through exactly for the first entry regardless of
    # interval pacing.
    assert rebuilt.die_info[0].timestamp == original.die_info[0].timestamp
    assert rebuilt.total_bond_die_qty == original.total_bond_die_qty
