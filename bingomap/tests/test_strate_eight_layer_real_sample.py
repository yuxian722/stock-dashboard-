"""Real 8-layer (一次上八顆) sample the user sent 2026-08-17, as a photo of
Notepad++ first (which is how the >2-layer OTHER_LAYER grouping-by-f9
structure was first spotted) and then as the actual file
(`2070_V25NVDY_F2006908_20260702203138.strate` in fixtures/, uploaded with
a `.txt` suffix appended for the upload path — content otherwise untouched).

What this file proves, that the earlier 2-layer sample
(test_strate_multi_layer.py) couldn't: `[DIE_INFO_OTHER_LAYER_BEG/END]`
is not "one more layer" — it holds *every* layer except the current one,
all in a single section, distinguished purely by each row's own f9 value.
Here [DIE_INFO_BEG] holds only f9="8" (7 rows, the just-completed top
layer), and [DIE_INFO_OTHER_LAYER_BEG] holds all of f9="1".."7" (49 rows,
grouped in blocks of 7 by ascending f9, each block repeating the same
7 substrate positions as [DIE_INFO_BEG] in the same order) — confirmed by
per-position timestamps: layer 1's pick at a given substrate position is
only ~3s before layer 2's pick at that *same* position, which is only ~3s
before layer 3's, etc. — i.e. real bonding order is one full 8-die stack
per site before moving to the next site, but the *file* reorders rows to
group by layer number instead of chronological/site order. Only the
DIE_INFO/OTHER_LAYER split and grouping matters for our own generation
logic (assign_layers() doesn't need to replicate real per-die bonding
chronology — see assignment.py's existing synthetic-timestamp approach,
already established for the 1- and 2-layer cases before this file existed).

Note: unlike the earlier real single/2-layer fixtures, the copy of this
file we received has no trailing blank lines after
[DIE_INFO_OTHER_LAYER_END] (uncertain whether the real file lacks them or
the upload path trimmed them) — so this test does not assert byte-exact
round-tripping the way test_strate_multi_layer.py does for its (partly
synthetic) sample. It asserts the part that's actually confirmed: parsed
structure, and that re-parsing our own to_text() output reproduces the
same die_info/other_layer_die_info data.
"""
from pathlib import Path

from bingomap.strate import StrateFile

FIXTURE = Path(__file__).parent / "fixtures" / "2070_V25NVDY_F2006908_20260702203138.strate"

# The 7 substrate positions, in blank-skeleton order — identical across
# [DIE_INFO_BEG] and every one of the 7 layer-groups inside
# [DIE_INFO_OTHER_LAYER_BEG].
EXPECTED_POSITIONS = ["0:1", "0:2", "0:3", "0:4", "2:0", "2:1", "2:2"]


def _parse_fixture() -> StrateFile:
    with open(FIXTURE, encoding="ascii", newline="") as f:
        return StrateFile.parse(f.read())


def test_header_fields():
    strate = _parse_fixture()
    assert strate.assy_lot == "V25NVDY"
    assert strate.substrate_id == "F2006908"
    assert strate.substrate_row == 5
    assert strate.substrate_column == 19
    assert strate.substrate_block == 1
    assert strate.total_bond_die_qty == 7
    assert strate.good_die == 7
    assert strate.notch == "180"


def test_die_info_is_only_the_current_topmost_layer():
    strate = _parse_fixture()
    assert len(strate.die_info) == 7
    assert all(d.f9 == "8" for d in strate.die_info)
    assert [d.sub_pos for d in strate.die_info] == EXPECTED_POSITIONS
    assert all(d.wafer_ring == "B6844E" for d in strate.die_info)
    assert all(d.bin == "1" for d in strate.die_info)
    # spot-check exact wafer coordinates (first and last row)
    assert strate.die_info[0].wafer_xy == "14:66"
    assert strate.die_info[-1].wafer_xy == "7:60"


def test_other_layer_holds_every_other_layer_grouped_by_f9():
    strate = _parse_fixture()
    assert len(strate.other_layer_die_info) == 49  # 7 layers x 7 positions

    # Grouped in 7 contiguous blocks of 7, ascending f9 1..7, each block
    # repeating the same substrate position order as DIE_INFO.
    for layer_num in range(1, 8):
        block = strate.other_layer_die_info[(layer_num - 1) * 7 : layer_num * 7]
        assert all(d.f9 == str(layer_num) for d in block), layer_num
        assert [d.sub_pos for d in block] == EXPECTED_POSITIONS, layer_num

    # index is renumbered continuously across the whole section (not
    # restarting at 1 for each layer block)
    assert [d.index for d in strate.other_layer_die_info] == list(range(1, 50))

    # spot-check exact wafer coordinates: layer 1's first pick, layer 7's
    # last pick
    assert strate.other_layer_die_info[0].wafer_xy == "3:66"
    assert strate.other_layer_die_info[0].f9 == "1"
    assert strate.other_layer_die_info[-1].wafer_xy == "1:60"
    assert strate.other_layer_die_info[-1].f9 == "7"


def test_same_substrate_position_gets_a_different_wafer_site_per_layer():
    strate = _parse_fixture()
    # substrate position "0:1" (first in the skeleton order) — one wafer
    # site per layer, all different, confirming each layer is an
    # independent pick rather than a repeat.
    sites_for_first_position = [strate.die_info[0].wafer_xy] + [
        d.wafer_xy for d in strate.other_layer_die_info if d.sub_pos == "0:1"
    ]
    assert len(sites_for_first_position) == 8
    assert len(set(sites_for_first_position)) == 8  # all distinct


def test_round_trips_the_parsed_data_through_to_text():
    strate = _parse_fixture()
    reparsed = StrateFile.parse(strate.to_text())
    assert reparsed.die_info == strate.die_info
    assert reparsed.other_layer_die_info == strate.other_layer_die_info
    assert reparsed.total_bond_die_qty == strate.total_bond_die_qty
