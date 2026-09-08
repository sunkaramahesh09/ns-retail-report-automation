from __future__ import annotations

import json

import pytest

from ns_retail_automation.automation.selectors import (
    Selectors,
    build_selectors,
    load_selectors,
)
from ns_retail_automation.errors import ConfigError, SelectorNotConfiguredError


class TestEmptyState:
    def test_no_file_means_nothing_is_mapped(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        selectors = load_selectors()
        assert selectors.source_path is None
        assert selectors.has_step("open_reports") is False

    def test_the_shipped_template_is_deliberately_unmapped(self):
        selectors = load_selectors("config/selectors.example.json")
        assert selectors.has_window("main") is False
        assert selectors.missing_steps(["open_reports", "search"]) == ["open_reports", "search"]

    def test_asking_for_an_unmapped_step_explains_what_to_do(self):
        with pytest.raises(SelectorNotConfiguredError) as excinfo:
            Selectors().step("open_reports")
        assert "inspect" in (excinfo.value.hint or "")

    def test_asking_for_an_unmapped_window_explains_what_to_do(self):
        with pytest.raises(SelectorNotConfiguredError) as excinfo:
            Selectors().window("main")
        assert "selectors.json" in (excinfo.value.hint or "")


class TestParsing:
    def test_a_mapped_step_is_usable(self):
        selectors = build_selectors(
            {
                "windows": {"main": {"title_re": "Some App.*"}},
                "steps": {
                    "open_reports": {
                        "window": "main",
                        "targets": [
                            {"action": "invoke", "title": "Reports", "control_type": "MenuItem"}
                        ],
                    }
                },
            }
        )
        assert selectors.has_window("main")
        step = selectors.step("open_reports")
        assert step.targets[0].search_criteria() == {
            "title": "Reports",
            "control_type": "MenuItem",
        }

    def test_a_bare_list_of_targets_is_accepted(self):
        selectors = build_selectors({"steps": {"search": [{"auto_id": "btnSearch"}]}})
        assert selectors.step("search").targets[0].auto_id == "btnSearch"

    def test_underscore_keys_are_comments(self):
        selectors = build_selectors(
            {"steps": {"_comment": "ignore me", "search": [{"auto_id": "x"}]}}
        )
        assert list(selectors.steps) == ["search"]

    def test_target_without_criteria_is_rejected(self):
        with pytest.raises(ConfigError, match="no search criteria"):
            build_selectors({"steps": {"search": [{"action": "click"}]}})

    def test_unknown_action_is_rejected(self):
        with pytest.raises(ConfigError, match="not supported"):
            build_selectors({"steps": {"search": [{"action": "dance", "auto_id": "x"}]}})

    def test_set_text_without_a_value_is_rejected(self):
        with pytest.raises(ConfigError, match="needs a 'value'"):
            build_selectors({"steps": {"set_date": [{"action": "set_text", "auto_id": "d"}]}})

    def test_unknown_field_is_rejected_with_the_allowed_list(self):
        with pytest.raises(ConfigError, match="unknown field"):
            build_selectors({"steps": {"search": [{"auto_id": "x", "colour": "blue"}]}})

    def test_broken_json_is_reported(self, tmp_path):
        path = tmp_path / "selectors.json"
        path.write_text("{oops}", encoding="utf-8")
        with pytest.raises(ConfigError, match="not valid JSON"):
            load_selectors(path)

    def test_round_trip_through_a_file(self, tmp_path):
        path = tmp_path / "selectors.json"
        path.write_text(
            json.dumps(
                {
                    "windows": {"report_viewer": {"title_re": "Report Viewer"}},
                    "steps": {"export_to": [{"action": "invoke", "title": "Export To"}]},
                }
            ),
            encoding="utf-8",
        )
        selectors = load_selectors(path)
        assert selectors.window("report_viewer").title_re == "Report Viewer"
        assert selectors.step("export_to").targets[0].title == "Export To"
