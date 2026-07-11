"""
Regression tests: batch_connect's "power nets without PWR_FLAG" warning must
not fire when a PWR_FLAG exists elsewhere on the net.

Bug: `_pwr_flag_warnings` mapped flags to nets only by coordinate coincidence
with pins placed IN THE CURRENT CALL (0.5 mm). A PWR_FLAG connected to the
same net via a wire, or placed in an earlier call at a different point, was
invisible — the warning fired even though the flag exists (false positive,
wasted verify round-trips).

Fix contract: when the quick coincidence check leaves candidate nets, resolve
every PWR_FLAG's real net via the interface's wire-tracing pad→net map
(`_build_hierarchical_pad_net_map`) before warning.  Net names are compared
with any leading "/" (sheet-scope prefix) stripped.
"""

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.schematic_batch import SchematicBatchCommands  # noqa: E402


class _StubLocator:
    """PinLocator stand-in: no coincident pins anywhere (quick path finds nothing)."""

    def get_pin_location(self, sch_path, ref, pin):
        return None

    def get_all_symbol_pins(self, sch_path, ref):
        return {}


def _cmds_with_map(pad_net_map):
    iface = types.SimpleNamespace(
        _build_hierarchical_pad_net_map=lambda p: (pad_net_map, set(pad_net_map.values()))
    )
    return SchematicBatchCommands(iface)


def _placed(net):
    return [{"componentRef": "J9", "pin": "1", "net": net, "position": {"x": 10.0, "y": 10.0}}]


@pytest.mark.unit
class TestPwrFlagTracedResolution:
    def test_flag_elsewhere_on_net_suppresses_warning(self, tmp_path):
        sch = tmp_path / "t.kicad_sch"
        sch.write_text("(kicad_sch)")
        cmds = _cmds_with_map({("#FLG01", "1"): "+12V"})
        warnings = cmds._pwr_flag_warnings(sch, _StubLocator(), _placed("+12V"))
        assert warnings == [], f"false positive: {warnings}"

    def test_warning_kept_when_flag_truly_missing(self, tmp_path):
        sch = tmp_path / "t.kicad_sch"
        sch.write_text("(kicad_sch)")
        cmds = _cmds_with_map({("#FLG01", "1"): "GND"})  # flag on a different net
        warnings = cmds._pwr_flag_warnings(sch, _StubLocator(), _placed("+12V"))
        assert len(warnings) == 1
        assert "+12V" in warnings[0]

    def test_sheet_prefix_normalized(self, tmp_path):
        sch = tmp_path / "t.kicad_sch"
        sch.write_text("(kicad_sch)")
        cmds = _cmds_with_map({("#FLG01", "1"): "/+12V"})  # traced name carries "/"
        warnings = cmds._pwr_flag_warnings(sch, _StubLocator(), _placed("+12V"))
        assert warnings == []

    def test_non_power_nets_never_traced_or_warned(self, tmp_path):
        sch = tmp_path / "t.kicad_sch"
        sch.write_text("(kicad_sch)")

        def _boom(p):
            raise AssertionError("tracing must not run for non-power nets")

        cmds = SchematicBatchCommands(types.SimpleNamespace(_build_hierarchical_pad_net_map=_boom))
        warnings = cmds._pwr_flag_warnings(sch, _StubLocator(), _placed("CTRL_FB"))
        assert warnings == []

    def test_tracing_failure_falls_back_to_warning(self, tmp_path):
        sch = tmp_path / "t.kicad_sch"
        sch.write_text("(kicad_sch)")

        def _boom(p):
            raise RuntimeError("skip parse failed")

        cmds = SchematicBatchCommands(types.SimpleNamespace(_build_hierarchical_pad_net_map=_boom))
        warnings = cmds._pwr_flag_warnings(sch, _StubLocator(), _placed("+12V"))
        assert len(warnings) == 1  # conservative: warn rather than stay silent
