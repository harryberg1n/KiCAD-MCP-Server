"""
Regression tests: replace_schematic_component must patch the placed symbol
block in place instead of delete + re-add.

Bug: the old implementation deleted the placed block and re-added the new
symbol via DynamicSymbolLoader.  That dropped `(mirror y)` (symbol flipped,
pins moved to the other side, attached wires detached — 3 "unconnected wire
endpoint" ERC warnings), regenerated the uuid / instances / dnp / in_bom
attributes from defaults, and re-emitted the block in a foreign formatting
style, producing huge unreviewable diffs.

Contract pinned here:
  * `_pin_numbers_from_symbol_def`  — parse pin numbers out of a lib symbol def
  * `_patch_placed_symbol_block`    — swap lib_id + sync (pin "N" (uuid …))
    entries; keep everything else (at / mirror / uuid / properties / instances)
    byte-identical
  * `replace_schematic_component`   — orchestrates surgically: one write, all
    unrelated file content byte-identical, refuses cleanly when the new symbol
    cannot be resolved (file untouched).
"""

import re
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands import schematic_batch as sb  # noqa: E402
from commands.schematic_batch import (  # noqa: E402
    SchematicBatchCommands,
    _patch_placed_symbol_block,
    _pin_numbers_from_symbol_def,
)

# KiCad-10 style placed symbol: mirrored 3-pin connector with wires on its pins
PLACED_J1_BLOCK = """\
\t(symbol
\t\t(lib_id "Connector_Generic:Conn_01x03")
\t\t(at 74.93 111.76 0)
\t\t(mirror y)
\t\t(unit 1)
\t\t(body_style 1)
\t\t(exclude_from_sim no)
\t\t(in_bom yes)
\t\t(on_board yes)
\t\t(in_pos_files yes)
\t\t(dnp no)
\t\t(uuid "d860e554-61e2-48d0-8f34-ce6e6ec1a49c")
\t\t(property "Reference" "J1"
\t\t\t(at 74.93 105.664 0)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(property "Value" "CTRL"
\t\t\t(at 74.93 116.84 0)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(property "Footprint" "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical"
\t\t\t(at 74.93 111.76 0)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t\thide
\t\t\t)
\t\t)
\t\t(pin "1"
\t\t\t(uuid "60653e60-94c7-493f-b031-a4027ec6cddc")
\t\t)
\t\t(pin "2"
\t\t\t(uuid "76edae87-c964-4acb-8e31-c8ecea5a821e")
\t\t)
\t\t(pin "3"
\t\t\t(uuid "5062fcd7-8a67-47b9-972c-d11f55becec6")
\t\t)
\t\t(instances
\t\t\t(project "mains"
\t\t\t\t(path "/48b33bd1-343c-4ad1-8abb-a7719557361a"
\t\t\t\t\t(reference "J1")
\t\t\t\t\t(unit 1)
\t\t\t\t)
\t\t\t)
\t\t)
\t)
"""

# Second placed symbol used to verify unrelated content is untouched
PLACED_R9_BLOCK = """\
\t(symbol
\t\t(lib_id "Device:R")
\t\t(at 10 10 0)
\t\t(unit 1)
\t\t(uuid "11111111-2222-3333-4444-555555555555")
\t\t(property "Reference" "R9"
\t\t\t(at 12 10 0)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(property "Value" "1k"
\t\t\t(at 12 12 0)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(pin "1"
\t\t\t(uuid "99999999-8888-7777-6666-555555555555")
\t\t)
\t\t(pin "2"
\t\t\t(uuid "99999999-8888-7777-6666-444444444444")
\t\t)
\t)
"""

# Minimal lib-symbol definition for the new 4-pin connector
CONN_01X04_DEF = """\
\t\t(symbol "Connector_Generic:Conn_01x04"
\t\t\t(pin_names
\t\t\t\t(offset 1.016) hide)
\t\t\t(property "Reference" "J"
\t\t\t\t(at 0 5.08 0)
\t\t\t)
\t\t\t(symbol "Conn_01x04_1_1"
\t\t\t\t(pin passive line
\t\t\t\t\t(at -5.08 5.08 0)
\t\t\t\t\t(length 3.81)
\t\t\t\t\t(name "Pin_1"
\t\t\t\t\t\t(effects (font (size 1.27 1.27)))
\t\t\t\t\t)
\t\t\t\t\t(number "1"
\t\t\t\t\t\t(effects (font (size 1.27 1.27)))
\t\t\t\t\t)
\t\t\t\t)
\t\t\t\t(pin passive line
\t\t\t\t\t(at -5.08 2.54 0)
\t\t\t\t\t(length 3.81)
\t\t\t\t\t(name "Pin_2"
\t\t\t\t\t\t(effects (font (size 1.27 1.27)))
\t\t\t\t\t)
\t\t\t\t\t(number "2"
\t\t\t\t\t\t(effects (font (size 1.27 1.27)))
\t\t\t\t\t)
\t\t\t\t)
\t\t\t\t(pin passive line
\t\t\t\t\t(at -5.08 0 0)
\t\t\t\t\t(length 3.81)
\t\t\t\t\t(name "Pin_3"
\t\t\t\t\t\t(effects (font (size 1.27 1.27)))
\t\t\t\t\t)
\t\t\t\t\t(number "3"
\t\t\t\t\t\t(effects (font (size 1.27 1.27)))
\t\t\t\t\t)
\t\t\t\t)
\t\t\t\t(pin passive line
\t\t\t\t\t(at -5.08 -2.54 0)
\t\t\t\t\t(length 3.81)
\t\t\t\t\t(name "Pin_4"
\t\t\t\t\t\t(effects (font (size 1.27 1.27)))
\t\t\t\t\t)
\t\t\t\t\t(number "4"
\t\t\t\t\t\t(effects (font (size 1.27 1.27)))
\t\t\t\t\t)
\t\t\t\t)
\t\t\t)
\t\t)
"""


def _make_schematic(tmp_path: Path) -> Path:
    sch = tmp_path / "t.kicad_sch"
    content = (
        "(kicad_sch\n"
        "\t(version 20260306)\n"
        '\t(generator "eeschema")\n'
        '\t(generator_version "10.0")\n'
        '\t(uuid "48b33bd1-343c-4ad1-8abb-a7719557361a")\n'
        '\t(paper "A4")\n'
        "\t(lib_symbols\n"
        "\t)\n" + PLACED_J1_BLOCK + PLACED_R9_BLOCK + "\t(sheet_instances\n"
        '\t\t(path "/"\n'
        '\t\t\t(page "1")\n'
        "\t\t)\n"
        "\t)\n"
        ")\n"
    )
    sch.write_bytes(content.encode("utf-8"))  # LF, no translation
    return sch


# ---------------------------------------------------------------------------
# Unit: _pin_numbers_from_symbol_def
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPinNumbersFromDef:
    def test_extracts_all_pin_numbers(self):
        assert _pin_numbers_from_symbol_def(CONN_01X04_DEF) == ["1", "2", "3", "4"]

    def test_no_pins(self):
        assert _pin_numbers_from_symbol_def('(symbol "X:Y" (property "Reference" "U"))') == []

    def test_deduplicates_multi_style_duplicates(self):
        # DeMorgan body styles repeat the same pin numbers — dedupe, keep order
        dup = CONN_01X04_DEF + CONN_01X04_DEF
        assert _pin_numbers_from_symbol_def(dup) == ["1", "2", "3", "4"]


# ---------------------------------------------------------------------------
# Unit: _patch_placed_symbol_block
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPatchPlacedSymbolBlock:
    def _patch(self, **kw):
        return _patch_placed_symbol_block(
            PLACED_J1_BLOCK.rstrip("\n"),
            "Connector_Generic:Conn_01x04",
            ["1", "2", "3", "4"],
            **kw,
        )

    def test_lib_id_swapped(self):
        out = self._patch()
        assert '(lib_id "Connector_Generic:Conn_01x04")' in out
        assert '(lib_id "Connector_Generic:Conn_01x03")' not in out

    def test_position_mirror_uuid_preserved(self):
        out = self._patch()
        assert "(at 74.93 111.76 0)" in out
        assert "(mirror y)" in out
        assert '(uuid "d860e554-61e2-48d0-8f34-ce6e6ec1a49c")' in out

    def test_properties_and_instances_preserved(self):
        out = self._patch()
        assert '(property "Value" "CTRL"' in out
        assert (
            '(property "Footprint" "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical"'
            in out
        )
        assert '(reference "J1")' in out
        assert '(project "mains"' in out

    def test_existing_pin_uuids_kept_and_new_pin_added(self):
        out = self._patch()
        # pins 1-3 keep their uuids (wires stay associated / diffs minimal)
        assert '(uuid "60653e60-94c7-493f-b031-a4027ec6cddc")' in out
        assert '(uuid "76edae87-c964-4acb-8e31-c8ecea5a821e")' in out
        assert '(uuid "5062fcd7-8a67-47b9-972c-d11f55becec6")' in out
        # pin 4 added with some fresh uuid
        m = re.search(r'\(pin "4"\s*\(uuid "([0-9a-f-]{36})"\)', out)
        assert m, f'pin "4" entry missing in:\n{out}'

    def test_removed_pins_dropped(self):
        out = _patch_placed_symbol_block(
            PLACED_J1_BLOCK.rstrip("\n"),
            "Connector_Generic:Conn_01x02",
            ["1", "2"],
        )
        assert '(pin "3"' not in out
        assert '(uuid "5062fcd7-8a67-47b9-972c-d11f55becec6")' not in out
        assert '(pin "1"' in out and '(pin "2"' in out

    def test_rotation_override_patches_symbol_at_only(self):
        out = self._patch(new_rotation=90)
        assert "(at 74.93 111.76 90)" in out
        # property label positions untouched
        assert "(at 74.93 105.664 0)" in out
        assert "(at 74.93 116.84 0)" in out

    def test_everything_else_byte_identical(self):
        out = self._patch()
        # Strip the two intended changes; the rest must match the original
        norm_out = out.replace("Conn_01x04", "Conn_01x03")
        norm_out = re.sub(
            r'\n?\t*\(pin "4"\s*\n?\t*\(uuid "[0-9a-f-]{36}"\)\s*\n?\t*\)', "", norm_out
        )
        assert norm_out == PLACED_J1_BLOCK.rstrip("\n")


# ---------------------------------------------------------------------------
# Orchestration: replace_schematic_component end-to-end (loader stubbed)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReplaceSurgical:
    @pytest.fixture()
    def cmds(self, monkeypatch):
        # Stub the heavy loader: canned symbol def, lib_symbols injection no-op
        monkeypatch.setattr(
            sb.DynamicSymbolLoader,
            "extract_symbol_from_library",
            lambda self, lib, name: CONN_01X04_DEF if name == "Conn_01x04" else None,
        )
        monkeypatch.setattr(
            sb.DynamicSymbolLoader,
            "inject_symbol_into_schematic",
            lambda self, sch, lib, name: True,
        )
        # Pin-position reporting is not under test
        monkeypatch.setattr(
            sb.PinLocator, "get_all_symbol_pins", lambda self, sch, ref: {}, raising=False
        )
        monkeypatch.setattr(
            sb.PinLocator, "get_symbol_pins", lambda self, sch, sym: {}, raising=False
        )
        return SchematicBatchCommands(types.SimpleNamespace())

    def _replace(self, cmds, sch, new_symbol="Connector_Generic:Conn_01x04", **kw):
        return cmds.replace_schematic_component(
            {
                "schematicPath": str(sch),
                "reference": "J1",
                "newSymbol": new_symbol,
                **kw,
            }
        )

    def test_success_and_mirror_preserved(self, cmds, tmp_path):
        sch = _make_schematic(tmp_path)
        r = self._replace(cmds, sch)
        assert r["success"], r
        content = sch.read_text(encoding="utf-8")
        block = re.search(
            r'\(symbol\s+\(lib_id "Connector_Generic:Conn_01x04"\).*?\(instances.*?\n\t\)',
            content,
            re.S,
        )
        assert block, "replaced block not found"
        assert "(mirror y)" in block.group(0)
        assert "(at 74.93 111.76 0)" in block.group(0)
        assert '(uuid "d860e554-61e2-48d0-8f34-ce6e6ec1a49c")' in block.group(0)

    def test_unrelated_content_byte_identical(self, cmds, tmp_path):
        sch = _make_schematic(tmp_path)
        before = sch.read_bytes()
        r = self._replace(cmds, sch)
        assert r["success"], r
        after = sch.read_bytes()
        assert b"\r\n" not in after, "replace changed line endings"
        # R9 block and sheet_instances untouched
        assert PLACED_R9_BLOCK.encode() in after
        assert b"(sheet_instances" in after
        # Reverting the two intended changes must reproduce the input byte-for-byte:
        # swap the lib_id back and drop the added pin-4 uuid entry.
        norm = after.decode().replace("Conn_01x04", "Conn_01x03")
        norm = re.sub(r'\n\t*\(pin "4"\n\t*\(uuid "[0-9a-f-]{36}"\)\n\t*\)', "", norm)
        assert norm == before.decode(), "unrelated content changed"

    def test_refuses_unknown_symbol_and_leaves_file_untouched(self, cmds, tmp_path):
        sch = _make_schematic(tmp_path)
        before = sch.read_bytes()
        r = self._replace(cmds, sch, new_symbol="Connector_Generic:DoesNotExist")
        assert not r["success"]
        assert "DoesNotExist" in r["message"] or "not" in r["message"].lower()
        assert sch.read_bytes() == before, "file must be untouched on refusal"

    def test_wired_pins_keep_uuid_entries(self, cmds, tmp_path):
        sch = _make_schematic(tmp_path)
        r = self._replace(cmds, sch)
        assert r["success"], r
        content = sch.read_text(encoding="utf-8")
        assert '(uuid "60653e60-94c7-493f-b031-a4027ec6cddc")' in content
        assert re.search(r'\(pin "4"', content)
