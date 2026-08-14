"""Tests for the [DIE_INFO_OTHER_LAYER_*] second section ("一次上兩顆" —
the bonder stacks a second die per substrate site in the same cycle).

The synthetic fixture below is NOT a full real file — the real 2-layer
sample we confirmed this structure against (V32NVED / Z2571802826E,
2026-08-14) was captured across several photos with some middle rows
never transcribed, so building a byte-exact fixture from it would risk
baking in a transcription error. What IS taken verbatim from that real
file: the header field values, the closing-tag pair, and a handful of
real DIE_INFO rows from both sections (first and last of each, confirmed
from unambiguous screenshots) — assembled into a smaller but structurally
faithful 3-row-per-section example.
"""
from bingomap.strate import DieInfo, StrateFile

# Real header values, real closing tags, real first/last rows of each
# section — trimmed to 3 rows per section rather than the real 55.
TWO_LAYER_SAMPLE = (
    "ASSY_LOT=V32NVED\r\n"
    "MAPPING_LOT=DP1970111.00C\r\n"
    "EQPID=BAA02\r\n"
    "OPER=2070\r\n"
    "SUBSTRATE_ID=Z2571802826E\r\n"
    "SUBSTRATE_ROW=5\r\n"
    "SUBSTRATE_COLUMN=12\r\n"
    "SUBSTRATE_BLOCK=1\r\n"
    "OUT_MGZ_SLOT_NO=\r\n"
    "TOTAL_BOND_DIE_QTY=3\r\n"
    "GOOD_DIE=3\r\n"
    "RUN_TIME=\r\n"
    "NOTCH=270\r\n"
    "Ref=0,14\r\n"
    "T2_POINT=NA\r\n"
    "T2_Flat=NA\r\n"
    "[DIE_INFO_BEG]\r\n"
    "1,I4F247,21:24,0:0,1,0,0,20260812161523,2\r\n"
    "2,I4F247,19:24,0:1,1,0,0,20260812161526,2\r\n"
    "3,I4F247,17:24,0:2,1,0,0,20260812161529,2\r\n"
    "[DIE_INFO_END]\r\n"
    "[DIE_INFO_OTHER_LAYER_BEG]\r\n"
    "1,I4F247,22:24,0:0,1,0,0,20260812161521,1\r\n"
    "2,I4F247,20:24,0:1,1,0,0,20260812161524,1\r\n"
    "3,I4F247,18:24,0:2,1,0,0,20260812161528,1\r\n"
    "[DIE_INFO_OTHER_LAYER_END]\r\n"
    "\r\n"
    "\r\n"
)


def test_parses_both_sections():
    parsed = StrateFile.parse(TWO_LAYER_SAMPLE)
    assert len(parsed.die_info) == 3
    assert len(parsed.other_layer_die_info) == 3
    assert all(d.f9 == "2" for d in parsed.die_info)
    assert all(d.f9 == "1" for d in parsed.other_layer_die_info)
    # same substrate positions, different wafer sites/layer per SOP explanation
    assert [d.sub_pos for d in parsed.die_info] == [d.sub_pos for d in parsed.other_layer_die_info]
    assert parsed.die_info[0].wafer_xy != parsed.other_layer_die_info[0].wafer_xy


def test_round_trips_byte_for_byte():
    parsed = StrateFile.parse(TWO_LAYER_SAMPLE)
    assert parsed.to_text() == TWO_LAYER_SAMPLE


def test_single_layer_file_emits_no_other_layer_section():
    # Regression guard: adding other_layer support must not change output
    # for the plain single-layer case verified earlier against a real file.
    strate = StrateFile(
        assy_lot="X",
        mapping_lot="Y",
        eqpid="E",
        oper="2070",
        substrate_id="S",
        substrate_row=1,
        substrate_column=1,
        substrate_block=1,
        die_info=[DieInfo(index=1, sub_pos="0:0")],
    )
    text = strate.to_text()
    assert "OTHER_LAYER" not in text
    assert StrateFile.parse(text).other_layer_die_info == []
