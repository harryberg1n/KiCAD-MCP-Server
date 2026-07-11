"""
Regression tests: schematic writes must preserve the file's newline style.

Bug: on Windows, text-mode writes (open(path, "w") / Path.write_text) translate
"\n" to "\r\n" (os.linesep).  KiCad writes LF-only files on every platform, so a
one-field edit rewrote EVERY line of the .kicad_sch — git diffs showed
whole-file rewrites (7596 insertions / 7596 deletions for a 1-line change) and
edits became unreviewable.

These tests pin the contract for utils.sch_io.write_sch_text and for the
user-visible edit paths: after any schematic mutation, the file's original EOL
style (LF or CRLF) is preserved byte-for-byte, and a one-field edit changes
exactly one line.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

TEMPLATE_SCH = Path(__file__).parent.parent / "python" / "templates" / "empty.kicad_sch"

PLACED_RESISTOR_BLOCK = """\
  (symbol (lib_id "Device:R") (at 50 50 0) (unit 1)
    (in_bom yes) (on_board yes) (dnp no)
    (uuid "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    (property "Reference" "R1" (at 51.27 47.46 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Value" "10k" (at 51.27 52.54 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Footprint" "Resistor_SMD:R_0603_1608Metric" (at 50 50 0)
      (effects (font (size 1.27 1.27)) hide)
    )
    (property "Datasheet" "~" (at 50 50 0)
      (effects (font (size 1.27 1.27)) hide)
    )
  )
"""


def _schematic_text() -> str:
    """Template with one placed resistor, LF newlines, as a str."""
    src = TEMPLATE_SCH.read_text(encoding="utf-8").replace("\r\n", "\n").rstrip()
    assert src.endswith(")")
    return src[:-1] + "\n" + PLACED_RESISTOR_BLOCK + ")\n"


def _write_fixture(path: Path, eol: str) -> bytes:
    """Write the fixture schematic with an explicit EOL style; return its bytes."""
    data = _schematic_text().replace("\n", eol).encode("utf-8")
    path.write_bytes(data)
    return data


@pytest.fixture()
def iface():
    from kicad_interface import KiCADInterface

    return KiCADInterface()


# ---------------------------------------------------------------------------
# Unit tests for the EOL-preserving writer
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWriteSchText:
    def test_lf_file_stays_lf(self, tmp_path):
        from utils.sch_io import write_sch_text

        p = tmp_path / "a.kicad_sch"
        p.write_bytes(b"(kicad_sch\n\t(version 1)\n)\n")
        write_sch_text(p, "(kicad_sch\n\t(version 2)\n)\n")
        data = p.read_bytes()
        assert b"\r" not in data
        assert data == b"(kicad_sch\n\t(version 2)\n)\n"

    def test_crlf_file_stays_crlf(self, tmp_path):
        from utils.sch_io import write_sch_text

        p = tmp_path / "a.kicad_sch"
        p.write_bytes(b"(kicad_sch\r\n\t(version 1)\r\n)\r\n")
        write_sch_text(p, "(kicad_sch\n\t(version 2)\n)\n")
        assert p.read_bytes() == b"(kicad_sch\r\n\t(version 2)\r\n)\r\n"

    def test_new_file_defaults_to_lf(self, tmp_path):
        from utils.sch_io import write_sch_text

        p = tmp_path / "new.kicad_sch"
        write_sch_text(p, "(kicad_sch\n)\n")
        assert p.read_bytes() == b"(kicad_sch\n)\n"

    def test_content_with_crlf_is_normalised_before_eol_applied(self, tmp_path):
        # Callers may hand us content that already contains CRLF (e.g. spliced
        # from a CRLF file read without newline translation) — never double-convert.
        from utils.sch_io import write_sch_text

        p = tmp_path / "a.kicad_sch"
        p.write_bytes(b"(a\n)\n")
        write_sch_text(p, "(a\r\n)\r\n")
        assert p.read_bytes() == b"(a\n)\n"


# ---------------------------------------------------------------------------
# End-to-end: edit_schematic_component must not rewrite the whole file
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEditPreservesEol:
    def _edit_value(self, iface, sch: Path) -> None:
        result = iface._handle_edit_schematic_component(
            {"schematicPath": str(sch), "reference": "R1", "value": "99k"}
        )
        assert result.get("success"), result

    def test_edit_value_on_lf_file_keeps_lf(self, iface, tmp_path):
        sch = tmp_path / "t.kicad_sch"
        _write_fixture(sch, "\n")
        self._edit_value(iface, sch)
        data = sch.read_bytes()
        assert b'"99k"' in data
        assert b"\r\n" not in data, "LF schematic was rewritten with CRLF line endings"

    def test_edit_value_on_crlf_file_keeps_crlf(self, iface, tmp_path):
        sch = tmp_path / "t.kicad_sch"
        _write_fixture(sch, "\r\n")
        self._edit_value(iface, sch)
        data = sch.read_bytes()
        assert b'"99k"' in data
        assert b"\r\n" in data
        # no lone LF: removing all CRLF must leave no bare \n behind
        assert b"\n" not in data.replace(
            b"\r\n", b""
        ), "CRLF schematic was partially rewritten with LF line endings"

    def test_edit_value_changes_exactly_one_line(self, iface, tmp_path):
        sch = tmp_path / "t.kicad_sch"
        before = _write_fixture(sch, "\n").decode("utf-8").splitlines()
        self._edit_value(iface, sch)
        after = sch.read_bytes().decode("utf-8").splitlines()
        assert len(before) == len(after)
        changed = [(a, b) for a, b in zip(before, after) if a != b]
        assert len(changed) == 1, f"expected 1 changed line, got {len(changed)}: {changed[:5]}"
        assert '"99k"' in changed[0][1]

    def test_set_property_on_lf_file_keeps_lf(self, iface, tmp_path):
        sch = tmp_path / "t.kicad_sch"
        _write_fixture(sch, "\n")
        result = iface._handle_set_schematic_component_property(
            {"schematicPath": str(sch), "reference": "R1", "name": "MPN", "value": "RC0603"}
        )
        assert result.get("success"), result
        assert b"\r\n" not in sch.read_bytes()


# ---------------------------------------------------------------------------
# End-to-end: WireManager (used by batch_add_and_connect / add_schematic_wire)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWireManagerPreservesEol:
    def test_add_wire_on_lf_file_keeps_lf(self, tmp_path):
        from commands.wire_manager import WireManager

        sch = tmp_path / "t.kicad_sch"
        _write_fixture(sch, "\n")
        assert WireManager.add_wire(sch, [10, 10], [20, 10])
        data = sch.read_bytes()
        assert b"(wire" in data
        assert b"\r\n" not in data, "add_wire rewrote LF schematic with CRLF line endings"

    def test_add_label_on_lf_file_keeps_lf(self, tmp_path):
        from commands.wire_manager import WireManager

        sch = tmp_path / "t.kicad_sch"
        _write_fixture(sch, "\n")
        assert WireManager.add_label(sch, "NET1", [10, 10])
        data = sch.read_bytes()
        assert b"\r\n" not in data, "add_label rewrote LF schematic with CRLF line endings"
