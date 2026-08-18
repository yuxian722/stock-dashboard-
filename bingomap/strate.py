"""Read/write .strate substrate-map files (SUBSTRATE MAP format used by EAS/BINGO MAP).

File layout (verified byte-for-byte against a real single-layer sample):
- CRLF line endings throughout — `to_text()` always writes this
- 16 header `KEY=VALUE` lines
- `[DIE_INFO_BEG]` / `[DIE_INFO_END]` bracketing one CSV line per die
- two trailing blank lines after the last section

`parse()` itself accepts either CRLF or bare LF line endings (normalizing
before splitting) even though real files are always CRLF — a browser
`<textarea>` silently normalizes CRLF to LF when its `.value` is read back
(the webapp's "貼上檔案內容"/複製既有.strate為範本 path goes through one),
so a strict CRLF-only parser rejects perfectly valid pasted content with a
misleading "Missing [DIE_INFO_BEG] marker" error that has nothing to do
with the file actually being malformed. Confirmed live: setting a
textarea's `.value` to a CRLF string and reading `.value` back yields LF
only. Output is unaffected — to_text() is untouched, still always CRLF.

Each DIE_INFO line has 9 comma-separated fields:
    index, wafer_ring, wafer_xy, sub_pos, bin, f6, f7, timestamp, f9

wafer_xy and sub_pos are themselves "A:B" pairs (wafer pickup X:Y, and
substrate column:row placement respectively). f9 is the stack layer number
(see below) — not a constant, despite every sample we first saw having "1"
there.

Stacked dies ("一次上兩顆" — the bonder picks up and places more than one
die per cycle, at different z-layers on the same substrate site): a second
section appears right after `[DIE_INFO_END]`, bracketed by
`[DIE_INFO_OTHER_LAYER_BEG]` / `[DIE_INFO_OTHER_LAYER_END]`, holding the
same substrate positions again but for the other layer — its rows' f9
differs from the first section's (e.g. first section all "2", other-layer
section all "1"). Confirmed against a real 2-layer sample (55 dies each
section, both matching header TOTAL_BOND_DIE_QTY). Only the first section
was confirmed with a complete real file top-to-bottom byte-for-byte; the
other-layer section's structure (BEG/END markers, per-row shape) is
confirmed from real captured rows but not a fully transcribed complete
file, so treat it as verified-but-not-exhaustively-fuzzed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

HEADER_FIELDS = [
    ("ASSY_LOT", "assy_lot"),
    ("MAPPING_LOT", "mapping_lot"),
    ("EQPID", "eqpid"),
    ("OPER", "oper"),
    ("SUBSTRATE_ID", "substrate_id"),
    ("SUBSTRATE_ROW", "substrate_row"),
    ("SUBSTRATE_COLUMN", "substrate_column"),
    ("SUBSTRATE_BLOCK", "substrate_block"),
    ("OUT_MGZ_SLOT_NO", "out_mgz_slot_no"),
    ("TOTAL_BOND_DIE_QTY", "total_bond_die_qty"),
    ("GOOD_DIE", "good_die"),
    ("RUN_TIME", "run_time"),
    ("NOTCH", "notch"),
    ("Ref", "ref"),
    ("T2_POINT", "t2_point"),
    ("T2_Flat", "t2_flat"),
]

DIE_INFO_BEG = "[DIE_INFO_BEG]"
DIE_INFO_END = "[DIE_INFO_END]"
DIE_INFO_OTHER_LAYER_BEG = "[DIE_INFO_OTHER_LAYER_BEG]"
DIE_INFO_OTHER_LAYER_END = "[DIE_INFO_OTHER_LAYER_END]"


class StrateFormatError(ValueError):
    """Raised when a .strate file/line does not match the expected format."""


@dataclass
class DieInfo:
    index: int
    wafer_ring: str = ""
    wafer_xy: str = ""
    sub_pos: str = ""
    bin: str = "1"
    f6: str = "0"
    f7: str = "0"
    timestamp: str = "0"
    f9: str = "1"

    def to_line(self) -> str:
        return ",".join(
            [
                str(self.index),
                self.wafer_ring,
                self.wafer_xy,
                self.sub_pos,
                self.bin,
                self.f6,
                self.f7,
                self.timestamp,
                self.f9,
            ]
        )

    @classmethod
    def from_line(cls, line: str) -> "DieInfo":
        parts = line.split(",")
        if len(parts) != 9:
            raise StrateFormatError(
                f"DIE_INFO line must have 9 comma-separated fields, got {len(parts)}: {line!r}"
            )
        idx, wafer_ring, wafer_xy, sub_pos, bin_, f6, f7, ts, f9 = parts
        try:
            index = int(idx)
        except ValueError as exc:
            raise StrateFormatError(f"DIE_INFO index is not an integer: {line!r}") from exc
        return cls(index, wafer_ring, wafer_xy, sub_pos, bin_, f6, f7, ts, f9)


@dataclass
class StrateFile:
    assy_lot: str
    mapping_lot: str
    eqpid: str
    oper: str
    substrate_id: str
    substrate_row: int
    substrate_column: int
    substrate_block: int
    out_mgz_slot_no: str = ""
    total_bond_die_qty: int = 0
    good_die: int = 0
    run_time: str = ""
    notch: str = ""
    ref: str = ""
    t2_point: str = "NA"
    t2_flat: str = "NA"
    die_info: list[DieInfo] = field(default_factory=list)
    other_layer_die_info: list[DieInfo] = field(default_factory=list)
    """Second stacked layer's DIE_INFO rows, if this substrate has one
    (see module docstring). Empty by default — a plain single-layer file
    emits no [DIE_INFO_OTHER_LAYER_*] section at all, matching the
    originally-verified single-layer sample byte-for-byte."""

    def filename(self, timestamp: str) -> str:
        """站別_批號_基板流水號碼_時間.strate"""
        return f"{self.oper}_{self.assy_lot}_{self.substrate_id}_{timestamp}.strate"

    def to_text(self) -> str:
        lines: list[str] = []
        for key, attr in HEADER_FIELDS:
            lines.append(f"{key}={getattr(self, attr)}")
        lines.append(DIE_INFO_BEG)
        lines.extend(d.to_line() for d in self.die_info)
        lines.append(DIE_INFO_END)
        if self.other_layer_die_info:
            lines.append(DIE_INFO_OTHER_LAYER_BEG)
            lines.extend(d.to_line() for d in self.other_layer_die_info)
            lines.append(DIE_INFO_OTHER_LAYER_END)
        lines.append("")
        lines.append("")
        return "".join(line + "\r\n" for line in lines)

    @classmethod
    def parse(cls, text: str) -> "StrateFile":
        # Accept bare LF too — see module docstring for why (textarea
        # value normalization strips the \r before it ever reaches here).
        # A no-op for genuinely CRLF input: replacing "\r\n" with "\n"
        # then splitting on "\n" yields the exact same list a straight
        # split("\r\n") would.
        lines = text.replace("\r\n", "\n").split("\n")
        header: dict[str, str] = {}
        i = 0
        while i < len(lines) and lines[i] != DIE_INFO_BEG:
            line = lines[i]
            if line:
                if "=" not in line:
                    raise StrateFormatError(f"Malformed header line (no '='): {line!r}")
                k, _, v = line.partition("=")
                header[k] = v
            i += 1
        if i >= len(lines):
            raise StrateFormatError(f"Missing {DIE_INFO_BEG} marker")
        i += 1  # skip DIE_INFO_BEG

        die_info: list[DieInfo] = []
        while i < len(lines) and lines[i] != DIE_INFO_END:
            die_info.append(DieInfo.from_line(lines[i]))
            i += 1
        if i >= len(lines):
            raise StrateFormatError(f"Missing {DIE_INFO_END} marker")
        i += 1  # skip DIE_INFO_END

        other_layer_die_info: list[DieInfo] = []
        if i < len(lines) and lines[i] == DIE_INFO_OTHER_LAYER_BEG:
            i += 1  # skip DIE_INFO_OTHER_LAYER_BEG
            while i < len(lines) and lines[i] != DIE_INFO_OTHER_LAYER_END:
                other_layer_die_info.append(DieInfo.from_line(lines[i]))
                i += 1
            if i >= len(lines):
                raise StrateFormatError(f"Missing {DIE_INFO_OTHER_LAYER_END} marker")

        missing = [key for key, _ in HEADER_FIELDS if key not in header]
        if missing:
            raise StrateFormatError(f"Missing header field(s): {', '.join(missing)}")

        kwargs = {}
        for key, attr in HEADER_FIELDS:
            value = header[key]
            if attr in ("substrate_row", "substrate_column", "substrate_block", "total_bond_die_qty", "good_die"):
                try:
                    value = int(value)
                except ValueError as exc:
                    raise StrateFormatError(f"{key} must be an integer, got {value!r}") from exc
            kwargs[attr] = value

        return cls(die_info=die_info, other_layer_die_info=other_layer_die_info, **kwargs)
