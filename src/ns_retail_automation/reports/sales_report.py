"""The Sales report (Reports -> Stock Reports -> Sales)."""

from __future__ import annotations

from ..automation.ns_retail import NSRetailAutomation
from .base import ReportJob


class SalesReportJob(ReportJob):
    key = "sales"
    title = "Sales"

    def navigate(self, automation: NSRetailAutomation) -> None:
        automation.close_report_screens()
        automation.open_reports()
        automation.open_stock_reports()
        automation.select_sales_report()
