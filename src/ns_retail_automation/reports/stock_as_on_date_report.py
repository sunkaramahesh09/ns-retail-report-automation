"""The Stock As on date report (Reports -> Stock Reports -> Stock As on date).

Unlike Purchases, Dispatches and Sales, this is a snapshot report - its
screen has a single 'As on Date' field instead of a From/To range.
"""

from __future__ import annotations

from datetime import date

from ..automation.ns_retail import NSRetailAutomation
from .base import ReportJob


class StockAsOnDateReportJob(ReportJob):
    key = "stock_as_on_date"
    title = "Stock As on date"

    def navigate(self, automation: NSRetailAutomation) -> None:
        automation.close_report_screens()
        automation.open_reports()
        automation.open_stock_reports()
        automation.select_stock_as_on_date_report()

    def set_date(self, automation: NSRetailAutomation, report_date: date) -> None:
        automation.set_as_on_date(report_date)
