"""The Dispatches report (Reports -> Stock Reports -> Dispatches)."""

from __future__ import annotations

from ..automation.ns_retail import NSRetailAutomation
from .base import ReportJob


class DispatchReportJob(ReportJob):
    key = "dispatches"
    title = "Dispatches"

    def navigate(self, automation: NSRetailAutomation) -> None:
        automation.close_report_screens()
        automation.open_reports()
        automation.open_stock_reports()
        automation.select_dispatches_report()
