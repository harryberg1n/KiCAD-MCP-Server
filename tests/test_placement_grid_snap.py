"""
Tests for grid-snapped placement (G3) and pin electrical type in results (G8).

G3: placement previously wrote caller coordinates verbatim; anything off the
1.27 mm (50-mil) schematic grid produced pins that no wire can legally reach
and "off connection grid" ERC warnings.  batch_add_components (also the
placement stage of batch_add_and_connect) and add_schematic_component now
snap x/y to the 1.27 grid by default; pass snapToGrid: false to opt out.
The reported snapped_position always matched the snap — now the written file
matches it too.

G8: includePins pin dicts now carry the pin's electrical "type"
(passive / power_in / output ...) so callers don't need a second
get_schematic_pin_locations round-trip to learn polarity.
"""

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands import schematic_batch as sb  # noqa: E402
from commands.schematic_batch import SchematicBatchCommands  # noqa: E402


class _CaptureLoader:
    """DynamicSymbolLoader stand-in that records add_component coordinates."""

    calls: list = []

    def __init__(self, project_path=None):
        self.project_path = project_path

    def add_component(self, sch, library, name, **kw):
        _CaptureLoader.calls.append(kw)
        return True


class _StubLocator:
    def __init__(self):
        self._schematic_cache = {}

    def get_all_symbol_pins(self, sch, ref):
        return {"1": [50.8, 50.8], "2": [55.88, 50.8]}

    def get_symbol_pins(self, sch, lib_id):
        return {
            "1": {"name": "A", "type": "passive"},
            "2": {"name": "K", "type": "power_in"},
        }


@pytest.fixture()
def cmds(monkeypatch, tmp_path):
    _CaptureLoader.calls = []
    monkeypatch.setattr(sb, "DynamicSymbolLoader", _CaptureLoader)
    monkeypatch.setattr(sb, "PinLocator", _StubLocator)
    sch = tmp_path / "t.kicad_sch"
    sch.write_text("(kicad_sch (lib_symbols))\n")
    iface = types.SimpleNamespace(
        footprint_library=types.SimpleNamespace(find_footprint=lambda fp: object())
    )
    return SchematicBatchCommands(iface), sch


def _add(cmds_sch, x, y, **extra):
    cmds, sch = cmds_sch
    return cmds.batch_add_components(
        {
            "schematicPath": str(sch),
            "components": [
                {
                    "symbol": "Device:R",
                    "reference": "R1",
                    "position": {"x": x, "y": y},
                    **extra.pop("component", {}),
                }
            ],
            "auto_position_fields": False,
            **extra,
        }
    )


@pytest.mark.unit
class TestGridSnapOnPlacement:
    def test_off_grid_position_snapped_by_default(self, cmds):
        r = _add(cmds, 10.0, 11.0)
        assert r["success"], r
        kw = _CaptureLoader.calls[0]
        assert kw["x"] == pytest.approx(10.16)  # 8 * 1.27
        assert kw["y"] == pytest.approx(11.43)  # 9 * 1.27

    def test_on_grid_position_unchanged(self, cmds):
        _add(cmds, 12.7, 25.4)
        kw = _CaptureLoader.calls[0]
        assert kw["x"] == pytest.approx(12.7)
        assert kw["y"] == pytest.approx(25.4)

    def test_snap_to_grid_false_places_verbatim(self, cmds):
        _add(cmds, 10.0, 11.0, snapToGrid=False)
        kw = _CaptureLoader.calls[0]
        assert kw["x"] == pytest.approx(10.0)
        assert kw["y"] == pytest.approx(11.0)

    def test_snapped_position_report_matches_written(self, cmds):
        r = _add(cmds, 10.0, 11.0)
        kw = _CaptureLoader.calls[0]
        sp = (
            r["added"][0]["snapped_position"]
            if "added" in r
            else r["results"][0]["snapped_position"]
        )
        assert sp == {"x": pytest.approx(kw["x"]), "y": pytest.approx(kw["y"])}


@pytest.mark.unit
class TestPinTypeInResults:
    def test_include_pins_carries_electrical_type(self, cmds):
        r = _add(cmds, 12.7, 12.7, component={"includePins": True})
        assert r["success"], r
        entries = r.get("added") or r.get("results")
        pins = entries[0]["pins"]
        assert pins["1"]["type"] == "passive"
        assert pins["2"]["type"] == "power_in"
        assert pins["2"]["name"] == "K"
