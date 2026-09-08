"""The Purchases report (Reports -> Stock Reports -> Purchases)."""

from __future__ import annotations

from ..automation.ns_retail import NSRetailAutomation
from .base import ReportJob


class PurchaseReportJob(ReportJob):
    key = "purchases"
    title = "Purchases"

    def navigate(self, automation: NSRetailAutomation) -> None:
        """Reports -> Stock Reports -> Purchases.

        Each call maps to one entry in ``config/selectors.json``, so a change in
        NS Retail's menus is a configuration fix, not a code change.
        """
        automation.open_reports()
        automation.open_stock_reports()
        automation.select_purchase_report()
