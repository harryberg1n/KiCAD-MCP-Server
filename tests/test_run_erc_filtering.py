"""
Tests for run_erc output filtering (T2 in the token-cost feedback report).

run_erc previously returned every violation verbatim (~30 mostly-benign
warnings per call on a real board).  The handler now supports:
  * minSeverity  — "info" (default, everything) | "warning" | "error"
  * excludeTypes — list of violation type slugs to drop (e.g.
                   ["lib_symbol_mismatch", "endpoint_off_grid"])
  * maxViolations — cap the returned list (0 = unlimited)

The summary always reports FULL pre-filter counts plus how many entries the
filter removed, so nothing is silently hidden.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.schematic_handlers import _filter_erc_violations  # noqa: E402

VIOLATIONS = [
    {"type": "pin_not_connected", "severity": "error", "message": "e1", "location": {}},
    {"type": "lib_symbol_mismatch", "severity": "warning", "message": "w1", "location": {}},
    {"type": "lib_symbol_mismatch", "severity": "warning", "message": "w2", "location": {}},
    {"type": "endpoint_off_grid", "severity": "warning", "message": "w3", "location": {}},
    {"type": "unconnected_wire", "severity": "error", "message": "e2", "location": {}},
    {"type": "note_thing", "severity": "info", "message": "i1", "location": {}},
]


@pytest.mark.unit
class TestFilterErcViolations:
    def test_default_returns_everything(self):
        kept, removed = _filter_erc_violations(VIOLATIONS, "info", [], 0)
        assert kept == VIOLATIONS
        assert removed == 0

    def test_min_severity_warning_drops_info(self):
        kept, removed = _filter_erc_violations(VIOLATIONS, "warning", [], 0)
        assert all(v["severity"] in ("warning", "error") for v in kept)
        assert removed == 1

    def test_min_severity_error_keeps_only_errors(self):
        kept, removed = _filter_erc_violations(VIOLATIONS, "error", [], 0)
        assert [v["message"] for v in kept] == ["e1", "e2"]
        assert removed == 4

    def test_exclude_types(self):
        kept, removed = _filter_erc_violations(
            VIOLATIONS, "info", ["lib_symbol_mismatch", "endpoint_off_grid"], 0
        )
        assert all(v["type"] not in ("lib_symbol_mismatch", "endpoint_off_grid") for v in kept)
        assert removed == 3

    def test_max_violations_caps_list(self):
        kept, removed = _filter_erc_violations(VIOLATIONS, "info", [], 2)
        assert len(kept) == 2
        assert removed == 4

    def test_filters_compose(self):
        kept, removed = _filter_erc_violations(VIOLATIONS, "warning", ["lib_symbol_mismatch"], 1)
        assert len(kept) == 1
        assert kept[0]["severity"] in ("warning", "error")
        assert kept[0]["type"] != "lib_symbol_mismatch"
        assert removed == len(VIOLATIONS) - 1

    def test_unknown_min_severity_means_no_severity_filter(self):
        kept, removed = _filter_erc_violations(VIOLATIONS, "bogus", [], 0)
        assert kept == VIOLATIONS and removed == 0
