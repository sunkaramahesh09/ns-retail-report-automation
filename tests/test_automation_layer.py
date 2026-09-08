"""Automation layer checks.

The macOS tests confirm that the Windows-only code is properly isolated and
fails with an understandable message.  The tests marked ``windows`` need a real
Windows desktop and are skipped everywhere else.
"""

from __future__ import annotations

import sys
from datetime import date

import pytest

from ns_retail_automation.automation import get_backend
from ns_retail_automation.automation.base import UnsupportedBackend
from ns_retail_automation.automation.ns_retail import NSRetailAutomation
from ns_retail_automation.automation.selectors import Selectors, build_selectors
from ns_retail_automation.errors import (
    ApplicationNotFoundError,
    SelectorNotConfiguredError,
    UnsupportedPlatformError,
)

on_windows = sys.platform == "win32"


class TestBackendSelection:
    @pytest.mark.skipif(on_windows, reason="checks the non-Windows fallback")
    def test_non_windows_gets_the_unsupported_backend(self):
        backend = get_backend()
        assert isinstance(backend, UnsupportedBackend)
        assert backend.is_supported is False

    @pytest.mark.skipif(on_windows, reason="checks the non-Windows fallback")
    def test_every_action_explains_why_it_cannot_run(self):
        backend = get_backend()
        with pytest.raises(UnsupportedPlatformError) as excinfo:
            backend.list_windows()
        assert "Windows" in excinfo.value.message

    def test_the_windows_module_imports_everywhere(self):
        # It must be importable on macOS so the code can be read and reviewed;
        # pywinauto is only imported when a method actually runs.
        from ns_retail_automation.automation import windows

        assert windows.WindowsBackend(ui_backend="uia").name == "windows"


class TestReadiness:
    def test_unmapped_project_reports_every_missing_step(self, settings):
        automation = NSRetailAutomation(settings, Selectors(), get_backend())
        missing = automation.missing_steps()
        assert "open_reports" in missing
        assert "export_to" in missing
        assert automation.missing_windows() == ["main", "report_viewer", "save_dialog"]

    def test_login_step_is_only_required_when_login_is_enabled(self, make_settings):
        settings = make_settings(login={"enabled": True, "credential_source": "env"})
        automation = NSRetailAutomation(settings, Selectors(), get_backend())
        assert "login" in automation.missing_steps()
        assert "login" in automation.missing_windows()

    def test_preflight_names_the_missing_pieces(self, settings):
        from ns_retail_automation.errors import AutomationError

        automation = NSRetailAutomation(settings, Selectors(), get_backend())
        with pytest.raises(AutomationError) as excinfo:
            automation.preflight()
        # On macOS the platform check fires first; on Windows the selector check.
        reported = f"{excinfo.value.message} {excinfo.value.hint or ''}"
        assert "Windows" in reported or "mapped" in reported

    def test_a_fully_mapped_selector_file_reports_nothing_missing(self, settings):
        selectors = build_selectors(
            {
                "windows": {
                    "main": {"title_re": "Main"},
                    "report_viewer": {"title_re": "Viewer"},
                    "save_dialog": {"title_re": "Save"},
                },
                "steps": {
                    name: [{"action": "invoke", "auto_id": f"id_{name}"}]
                    for name in (
                        "open_reports",
                        "open_stock_reports",
                        "select_purchase_report",
                        "set_date",
                        "search",
                        "generate_report",
                        "export_to",
                        "choose_csv_format",
                        "confirm_export",
                        "save_set_path",
                        "save_confirm",
                    )
                },
            }
        )
        automation = NSRetailAutomation(settings, selectors, get_backend())
        assert automation.missing_steps() == []
        assert automation.missing_windows() == []


class TestLaunchRules:
    def test_launch_without_an_executable_path_is_explained(self, make_settings):
        settings = make_settings(application={"executable_path": "", "process_name": ""})
        automation = NSRetailAutomation(settings, Selectors(), get_backend())
        with pytest.raises(ApplicationNotFoundError) as excinfo:
            automation.launch()
        assert "executable_path" in (excinfo.value.hint or "")


class TestSelectorPlaceholders:
    def test_a_date_placeholder_is_filled_in(self, settings):
        from ns_retail_automation.automation.ns_retail import _date_context, _resolve_value
        from ns_retail_automation.automation.selectors import UiTarget

        target = UiTarget(action="set_text", auto_id="dtFrom", value="{date_dd_mm_yyyy}")
        resolved = _resolve_value(target, _date_context(date(2026, 9, 8)), step_name="set_date")
        assert resolved.value == "08-09-2026"

    def test_an_unknown_placeholder_is_reported(self, settings):
        from ns_retail_automation.automation.ns_retail import _resolve_value
        from ns_retail_automation.automation.selectors import UiTarget

        target = UiTarget(action="set_text", auto_id="dtFrom", value="{nope}")
        with pytest.raises(SelectorNotConfiguredError, match="unknown placeholder"):
            _resolve_value(target, {"date_iso": "2026-09-08"}, step_name="set_date")


@pytest.mark.windows
@pytest.mark.skipif(not on_windows, reason="needs a real Windows desktop")
class TestOnWindows:
    """Smoke tests for the Windows backend - they do not need NS Retail."""

    def test_backend_is_available(self):
        backend = get_backend()
        assert backend.is_supported, "install the packages in requirements.txt"

    def test_top_level_windows_can_be_listed(self):
        assert isinstance(get_backend().list_windows(), list)

    def test_processes_can_be_enumerated(self):
        from ns_retail_automation.automation.windows import iter_processes

        names = {p.name.lower() for p in iter_processes()}
        assert "explorer.exe" in names
