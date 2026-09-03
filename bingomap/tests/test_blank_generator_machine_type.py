"""Substrate position walk order, verified against a real internal email
(2019/11/27) comparing a DB-machine .strate file against an ESEC 2100SD
one for the same product family — see bingomap/CLAUDE.md. ESEC support
itself was removed 2026/09/03 per the user's request (this project's only
real hardware is DB); this file keeps the DB half of that real-sample
verification.
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


def test_db_positions_match_real_sample_prefix():
    blank = generate_blank(**DB_KWARGS, convention="EPOXY")
    positions = [d.sub_pos for d in blank.die_info]
    assert positions[:8] == ["0:0", "0:1", "0:2", "0:3", "0:4", "0:5", "1:0", "1:1"]
    assert len(blank.die_info) == 6 * 28
