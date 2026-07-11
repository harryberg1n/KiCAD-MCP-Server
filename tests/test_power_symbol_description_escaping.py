"""
Regression tests: placing a symbol whose library Description contains escaped
quotes (every ``power:*`` symbol) must not corrupt the schematic.

Bug: ``_extract_lib_property_value`` used ``"([^"]*)"`` which stops at the
backslash of an escaped quote, returning a value with a trailing ``\\``.
``_property`` then interpolated it raw, emitting ``"...name \\"`` — the ``\\"``
escapes the closing quote and the string silently swallows the following
s-expressions (pins, the next symbol), leaving the file unparseable by
kicad-cli.  PWR_FLAG was the only "safe" power symbol because its description
has no quotes.
"""

import sys
from pathlib import Path

import pytest
import sexpdata

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.dynamic_symbol_loader import DynamicSymbolLoader  # noqa: E402

# Mirrors the real power:GND definition — Description contains escaped quotes.
GND_DESCRIPTION_LOGICAL = 'Power symbol creates a global label with name "GND" , ground'

POWER_GND_DEF = """\
\t\t(symbol "power:GND"
\t\t\t(power)
\t\t\t(pin_names
\t\t\t\t(offset 0)
\t\t\t)
\t\t\t(property "Reference" "#PWR"
\t\t\t\t(at 0 -6.35 0)
\t\t\t\t(effects (font (size 1.27 1.27)) hide)
\t\t\t)
\t\t\t(property "Value" "GND"
\t\t\t\t(at 0 -3.81 0)
\t\t\t\t(effects (font (size 1.27 1.27)))
\t\t\t)
\t\t\t(property "Footprint" ""
\t\t\t\t(at 0 0 0)
\t\t\t\t(effects (font (size 1.27 1.27)) hide)
\t\t\t)
\t\t\t(property "Datasheet" ""
\t\t\t\t(at 0 0 0)
\t\t\t\t(effects (font (size 1.27 1.27)) hide)
\t\t\t)
\t\t\t(property "Description" "Power symbol creates a global label with name \\"GND\\" , ground"
\t\t\t\t(at 0 0 0)
\t\t\t\t(effects (font (size 1.27 1.27)) hide)
\t\t\t)
\t\t\t(symbol "GND_0_1"
\t\t\t\t(polyline
\t\t\t\t\t(pts (xy 0 0) (xy 0 -1.27))
\t\t\t\t\t(stroke (width 0) (type default))
\t\t\t\t\t(fill (type none))
\t\t\t\t)
\t\t\t)
\t\t\t(symbol "GND_1_1"
\t\t\t\t(pin power_in line
\t\t\t\t\t(at 0 0 270)
\t\t\t\t\t(length 0)
\t\t\t\t\t(name "GND"
\t\t\t\t\t\t(effects (font (size 1.27 1.27)))
\t\t\t\t\t)
\t\t\t\t\t(number "1"
\t\t\t\t\t\t(effects (font (size 1.27 1.27)))
\t\t\t\t\t)
\t\t\t\t)
\t\t\t)
\t\t)
"""


def _make_schematic_with_gnd_def(tmp_path: Path) -> Path:
    sch = tmp_path / "t.kicad_sch"
    content = (
        "(kicad_sch\n"
        "\t(version 20260306)\n"
        '\t(generator "eeschema")\n'
        '\t(generator_version "10.0")\n'
        '\t(uuid "48b33bd1-343c-4ad1-8abb-a7719557361a")\n'
        '\t(paper "A4")\n'
        "\t(lib_symbols\n" + POWER_GND_DEF + "\t)\n"
        "\t(sheet_instances\n"
        '\t\t(path "/"\n'
        '\t\t\t(page "1")\n'
        "\t\t)\n"
        "\t)\n"
        ")\n"
    )
    sch.write_bytes(content.encode("utf-8"))
    return sch


@pytest.mark.unit
class TestExtractLibPropertyValue:
    def test_full_value_with_escaped_quotes(self, tmp_path):
        sch = _make_schematic_with_gnd_def(tmp_path)
        loader = DynamicSymbolLoader(project_path=tmp_path)
        val = loader._extract_lib_property_value(sch, "power", "GND", "Description")
        assert val == GND_DESCRIPTION_LOGICAL

    def test_plain_value_unchanged(self, tmp_path):
        sch = _make_schematic_with_gnd_def(tmp_path)
        loader = DynamicSymbolLoader(project_path=tmp_path)
        assert loader._extract_lib_property_value(sch, "power", "GND", "Value") == "GND"


@pytest.mark.unit
class TestPowerSymbolPlacement:
    def test_placed_gnd_keeps_file_parseable(self, tmp_path):
        sch = _make_schematic_with_gnd_def(tmp_path)
        loader = DynamicSymbolLoader(project_path=tmp_path)
        ok = loader.create_component_instance(
            sch, "power", "GND", reference="#PWR01", value="GND", x=100, y=100
        )
        assert ok
        content = sch.read_text(encoding="utf-8")
        # The file must remain a valid s-expression — the truncated-Description
        # bug swallowed everything after the corrupt property string.
        sexpdata.loads(content)

    def test_placed_gnd_description_complete_and_escaped(self, tmp_path):
        sch = _make_schematic_with_gnd_def(tmp_path)
        loader = DynamicSymbolLoader(project_path=tmp_path)
        assert loader.create_component_instance(
            sch, "power", "GND", reference="#PWR01", value="GND", x=100, y=100
        )
        content = sch.read_text(encoding="utf-8")
        # Placed instance carries the FULL description, quotes escaped in-file.
        assert content.count('name \\"GND\\"') >= 2  # lib def + placed instance
        assert not content.rstrip().endswith('\\"')

    def test_pin_and_instances_survive_after_description(self, tmp_path):
        # The corruption ate the s-expr content following the property; make
        # sure the placed block still has its pin uuid entry.
        sch = _make_schematic_with_gnd_def(tmp_path)
        loader = DynamicSymbolLoader(project_path=tmp_path)
        assert loader.create_component_instance(
            sch, "power", "GND", reference="#PWR01", value="GND", x=100, y=100
        )
        content = sch.read_text(encoding="utf-8")
        placed = content.rindex('(lib_id "power:GND")')
        assert '(pin "1"' in content[placed:], "placed block lost its pin entry"


@pytest.mark.unit
class TestPropertyValueEscaping:
    def test_user_value_with_quotes_is_escaped(self, tmp_path):
        # Any caller-supplied value containing quotes must be escaped on emit.
        sch = _make_schematic_with_gnd_def(tmp_path)
        loader = DynamicSymbolLoader(project_path=tmp_path)
        assert loader.create_component_instance(
            sch, "power", "GND", reference="#PWR01", value='G"N"D', x=100, y=100
        )
        sexpdata.loads(sch.read_text(encoding="utf-8"))
