"""
Regression tests: schematic edits must not change (junction ...) entries at
nodes the edit did not touch.

Bug (bifrost/coildrive, 2026-07-12): WireManager.sync_junctions recomputed the
whole sheet's junction set from a "wire endpoints + pins >= 3" heuristic after
every wire/move/rotate op, deleting junctions it deemed redundant and adding
dots at untouched nodes.  The heuristic is wrong exactly where KiCad REQUIRES
a junction — a wire END on another wire's MIDDLE contributes only one endpoint
— so a move of an unrelated component silently dropped a T-node junction and
produced a real "pin not connected" ERC error.

Contract pinned here:
  * sync_junctions NEVER removes an existing junction — junctions are
    user/GUI data; an orphaned dot is harmless and the GUI cleans it up,
    a silently deleted one breaks connectivity.
  * additions only happen at explicitly passed candidate_points (the
    coordinates the current edit touched), never sheet-wide.
  * add_wire / delete_schematic_wire far away from a junction leave the
    junction set byte-identical; a property-only edit_schematic_component
    never touches junctions at all.
"""

import re
import sys
from pathlib import Path

import pytest
import sexpdata

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.wire_manager import WireManager  # noqa: E402

# Layout (all LF, sexpdata-parseable):
#   T-node: w2's END lands on w1's MIDDLE at (165.1, 81.28) -> junction J1
#           REQUIRED by KiCad, but only 1 wire endpoint lives there.
#   3-end node WITH junction J2 at (60, 60): w3/w4/w5 all end there.
#   3-end node WITHOUT junction at (80, 80): w6/w7/w8 end there — user data,
#           an unrelated edit must not "helpfully" add a dot.
FIXTURE = """\
(kicad_sch
\t(version 20260306)
\t(generator "eeschema")
\t(generator_version "10.0")
\t(uuid "11111111-2222-3333-4444-555555555555")
\t(paper "A4")
\t(lib_symbols)
\t(wire (pts (xy 165.1 60) (xy 165.1 100)) (stroke (width 0) (type default)) (uuid "w1"))
\t(wire (pts (xy 140 81.28) (xy 165.1 81.28)) (stroke (width 0) (type default)) (uuid "w2"))
\t(junction (at 165.1 81.28) (diameter 0) (color 0 0 0 0) (uuid "j1"))
\t(wire (pts (xy 40 60) (xy 60 60)) (stroke (width 0) (type default)) (uuid "w3"))
\t(wire (pts (xy 60 40) (xy 60 60)) (stroke (width 0) (type default)) (uuid "w4"))
\t(wire (pts (xy 60 60) (xy 60 80)) (stroke (width 0) (type default)) (uuid "w5"))
\t(junction (at 60 60) (diameter 0) (color 0 0 0 0) (uuid "j2"))
\t(wire (pts (xy 70 80) (xy 80 80)) (stroke (width 0) (type default)) (uuid "w6"))
\t(wire (pts (xy 80 70) (xy 80 80)) (stroke (width 0) (type default)) (uuid "w7"))
\t(wire (pts (xy 80 80) (xy 80 90)) (stroke (width 0) (type default)) (uuid "w8"))
\t(sheet_instances
\t\t(path "/"
\t\t\t(page "1")
\t\t)
\t)
)
"""

ORIGINAL_JUNCTIONS = {(165.1, 81.28), (60.0, 60.0)}


def _junction_set(text: str):
    return {
        (float(m.group(1)), float(m.group(2)))
        for m in re.finditer(r"\(junction\s*\(at ([\d\.\-]+) ([\d\.\-]+)\)", text)
    }


def _junction_set_from_data(sch_data):
    out = set()
    for item in sch_data:
        if isinstance(item, list) and item and item[0] == sexpdata.Symbol("junction"):
            for sub in item[1:]:
                if isinstance(sub, list) and sub and sub[0] == sexpdata.Symbol("at"):
                    out.add((float(sub[1]), float(sub[2])))
    return out


def _write_fixture(tmp_path: Path) -> Path:
    sch = tmp_path / "t.kicad_sch"
    sch.write_bytes(FIXTURE.encode("utf-8"))
    return sch


# ---------------------------------------------------------------------------
# Unit: sync_junctions contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSyncJunctionsContract:
    def test_never_removes_t_node_junction(self):
        # Only ONE wire endpoint lives at the T-node — the old heuristic
        # called that redundant and deleted a junction KiCad requires.
        sch_data = sexpdata.loads(FIXTURE)
        WireManager.sync_junctions(sch_data)
        assert (165.1, 81.28) in _junction_set_from_data(
            sch_data
        ), "sync_junctions removed a required T-node junction"

    def test_never_removes_any_existing_junction(self):
        sch_data = sexpdata.loads(FIXTURE)
        added, removed = WireManager.sync_junctions(sch_data)
        assert removed == 0
        assert ORIGINAL_JUNCTIONS <= _junction_set_from_data(sch_data)

    def test_no_sheet_wide_additions_without_candidates(self):
        # (80, 80) has 3 wire ends and no junction — user data. An edit that
        # did not touch that node must not add a dot there.
        sch_data = sexpdata.loads(FIXTURE)
        WireManager.sync_junctions(sch_data, candidate_points=[(10.0, 10.0)])
        assert (80.0, 80.0) not in _junction_set_from_data(
            sch_data
        ), "sync_junctions added a junction at a node the edit did not touch"

    def test_adds_at_touched_candidate_point(self):
        sch_data = sexpdata.loads(FIXTURE)
        added, removed = WireManager.sync_junctions(sch_data, candidate_points=[(80.0, 80.0)])
        assert added == 1 and removed == 0
        assert (80.0, 80.0) in _junction_set_from_data(sch_data)


# ---------------------------------------------------------------------------
# File-level: wire ops far away leave the junction set identical
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWireOpsPreserveJunctions:
    def test_add_wire_far_away_preserves_junction_set(self, tmp_path):
        sch = _write_fixture(tmp_path)
        assert WireManager.add_wire(sch, [10, 10], [20, 10])
        after = _junction_set(sch.read_text(encoding="utf-8"))
        assert after == ORIGINAL_JUNCTIONS, f"junction churn: {after ^ ORIGINAL_JUNCTIONS}"

    def test_delete_wire_far_away_preserves_junction_set(self, tmp_path):
        sch = _write_fixture(tmp_path)
        assert WireManager.add_wire(sch, [10, 10], [20, 10])
        assert WireManager.delete_wire(sch, [10, 10], [20, 10])
        after = _junction_set(sch.read_text(encoding="utf-8"))
        assert after == ORIGINAL_JUNCTIONS, f"junction churn: {after ^ ORIGINAL_JUNCTIONS}"

    def test_delete_wire_at_junction_leaves_dot_in_place(self, tmp_path):
        # Deleting a wire may orphan a junction — leave it; the GUI cleans up
        # harmlessly, silent deletion breaks connectivity elsewhere.
        sch = _write_fixture(tmp_path)
        assert WireManager.delete_wire(sch, [140, 81.28], [165.1, 81.28])
        after = _junction_set(sch.read_text(encoding="utf-8"))
        assert (165.1, 81.28) in after


# ---------------------------------------------------------------------------
# End-to-end: property-only edit never touches junctions (incident B shape)
# ---------------------------------------------------------------------------

PLACED_RESISTOR_BLOCK = """\
\t(symbol (lib_id "Device:R") (at 30 110 0) (unit 1)
\t\t(in_bom yes) (on_board yes) (dnp no)
\t\t(uuid "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
\t\t(property "Reference" "R1" (at 32 108 0)
\t\t\t(effects (font (size 1.27 1.27)))
\t\t)
\t\t(property "Value" "10k" (at 32 112 0)
\t\t\t(effects (font (size 1.27 1.27)))
\t\t)
\t\t(property "Footprint" "" (at 30 110 0)
\t\t\t(effects (font (size 1.27 1.27)) hide)
\t\t)
\t)
"""


@pytest.mark.unit
class TestPropertyEditPreservesJunctions:
    def test_property_and_footprint_edit_leaves_junction_lines_byte_identical(self, tmp_path):
        from kicad_interface import KiCADInterface

        sch = tmp_path / "t.kicad_sch"
        content = FIXTURE.rstrip()[:-1] + PLACED_RESISTOR_BLOCK + ")\n"
        sch.write_bytes(content.encode("utf-8"))
        before = [ln for ln in sch.read_text(encoding="utf-8").splitlines() if "(junction" in ln]

        iface = KiCADInterface()
        result = iface._handle_edit_schematic_component(
            {
                "schematicPath": str(sch),
                "reference": "R1",
                "value": "99k",
                "footprint": "Resistor_SMD:R_0603_1608Metric",
                "properties": {"MPN": "RC0603FR-0799KL"},
            }
        )
        assert result.get("success"), result

        after = [ln for ln in sch.read_text(encoding="utf-8").splitlines() if "(junction" in ln]
        assert before == after, "property-only edit changed junction lines"
