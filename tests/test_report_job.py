"""Orchestration tests for the report job.

These use a stand-in for the Windows automation so the ORDER of the workflow and
the safety rules around existing files can be tested on macOS.  They prove
nothing about NS Retail itself - that needs the Windows PC.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from ns_retail_automation.config.settings import build_settings
from ns_retail_automation.errors import AutomationError
from ns_retail_automation.reports.purchase_report import PurchaseReportJob

REPORT_DAY = date(2026, 9, 8)


class FakeAutomation:
    """Records the workflow calls and writes a file where the export would."""

    def __init__(self, *, csv_text: str = "Item,Qty\nRice,10\n") -> None:
        self.calls: list[str] = []
        self.csv_text = csv_text

    def _record(self, name):
        self.calls.append(name)

    def preflight(self): self._record("preflight")
    def missing_steps(self): return []
    def missing_windows(self): return []
    def close_report_screens(self): self._record("close_report_screens")
    def launch(self): self._record("launch")
    def connect(self): self._record("connect")
    def login(self): self._record("login")
    def open_reports(self): self._record("open_reports")
    def open_stock_reports(self): self._record("open_stock_reports")
    def select_purchase_report(self): self._record("select_purchase_report")
    def set_date(self, day): self._record(f"set_date:{day.isoformat()}")
    def search(self): self._record("search")
    def generate_report(self): self._record("generate_report")
    def close(self): self._record("close")

    def export_csv(self, destination):
        self._record(f"export_csv:{destination}")
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.csv_text, encoding="utf-8")
        return path


@pytest.fixture
def settings(tmp_path):
    return build_settings(
        {
            "storage": {"base_path": str(tmp_path / "REPORTS")},
            "logging": {"directory": str(tmp_path / "logs")},
        }
    )


def make_job(settings, automation=None, **kwargs) -> PurchaseReportJob:
    return PurchaseReportJob(settings, automation, **kwargs)


class TestPlanning:
    def test_plan_does_not_touch_the_filesystem(self, settings, tmp_path):
        plan = make_job(settings).plan(REPORT_DAY)
        assert plan.destination.filename == "08.09.2026.csv"
        assert not (tmp_path / "REPORTS").exists()

    def test_plan_describes_itself_for_the_dry_run(self, settings):
        lines = "\n".join(make_job(settings).plan(REPORT_DAY).describe())
        assert "08-09-2026" in lines
        assert "9.SEPTEMBER" in lines


class TestSuccessfulRun:
    def test_the_workflow_runs_in_the_documented_order(self, settings):
        automation = FakeAutomation()
        result = make_job(settings, automation).run(REPORT_DAY)
        assert result.success is True
        assert automation.calls[:10] == [
            "preflight",
            "launch",
            "connect",
            "login",
            "close_report_screens",
            "open_reports",
            "open_stock_reports",
            "select_purchase_report",
            "set_date:2026-09-08",
            "search",
        ]
        assert automation.calls[10] == "generate_report"
        assert automation.calls[11].startswith("export_csv:")

    def test_the_file_lands_in_the_day_wise_folder(self, settings, tmp_path):
        result = make_job(settings, FakeAutomation()).run(REPORT_DAY)
        assert result.path == (
            tmp_path
            / "REPORTS"
            / "2026-27 DAY WISE SALE REPORTS"
            / "9.SEPTEMBER"
            / "08.09.2026"
            / "08.09.2026.csv"
        )
        assert result.path.read_text().startswith("Item,Qty")

    def test_an_empty_export_is_reported_as_a_failure(self, settings):
        job = make_job(settings, FakeAutomation(csv_text=""))
        with pytest.raises(AutomationError, match="empty"):
            job.run(REPORT_DAY)


class TestExistingFiles:
    def _existing_report(self, settings, tmp_path):
        job = make_job(settings)
        destination = job.plan(REPORT_DAY).destination
        Path(destination.folder).mkdir(parents=True, exist_ok=True)
        Path(destination.path).write_text("original report", encoding="utf-8")
        return Path(destination.path)

    def test_existing_report_is_never_silently_overwritten(self, settings, tmp_path):
        path = self._existing_report(settings, tmp_path)
        automation = FakeAutomation()
        result = make_job(settings, automation).run(REPORT_DAY)
        assert result.skipped is True
        assert result.success is False
        assert path.read_text() == "original report"
        # NS Retail was never opened - only the readiness check ran.
        assert automation.calls == ["preflight"]

    def test_overwrite_is_explicit(self, settings, tmp_path):
        path = self._existing_report(settings, tmp_path)
        result = make_job(settings, FakeAutomation(), on_existing="overwrite").run(REPORT_DAY)
        assert result.success is True
        assert path.read_text().startswith("Item,Qty")

    def test_duplicate_writes_a_new_file(self, settings, tmp_path):
        path = self._existing_report(settings, tmp_path)
        result = make_job(settings, FakeAutomation(), on_existing="duplicate").run(REPORT_DAY)
        assert result.success is True
        assert result.path.name == "08.09.2026 (2).csv"
        assert path.read_text() == "original report"

    def test_ask_declined_skips_without_touching_ns_retail(self, settings, tmp_path):
        self._existing_report(settings, tmp_path)
        automation = FakeAutomation()
        job = make_job(settings, automation, on_existing="ask", confirm=lambda question: False)
        result = job.run(REPORT_DAY)
        assert result.skipped is True
        assert "launch" not in automation.calls

    def test_ask_accepted_overwrites(self, settings, tmp_path):
        path = self._existing_report(settings, tmp_path)
        job = make_job(settings, FakeAutomation(), on_existing="ask", confirm=lambda question: True)
        assert job.run(REPORT_DAY).success is True
        assert path.read_text().startswith("Item,Qty")


class TestDisabledReport:
    def test_a_disabled_report_refuses_to_run(self, tmp_path):
        settings = build_settings(
            {
                "storage": {"base_path": str(tmp_path / "REPORTS")},
                "reports": {"default_report": "purchases", "purchases": {"enabled": False}},
            }
        )
        with pytest.raises(AutomationError, match="disabled"):
            make_job(settings, FakeAutomation()).run(REPORT_DAY)
