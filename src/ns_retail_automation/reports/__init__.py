"""Report definitions and the registry the CLI looks them up in."""

from __future__ import annotations

from ..errors import ConfigError
from .base import ReportJob, RunPlan, RunResult
from .dispatch_report import DispatchReportJob
from .purchase_report import PurchaseReportJob
from .sales_report import SalesReportJob
from .stock_as_on_date_report import StockAsOnDateReportJob

#: Report key -> job class.  Add new report types here.
REPORT_TYPES: dict[str, type[ReportJob]] = {
    PurchaseReportJob.key: PurchaseReportJob,
    DispatchReportJob.key: DispatchReportJob,
    SalesReportJob.key: SalesReportJob,
    StockAsOnDateReportJob.key: StockAsOnDateReportJob,
}

__all__ = [
    "ReportJob",
    "RunPlan",
    "RunResult",
    "PurchaseReportJob",
    "DispatchReportJob",
    "SalesReportJob",
    "StockAsOnDateReportJob",
    "REPORT_TYPES",
    "get_report_class",
]


def get_report_class(key: str) -> type[ReportJob]:
    try:
        return REPORT_TYPES[key.strip().lower()]
    except KeyError:
        raise ConfigError(
            f"'{key}' is not a report this program knows how to run.",
            hint="Available reports: " + ", ".join(sorted(REPORT_TYPES)),
        ) from None
