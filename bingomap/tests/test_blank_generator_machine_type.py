"""machine_type ordering, verified against a real internal email
(2019/11/27) comparing a DB-machine .strate file against an ESEC 2100SD
one for the same product family — see bingomap/CLAUDE.md.
"""
from bingomap.blank_generator import generate_blank

# Real DB sample: 2130_M46ABC3_00549387_20191122033609.strate
DB_KWARGS = dict(
    assy_lot="M46ABC301",
    mapping_lot="69323J400",
    eqpid="BA721",
    oper="2130",
    substrate_id="00549387",
    substrate_row=6,
    substrate_column=28,
    substrate_block=1,
    notch="0",
    ref="-27,0",
)

# Real ESEC sample: 2130_M46ABC3_00554294_20191118085815.strate
ESEC_KWARGS = dict(
    assy_lot="M46ABC309",
    mapping_lot="69323J400",
    eqpid="BA721",
    oper="2130",
    substrate_id="00554294",
    substrate_row=6,
    substrate_column=28,
    substrate_block=1,
    notch="270",
    ref="1,1",
)


def test_db_positions_match_real_sample_prefix():
    blank = generate_blank(**DB_KWARGS, convention="EPOXY", machine_type="DB")
    positions = [d.sub_pos for d in blank.die_info]
    assert positions[:8] == ["0:0", "0:1", "0:2", "0:3", "0:4", "0:5", "1:0", "1:1"]


def test_esec_positions_match_real_sample_prefix():
    blank = generate_blank(**ESEC_KWARGS, convention="EPOXY", machine_type="ESEC")
    positions = [d.sub_pos for d in blank.die_info]
    # Real captured rows (bad/missing sites aside): 27:5,27:4,27:3,27:2,27:1,
    # 27:0, 26:0,26:1,26:2,26:3,26:4,26:5, 25:5 — last column descending,
    # next column ascending, next descending again.
    assert positions[:13] == [
        "27:5", "27:4", "27:3", "27:2", "27:1", "27:0",
        "26:0", "26:1", "26:2", "26:3", "26:4", "26:5",
        "25:5",
    ]


def test_esec_and_db_cover_the_same_position_set_just_different_order():
    db = generate_blank(**DB_KWARGS, convention="EPOXY", machine_type="DB")
    esec = generate_blank(**ESEC_KWARGS, convention="EPOXY", machine_type="ESEC")
    assert {d.sub_pos for d in db.die_info} == {d.sub_pos for d in esec.die_info}
    assert len(db.die_info) == len(esec.die_info) == 6 * 28


def test_esec_default_still_db_for_backward_compatibility():
    # machine_type defaults to "DB" — every earlier caller/test that never
    # passed machine_type must keep behaving exactly as before.
    blank = generate_blank(**DB_KWARGS, convention="EPOXY")
    assert blank.die_info[0].sub_pos == "0:0"


def test_rejects_unknown_machine_type():
    import pytest

    with pytest.raises(ValueError, match="machine_type"):
        generate_blank(**DB_KWARGS, machine_type="BOGUS")
