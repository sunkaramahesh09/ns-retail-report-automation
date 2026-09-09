"""The NS Retail workflow.

STATUS
------
The workflow (what happens, in what order, with which timeouts and error
messages) is implemented here.  The *control details* for each step - which
button, which menu item - are NOT known yet: NS Retail has not been inspected.
They are read from ``config/selectors.json`` and, until that file is filled in
on the Windows PC (Phase 2), each step fails with a clear message naming the
step that still has to be mapped.  Nothing here guesses an automation id or a
screen coordinate.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path, PurePath

from ..config.credentials import Credentials, resolve_credentials
from ..config.settings import Settings
from ..errors import (
    ApplicationNotFoundError,
    AutomationError,
    ConnectionError_,
    ExportError,
    LoginError,
    ReportViewerError,
    SelectorNotConfiguredError,
)
from ..utils.dates import MONTH_NAMES
from ..utils.retry import retry_call
from ..utils.waits import wait_for_file
from .base import AutomationBackend, ProcessInfo, WindowRef
from .selectors import Selectors, Step, UiTarget

logger = logging.getLogger(__name__)

#: Steps the purchase-report workflow needs, in the order they are used.
STEP_OPEN_REPORTS = "open_reports"
STEP_OPEN_STOCK_REPORTS = "open_stock_reports"
STEP_SELECT_PURCHASE_REPORT = "select_purchase_report"
STEP_SET_DATE = "set_date"
STEP_OPEN_COLUMN_SETTINGS = "open_column_settings"
STEP_INCLUDE_ALL_COLUMNS = "include_all_columns"
STEP_APPLY_AND_SEARCH = "apply_and_search"
STEP_SEARCH = "search"
STEP_GENERATE_REPORT = "generate_report"
STEP_EXPORT_TO = "export_to"
STEP_CHOOSE_CSV = "choose_csv_format"
STEP_CONFIRM_EXPORT = "confirm_export"
STEP_SAVE_SET_PATH = "save_set_path"
STEP_SAVE_CONFIRM = "save_confirm"
STEP_LOGIN = "login"

PURCHASE_REPORT_STEPS = (
    STEP_OPEN_REPORTS,
    STEP_OPEN_STOCK_REPORTS,
    STEP_SELECT_PURCHASE_REPORT,
    STEP_SET_DATE,
    STEP_OPEN_COLUMN_SETTINGS,
    STEP_INCLUDE_ALL_COLUMNS,
    STEP_APPLY_AND_SEARCH,
    STEP_SEARCH,
    STEP_GENERATE_REPORT,
    STEP_EXPORT_TO,
    STEP_CHOOSE_CSV,
    STEP_CONFIRM_EXPORT,
    STEP_SAVE_SET_PATH,
    STEP_SAVE_CONFIRM,
)

#: Steps that are skipped when they are not mapped, because whether they exist
#: depends on how the operator works. The Include/Exclude column dialog (F3)
#: is one of these: it is part of the manual routine, but the report can also
#: be searched for directly.
OPTIONAL_STEPS = frozenset(
    {
        STEP_OPEN_COLUMN_SETTINGS,
        STEP_INCLUDE_ALL_COLUMNS,
        STEP_APPLY_AND_SEARCH,
        STEP_SEARCH,
    }
)


@dataclass
class SessionState:
    """What the automation currently knows about the running application."""

    process: ProcessInfo | None = None
    launched_by_us: bool = False
    main_window: WindowRef | None = None
    report_viewer: WindowRef | None = None
    logged_in: bool = False


class NSRetailAutomation:
    """Drives NS Retail through the purchase-report workflow.

    Every method is a single, replaceable step: if NS Retail changes, only the
    matching entry in ``config/selectors.json`` (or, at worst, one method here)
    needs attention.
    """

    def __init__(
        self,
        settings: Settings,
        selectors: Selectors,
        backend: AutomationBackend,
    ) -> None:
        self.settings = settings
        self.selectors = selectors
        self.backend = backend
        self.state = SessionState()

    # ------------------------------------------------------------------
    # Readiness
    # ------------------------------------------------------------------
    def missing_steps(self, steps: tuple[str, ...] = PURCHASE_REPORT_STEPS) -> list[str]:
        """Steps that still need control details from the Windows PC.

        Optional steps are not reported as missing, but the search has to
        happen somehow, so one of 'apply_and_search' or 'search' is required.
        """
        required = [name for name in steps if name not in OPTIONAL_STEPS]
        missing = list(self.selectors.missing_steps(required))
        if not (
            self.selectors.has_step(STEP_APPLY_AND_SEARCH)
            or self.selectors.has_step(STEP_SEARCH)
        ):
            missing.append(f"{STEP_APPLY_AND_SEARCH} or {STEP_SEARCH}")
        if self.settings.login.enabled and not self.selectors.has_step(STEP_LOGIN):
            missing.append(STEP_LOGIN)
        return missing

    def missing_windows(self) -> list[str]:
        needed = ["main", "report_viewer", "save_dialog"]
        if self.settings.login.enabled:
            needed.append("login")
        return [key for key in needed if not self.selectors.has_window(key)]

    def preflight(self) -> None:
        """Fail early, with one message listing everything that is not mapped."""
        if not self.backend.is_supported:
            raise AutomationError(
                "NS Retail automation is not available on this computer.",
                hint="Run this program on the Windows PC where NS Retail is installed.",
            )
        problems = []
        missing_windows = self.missing_windows()
        if missing_windows:
            problems.append("windows: " + ", ".join(missing_windows))
        missing_steps = self.missing_steps()
        if missing_steps:
            problems.append("steps: " + ", ".join(missing_steps))
        if problems:
            raise SelectorNotConfiguredError(
                "NS Retail has not been mapped yet - " + "; ".join(problems),
                hint=(
                    "Run 'python -m ns_retail_automation.inspect --windows' and "
                    "'python -m ns_retail_automation.inspect' on each NS Retail "
                    "screen, then fill in config/selectors.json."
                ),
            )

    # ------------------------------------------------------------------
    # Application lifecycle
    # ------------------------------------------------------------------
    def is_running(self) -> bool:
        """True when an NS Retail process is already running."""
        identifier = self.settings.application.process_name or self.settings.application.executable_path
        if not identifier:
            return False
        processes = self.backend.find_processes(identifier)
        if processes:
            self.state.process = processes[0]
        return bool(processes)

    def launch(self) -> ProcessInfo:
        """Start NS Retail, or reuse the instance that is already running."""
        app = self.settings.application
        if app.reuse_running_instance and self.is_running():
            logger.info(
                "%s is already running (pid %s) - reusing it.",
                app.name,
                self.state.process.pid if self.state.process else "?",
            )
            return self.state.process  # type: ignore[return-value]

        if not app.executable_path:
            raise ApplicationNotFoundError(
                f"{app.name} is not running and no executable path is configured.",
                hint=(
                    "Set application.executable_path in the configuration file, or "
                    "start NS Retail by hand before running the automation."
                ),
            )
        logger.info("Starting %s", app.name)
        process = self.backend.start_process(
            app.executable_path, working_directory=app.working_directory
        )
        self.state.process = process
        self.state.launched_by_us = True
        return process

    def connect(self) -> WindowRef:
        """Attach to the main NS Retail window."""
        app = self.settings.application
        spec = self.selectors.window("main")
        timeout = spec.timeout_seconds or app.connect_timeout_seconds
        pid = self.state.process.pid if self.state.process else None
        logger.info("Waiting for the %s main window", app.name)
        try:
            window = self.backend.wait_for_window(spec, timeout=timeout, process_id=pid)
        except AutomationError as exc:
            raise ConnectionError_(
                f"Could not connect to {app.name}: {exc}",
                hint=exc.hint,
            ) from exc
        self.state.main_window = window
        logger.info("Connected to %s ('%s')", app.name, window.info.title)
        return window

    def login(self, credentials: Credentials | None = None) -> None:
        """Log in, but only when automatic login is configured."""
        login_settings = self.settings.login
        if not login_settings.enabled:
            logger.info(
                "Automatic login is disabled - continuing with the session already "
                "logged in on screen."
            )
            self.state.logged_in = True
            return

        creds = credentials or resolve_credentials(login_settings)
        if creds is None:  # pragma: no cover - guarded by settings validation
            raise LoginError("Login is enabled but no credentials could be resolved.")

        window = self._window_for(self.selectors.step(STEP_LOGIN))
        logger.info("Logging in as %s", creds.username)
        self._run_step(
            STEP_LOGIN,
            window=window,
            context={"username": creds.username, "password": creds.password},
            timeout=login_settings.timeout_seconds,
        )
        self.state.logged_in = True

    def close(self) -> None:
        """Close NS Retail if the automation started it and is asked to."""
        if not self.settings.application.close_when_finished:
            return
        if not self.state.launched_by_us:
            logger.info("Leaving NS Retail open (it was already running).")
            return
        if self.state.main_window is None:
            return
        logger.info("Closing %s", self.settings.application.name)
        self.backend.close_window(self.state.main_window)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def open_reports(self) -> None:
        logger.info("Opening Reports")
        self._run_step(STEP_OPEN_REPORTS)

    def open_stock_reports(self) -> None:
        logger.info("Opening Stock Reports")
        self._run_step(STEP_OPEN_STOCK_REPORTS)

    def select_purchase_report(self) -> None:
        logger.info("Selecting Purchases")
        self._run_step(STEP_SELECT_PURCHASE_REPORT)

    def set_date(self, report_date: date) -> None:
        """Type the report date into the date field(s)."""
        logger.info("Setting report date: %s", report_date.strftime("%d-%m-%Y"))
        self._run_step(STEP_SET_DATE, context=_date_context(report_date))

    def search(self) -> None:
        """Run the search, including the Include/Exclude column dialog.

        The manual routine is: press F3, tick the columns to include, then
        'Apply and Search'. Each part is a separate step so it can be mapped -
        or left out - on its own.
        """
        for name in (STEP_OPEN_COLUMN_SETTINGS, STEP_INCLUDE_ALL_COLUMNS):
            if self.selectors.has_step(name):
                logger.info("Running '%s'", name.replace("_", " "))
                self._run_step(name)

        if self.selectors.has_step(STEP_APPLY_AND_SEARCH):
            logger.info("Applying the column settings and searching")
            self._run_step(STEP_APPLY_AND_SEARCH)
            return

        logger.info("Running Search")
        self._run_step(STEP_SEARCH)

    def generate_report(self) -> WindowRef:
        """Press Report and wait for the Report Viewer window."""
        report_settings = self.settings.report()
        logger.info("Generating report")
        self._run_step(STEP_GENERATE_REPORT)

        spec = self.selectors.window("report_viewer")
        timeout = spec.timeout_seconds or report_settings.generation_timeout_seconds
        logger.info("Waiting up to %.0f seconds for the report preview", timeout)
        try:
            if spec.inside:
                parent = self._window_by_key(spec.inside)
                viewer = self.backend.wait_for_child_window(parent, spec, timeout=timeout)
            else:
                pid = self.state.process.pid if self.state.process else None
                viewer = self.backend.wait_for_window(spec, timeout=timeout, process_id=pid)
        except AutomationError as exc:
            raise ReportViewerError(
                f"The Report Viewer did not appear within {timeout:.0f} seconds.",
                hint=(
                    "The report may still be generating, or the search returned no "
                    "data. Check NS Retail on screen."
                ),
            ) from exc
        self.state.report_viewer = viewer
        logger.info("Report preview detected ('%s')", viewer.info.title)
        return viewer

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def export_csv(self, destination: PurePath | str) -> Path:
        """Export the open report to ``destination`` as CSV and verify the file."""
        target = Path(destination)
        viewer = self.state.report_viewer
        if viewer is None:
            raise ReportViewerError(
                "There is no open Report Viewer to export from.",
                hint="generate_report() must succeed before export_csv().",
            )

        context = {
            "destination_path": str(target),
            "destination_folder": str(target.parent),
            "filename": target.name,
            "filename_stem": target.stem,
        }
        timeouts = self.settings.timeouts

        logger.info("Exporting to CSV: %s", target)
        self._run_step(STEP_EXPORT_TO, window=viewer, timeout=timeouts.menu_seconds)
        self._run_step(STEP_CHOOSE_CSV, window=viewer, timeout=timeouts.menu_seconds)
        self._run_step(STEP_CONFIRM_EXPORT, window=viewer, timeout=timeouts.control_seconds)

        save_spec = self.selectors.window("save_dialog")
        save_timeout = save_spec.timeout_seconds or timeouts.window_seconds
        try:
            save_dialog = self.backend.wait_for_window(save_spec, timeout=save_timeout)
        except AutomationError as exc:
            raise ExportError(
                f"The save dialog did not appear within {save_timeout:.0f} seconds.",
                hint=exc.hint,
            ) from exc

        self._run_step(
            STEP_SAVE_SET_PATH,
            window=save_dialog,
            context=context,
            timeout=timeouts.control_seconds,
        )
        self._run_step(
            STEP_SAVE_CONFIRM,
            window=save_dialog,
            context=context,
            timeout=timeouts.control_seconds,
        )

        logger.info("Waiting for the exported file to be written")
        created = wait_for_file(target, timeout=timeouts.file_seconds)
        logger.info("File created successfully: %s", created)
        return created

    def run_named_step(self, name: str, *, report_date: date | None = None) -> None:
        """Run one step on its own, for testing a newly mapped selector.

        This really does interact with NS Retail - it is the same code the full
        workflow uses, just for a single step.
        """
        context = _date_context(report_date) if report_date else None
        logger.info("Running single step '%s'", name)
        self._run_step(name, context=context)

    def step_status(self, steps: tuple[str, ...] = PURCHASE_REPORT_STEPS) -> list[tuple[str, bool, str]]:
        """(name, mapped, description) for each step of the workflow."""
        status: list[tuple[str, bool, str]] = []
        for name in steps:
            step = self.selectors.steps.get(name)
            mapped = step is not None and step.is_configured()
            description = step.description if step is not None else ""
            status.append((name, mapped, description))
        return status

    # ------------------------------------------------------------------
    # Step plumbing
    # ------------------------------------------------------------------
    def _window_for(self, step: Step) -> WindowRef:
        """Resolve the window a step runs in."""
        return self._window_by_key(step.window or "main")

    def _window_by_key(self, key: str, *, seen: tuple[str, ...] = ()) -> WindowRef:
        if key in seen:
            raise ConnectionError_(
                "Window definitions refer to each other in a loop: "
                + " -> ".join([*seen, key])
            )
        if key == "main":
            if self.state.main_window is None:
                raise ConnectionError_(
                    "Not connected to NS Retail yet.",
                    hint="connect() must succeed before this step.",
                )
            return self.state.main_window
        if key == "report_viewer" and self.state.report_viewer is not None:
            return self.state.report_viewer

        spec = self.selectors.window(key)
        timeout = spec.timeout_seconds or self.settings.timeouts.window_seconds
        if spec.inside:
            parent = self._window_by_key(spec.inside, seen=(*seen, key))
            return self.backend.wait_for_child_window(parent, spec, timeout=timeout)
        pid = self.state.process.pid if self.state.process else None
        return self.backend.wait_for_window(spec, timeout=timeout, process_id=pid)

    def _run_step(
        self,
        name: str,
        *,
        window: WindowRef | None = None,
        context: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> None:
        step = self.selectors.step(name)
        target_window = window or self._window_for(step)
        effective_timeout = timeout or self.settings.timeouts.control_seconds
        retry_settings = self.settings.retry

        step_window_key = step.window or "main"
        for target in step.targets:
            resolved = _resolve_value(target, context or {}, step_name=name)
            # A target may live in another window, e.g. a dialog this step
            # opened. That choice applies to this target only.
            window_for_target = target_window
            if resolved.window and resolved.window != step_window_key:
                window_for_target = self._window_by_key(resolved.window)
            # Only the search criteria are logged - a value may hold a password.
            label = resolved.label()
            logger.debug("Step '%s': %s (%s)", name, label, resolved.action)
            try:
                retry_call(
                    lambda t=resolved, w=window_for_target: self.backend.perform(
                        w, t, timeout=t.timeout_seconds or effective_timeout
                    ),
                    attempts=retry_settings.attempts,
                    delay=retry_settings.delay_seconds,
                    backoff=retry_settings.backoff,
                    exceptions=(AutomationError,),
                    description=f"step '{name}' -> {label}",
                )
            except AutomationError as exc:
                if resolved.optional:
                    logger.info(
                        "Optional control '%s' in step '%s' was not there - continuing.",
                        label,
                        name,
                    )
                    continue
                raise type(exc)(
                    f"Step '{name}' failed at '{label}': {exc.message}", hint=exc.hint
                ) from exc


def _date_context(report_date: date) -> dict[str, str]:
    """Placeholders a date field can be filled with.

    ``date_dd_month_yyyy`` matches how NS Retail displays a date in its date
    pickers ("08 September 2026"). The month name is spelled out from a fixed
    English table rather than strftime, so the machine's locale cannot change
    what gets typed.
    """
    month = MONTH_NAMES[report_date.month - 1].capitalize()
    return {
        "date_dd_month_yyyy": f"{report_date.day:02d} {month} {report_date.year}",
        "date_d_month_yyyy": f"{report_date.day} {month} {report_date.year}",
        "month_name": month,
        "date_iso": report_date.isoformat(),
        "date_dd_mm_yyyy": report_date.strftime("%d-%m-%Y"),
        "date_dd_mm_yyyy_dots": report_date.strftime("%d.%m.%Y"),
        "date_dd_mm_yyyy_slashes": report_date.strftime("%d/%m/%Y"),
        "date_mm_dd_yyyy_slashes": report_date.strftime("%m/%d/%Y"),
        "date_ddmmyyyy": report_date.strftime("%d%m%Y"),
        "dd": f"{report_date.day:02d}",
        "mm": f"{report_date.month:02d}",
        "yyyy": str(report_date.year),
    }


#: Runtime placeholders are lower case, e.g. {date_dd_month_yyyy}. Keystroke
#: names are upper case, e.g. {F3} or {TAB}, and must be left for pywinauto.
_PLACEHOLDER_RE = re.compile(r"\{([a-z][a-z0-9_]*)\}")


def _resolve_value(target: UiTarget, context: dict[str, str], *, step_name: str) -> UiTarget:
    """Fill ``{placeholders}`` in a target's ``value`` from the runtime context.

    Only lower-case names are substituted, so a send_keys value such as
    ``{F3}`` or ``^a{TAB}`` passes through to pywinauto untouched.
    """
    if not target.value or "{" not in target.value:
        return target

    missing: list[str] = []

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in context:
            return str(context[name])
        missing.append(name)
        return match.group(0)

    value = _PLACEHOLDER_RE.sub(substitute, target.value)
    if missing:
        raise SelectorNotConfiguredError(
            f"Step '{step_name}' uses unknown placeholder "
            f"{{{missing[0]}}} in a value.",
            hint="Available placeholders here: " + (", ".join(sorted(context)) or "(none)"),
        )
    return replace(target, value=value)
