"""Report jobs: tie together date, destination and the NS Retail workflow."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path, PurePath

from ..automation.ns_retail import NSRetailAutomation
from ..config.settings import ReportSettings, Settings
from ..errors import AutomationError, FileAlreadyExistsError
from ..filesystem.report_storage import FilePlan, ReportDestination, ReportStorage
from ..utils.dates import DateManager

logger = logging.getLogger(__name__)

#: Asked before overwriting when storage.on_existing_file is "ask".
ConfirmCallback = Callable[[str], bool]


@dataclass(frozen=True)
class RunPlan:
    """Everything decided before NS Retail is touched (this is the dry run)."""

    report_key: str
    report_date: date
    destination: ReportDestination
    file_plan: FilePlan
    create_folders: bool
    folder_exists: bool | None

    def describe(self) -> list[str]:
        folder_note = {
            True: "exists",
            False: "will be created" if self.create_folders else "MISSING (creation disabled)",
            None: "cannot be checked from this computer",
        }[self.folder_exists]
        lines = [
            f"Report      : {self.report_key}",
            f"Date        : {self.report_date.strftime('%d-%m-%Y')} "
            f"({self.report_date.strftime('%A %d %B %Y')})",
            f"Destination : {self.destination.folder}  [{folder_note}]",
            f"Filename    : {self.destination.filename}",
            f"Full path   : {self.destination.path}",
            f"Existing file: {'yes' if self.file_plan.existing else 'no'} "
            f"-> action '{self.file_plan.action}' ({self.file_plan.reason})",
        ]
        return lines


@dataclass
class RunResult:
    """What actually happened."""

    report_key: str
    report_date: date
    success: bool
    skipped: bool = False
    path: PurePath | None = None
    message: str = ""
    hint: str = ""
    steps_completed: list[str] = field(default_factory=list)


class ReportJob:
    """Base class for one kind of report.

    Subclasses only describe how to reach their report screen; everything else
    (dates, folders, existing files, verification, logging) is shared.
    """

    #: Config key, e.g. "purchases".
    key = "report"
    #: Human readable name used in messages.
    title = "Report"

    def __init__(
        self,
        settings: Settings,
        automation: NSRetailAutomation | None = None,
        *,
        on_existing: str | None = None,
        confirm: ConfirmCallback | None = None,
    ) -> None:
        self.settings = settings
        self.automation = automation
        self.on_existing = on_existing
        self.confirm = confirm
        self.dates = DateManager(
            fiscal_year_start_month=settings.dates.fiscal_year_start_month,
            fiscal_year_label_format=settings.dates.fiscal_year_label_format,
        )
        self.report_settings: ReportSettings = settings.report(self.key)
        self.storage = ReportStorage(settings.storage_for(self.report_settings), self.dates)

    # -- planning --------------------------------------------------------
    def plan(self, report_date: date) -> RunPlan:
        """Work out date, folder, filename and existing-file handling."""
        destination = self.storage.resolve(report_date)
        file_plan = self.storage.plan(destination, on_existing=self.on_existing)
        folder_exists: bool | None
        if destination.is_native:
            folder_exists = Path(destination.folder).is_dir()
        else:
            folder_exists = None
        return RunPlan(
            report_key=self.key,
            report_date=report_date,
            destination=destination,
            file_plan=file_plan,
            create_folders=self.storage.settings.create_missing_folders,
            folder_exists=folder_exists,
        )

    # -- navigation (subclass responsibility) ----------------------------
    def navigate(self, automation: NSRetailAutomation) -> None:
        """Open the screen this report lives on."""
        raise NotImplementedError

    def set_date(self, automation: NSRetailAutomation, report_date: date) -> None:
        """Put the report date into NS Retail.

        Overridden by a report whose screen uses a single date instead of a
        From/To range (Stock As on date).
        """
        automation.set_date(report_date)

    # -- execution -------------------------------------------------------
    def run(self, report_date: date) -> RunResult:
        """Run the full workflow for one date."""
        if self.automation is None:  # pragma: no cover - guarded by the CLI
            raise AutomationError(
                "No automation backend was supplied.",
                hint="This report can only run on the Windows PC.",
            )
        if not self.report_settings.enabled:
            raise AutomationError(
                f"The {self.title} report is disabled in the configuration.",
                hint=f"Set reports.{self.key}.enabled to true.",
            )

        automation = self.automation
        result = RunResult(report_key=self.key, report_date=report_date, success=False)
        plan = self.plan(report_date)

        # 1. Refuse early if this computer (or the selector file) is not ready.
        automation.preflight()

        # 2. Decide about an existing file BEFORE opening NS Retail.
        target_path = self._resolve_existing(plan, result)
        if result.skipped:
            return result

        # 3. Make sure the destination folder is there.
        self.storage.ensure_folder(plan.destination)

        # 4. Drive NS Retail.
        automation.launch()
        result.steps_completed.append("launch")
        automation.connect()
        result.steps_completed.append("connect")
        automation.login()
        result.steps_completed.append("login")

        self.navigate(automation)
        result.steps_completed.append("navigate")

        self.set_date(automation, report_date)
        result.steps_completed.append("set_date")
        automation.search()
        result.steps_completed.append("search")
        automation.generate_report()
        result.steps_completed.append("generate_report")

        created = automation.export_csv(target_path)
        result.steps_completed.append("export_csv")

        # 5. Prove the file is really there.
        verified = self.storage.verify_created(created)
        result.steps_completed.append("verify")
        automation.close()

        result.success = True
        result.path = verified
        result.message = f"{self.title} report for {report_date.strftime('%d-%m-%Y')} saved to {verified}"
        logger.info("Automation completed successfully")
        return result

    # -- helpers ---------------------------------------------------------
    def _resolve_existing(self, plan: RunPlan, result: RunResult) -> Path:
        file_plan = plan.file_plan
        path = Path(file_plan.path)

        if file_plan.action == "ask":
            question = (
                f"'{path}' already exists. Overwrite it?"
            )
            approved = self.confirm(question) if self.confirm else False
            if not approved:
                result.skipped = True
                result.success = False
                result.path = path
                result.message = f"Skipped: {path} already exists and was not overwritten."
                logger.warning(result.message)
                return path
            logger.warning("Overwriting existing file %s", path)
            return path

        if file_plan.action == "skip":
            try:
                self.storage.guard_existing(file_plan)
            except FileAlreadyExistsError as exc:
                result.skipped = True
                result.success = False
                result.path = path
                result.message = exc.message
                result.hint = exc.hint or ""
                logger.warning("%s", exc.message)
            return path

        if file_plan.action == "overwrite":
            logger.warning("Overwriting existing file %s", path)
        elif file_plan.action == "duplicate":
            logger.warning("%s", file_plan.reason)
        return path
