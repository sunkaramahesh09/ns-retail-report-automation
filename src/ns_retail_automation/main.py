"""Command line entry point.

    ns-retail-automation --report purchases --date yesterday
    ns-retail-automation --report purchases --date 2026-09-08
    ns-retail-automation --dry-run
    ns-retail-automation --check
    ns-retail-automation --inspect            (Windows only)
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace
from datetime import date

from . import __version__
from .automation import get_backend
from .automation.ns_retail import NSRetailAutomation
from .automation.selectors import load_selectors
from .config.settings import Settings, load_config
from .errors import AutomationError, ConfigError
from .logging_config import setup_logging
from .notify import NotifySettings, show_result, warn_before_run
from .platform_support import describe_environment
from .reports import get_report_class
from .reports.base import ReportJob, RunPlan, RunResult
from .utils.dates import DateManager

logger = logging.getLogger(f"ns_retail_automation.{__name__.split('.')[-1]}")

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CONFIG = 2
EXIT_SKIPPED = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ns-retail-automation",
        description="Generate an NS Retail report and file the CSV automatically.",
        epilog=(
            "Dates may be 'today', 'yesterday', 2026-09-08, 08-09-2026, 08.09.2026, "
            "or a range such as 01-09-2026..08-09-2026."
        ),
    )
    parser.add_argument("--report", help="report to run (default: from the configuration)")
    parser.add_argument("--date", help="report date (default: schedule.default_report_date)")
    parser.add_argument("--config", help="path to the configuration file")
    parser.add_argument("--selectors", help="path to the selector file (default: config/selectors.json)")
    parser.add_argument(
        "--on-existing",
        choices=("skip", "overwrite", "duplicate", "ask"),
        help="what to do when the report file already exists (default: from the configuration)",
    )
    parser.add_argument("--base-path", help="override storage.base_path for this run")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show the date, folder and filename that would be used; do not touch NS Retail",
    )
    parser.add_argument("--check", action="store_true", help="report what is ready and what is not, then exit")
    parser.add_argument("--list-steps", action="store_true", help="list the workflow steps and whether each is mapped")
    parser.add_argument(
        "--try-step",
        metavar="STEP[+STEP...]",
        help=(
            "run one or more steps against the running NS Retail, for testing "
            "newly mapped selectors (this does click in the application). "
            "Steps joined with + (or ,) run back to back without returning to "
            "the console, which is the only way to test a popup menu: clicking "
            "back to this window closes it"
        ),
    )
    parser.add_argument("--list-reports", action="store_true", help="list the configured reports and exit")
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="run the read-only Windows control inspector (further options are passed to it)",
    )
    parser.add_argument(
        "--send-keys",
        metavar="KEYS",
        help=(
            "after --try-step, send these keystrokes to whatever has focus, "
            "without touching focus itself. For trying out ways through a menu "
            'that UI Automation cannot see, e.g. "{HOME}{DOWN 7}{ENTER}"'
        ),
    )
    parser.add_argument(
        "--key-pause",
        type=float,
        default=0.15,
        help="seconds between key presses for --send-keys (default: 0.15)",
    )
    parser.add_argument(
        "--probe",
        metavar="TEXT",
        help=(
            "after --try-step, search every window for controls matching TEXT. "
            "Use it for menus that close as soon as anything else is clicked"
        ),
    )
    parser.add_argument("--yes", action="store_true", help="answer 'yes' to overwrite questions (unattended runs)")
    parser.add_argument(
        "--no-popup",
        action="store_true",
        help="do not show the countdown or the result window (for testing)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="log every detail")
    parser.add_argument("-q", "--quiet", action="store_true", help="only show warnings and errors")
    parser.add_argument("--version", action="version", version=f"NS Retail Report Automation {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # --inspect delegates to the inspection tool, passing the other options on.
    if "--inspect" in argv:
        from .inspect import main as inspect_main  # noqa: PLC0415 - optional path

        remaining = [arg for arg in argv if arg != "--inspect"]
        return inspect_main(remaining)

    parser = build_parser()
    args, unknown = parser.parse_known_args(argv)
    if unknown:
        parser.error("unrecognised argument(s): " + " ".join(unknown))

    try:
        settings = load_config(args.config)
    except AutomationError as exc:
        _print_error(exc)
        return EXIT_CONFIG

    if args.base_path:
        settings = replace(settings, storage=replace(settings.storage, base_path=args.base_path))

    log_path = setup_logging(settings.logging, verbose=args.verbose, quiet=args.quiet)

    try:
        if args.list_reports:
            return _list_reports(settings)
        if args.check:
            return _check(settings, args)
        if args.list_steps:
            return _list_steps(settings, args)
        if args.try_step:
            return _try_step(settings, args)

        if args.report:
            job, report_date = _prepare(settings, args)
            if args.dry_run:
                return _dry_run(job, report_date)
            return _run(job, report_date, log_path, _notify_settings(settings, args))

        jobs, report_date = _prepare_all(settings, args)
        if args.dry_run:
            return _dry_run_all(jobs, report_date)
        return _run_all(jobs, report_date, log_path, _notify_settings(settings, args))
    except AutomationError as exc:
        logger.debug("Automation error", exc_info=True)
        _print_error(exc)
        return EXIT_CONFIG if isinstance(exc, ConfigError) else EXIT_FAILED
    except KeyboardInterrupt:  # pragma: no cover - interactive
        print("\nStopped by the user.")
        return EXIT_FAILED


# --------------------------------------------------------------------------
# Sub-commands
# --------------------------------------------------------------------------
def _resolve_single_date(settings: Settings, args: argparse.Namespace) -> date:
    dates = DateManager(
        fiscal_year_start_month=settings.dates.fiscal_year_start_month,
        fiscal_year_label_format=settings.dates.fiscal_year_label_format,
    )
    requested = args.date or settings.schedule.default_report_date
    days = dates.resolve_range(requested)
    if len(days) > 1:
        raise ConfigError(
            f"'{requested}' is a range of {len(days)} dates.",
            hint="Date ranges are not implemented yet - run one date at a time.",
        )
    return days[0]


def _prepare(settings: Settings, args: argparse.Namespace) -> tuple[ReportJob, date]:
    report_key = args.report or settings.default_report
    report_class = get_report_class(report_key)
    settings.report(report_class.key)  # validates that it is configured

    report_date = _resolve_single_date(settings, args)

    backend = get_backend(settings.application.ui_backend)
    selectors = load_selectors(args.selectors)
    automation = NSRetailAutomation(settings, selectors, backend)

    job = report_class(
        settings,
        automation,
        on_existing=args.on_existing,
        confirm=_confirm_yes if args.yes else _ask_user,
    )
    return job, report_date


def _prepare_all(settings: Settings, args: argparse.Namespace) -> tuple[list[ReportJob], date]:
    """Build one job per enabled report, sharing a single automation/session.

    This is what an unattended run (no ``--report``) does: work through every
    enabled report for the date, one after another, instead of just the
    configured default.
    """
    report_date = _resolve_single_date(settings, args)

    backend = get_backend(settings.application.ui_backend)
    selectors = load_selectors(args.selectors)
    automation = NSRetailAutomation(settings, selectors, backend)
    confirm = _confirm_yes if args.yes else _ask_user

    jobs: list[ReportJob] = []
    for key, report_settings in settings.reports.items():
        if not report_settings.enabled:
            continue
        try:
            report_class = get_report_class(key)
        except ConfigError:
            logger.warning("Report '%s' is configured but not implemented yet - skipping it.", key)
            continue
        jobs.append(report_class(settings, automation, on_existing=args.on_existing, confirm=confirm))

    if not jobs:
        raise ConfigError(
            "No enabled reports are configured.",
            hint="Enable at least one report in the 'reports' section, or pass --report <key>.",
        )
    return jobs, report_date


def _dry_run(job: ReportJob, report_date: date) -> int:
    plan: RunPlan = job.plan(report_date)
    print("DRY RUN - NS Retail will not be touched.\n")
    for line in plan.describe():
        print(line)

    automation = job.automation
    print()
    if automation is not None:
        missing = automation.missing_steps() + [
            f"window:{name}" for name in automation.missing_windows()
        ]
        if missing:
            print("Not mapped to NS Retail yet (Phase 2 work):")
            for name in missing:
                print(f"  - {name}")
            print(
                "\nRun the inspector on the Windows PC and fill in "
                "config/selectors.json before a real run."
            )
        else:
            print("All required windows and steps are mapped in the selector file.")
    return EXIT_OK


def _dry_run_all(jobs: list[ReportJob], report_date: date) -> int:
    print("DRY RUN - NS Retail will not be touched.\n")
    for job in jobs:
        plan: RunPlan = job.plan(report_date)
        for line in plan.describe():
            print(line)
        print()

    automation = jobs[0].automation if jobs else None
    if automation is not None:
        missing = automation.missing_steps() + [
            f"window:{name}" for name in automation.missing_windows()
        ]
        if missing:
            print("Not mapped to NS Retail yet (Phase 2 work):")
            for name in missing:
                print(f"  - {name}")
            print(
                "\nRun the inspector on the Windows PC and fill in "
                "config/selectors.json before a real run."
            )
        else:
            print("All required windows and steps are mapped in the selector file.")
    return EXIT_OK


def _notify_settings(settings: Settings, args: argparse.Namespace) -> NotifySettings:
    configured = settings.notifications
    if args.no_popup:
        return NotifySettings(enabled=False)
    return NotifySettings(
        enabled=configured.enabled,
        warn_before_seconds=configured.warn_before_seconds,
        show_result=configured.show_result,
        allow_postpone=configured.allow_postpone,
    )


def _run(
    job: ReportJob, report_date: date, log_path, notify: NotifySettings
) -> int:
    return _run_all([job], report_date, log_path, notify)


def _run_all(
    jobs: list[ReportJob], report_date: date, log_path, notify: NotifySettings
) -> int:
    """Run each job in turn, on one shared NS Retail session.

    The operator sees one result popup per report; clicking its OK button is
    what lets the loop move on to the next one, since the popup is a blocking
    dialog in this same process. A failure stops the sequence there rather
    than pressing on to reports that would likely hit the same problem - the
    operator fixes it and reruns the ones that did not finish.
    """
    pretty_date = report_date.strftime("%d-%m-%Y")
    multiple = len(jobs) > 1
    if multiple:
        titles = ", ".join(job.title for job in jobs)
        what = f"About to generate {len(jobs)} reports for {pretty_date} from NS Retail, one after another: {titles}."
    else:
        what = f"About to generate the {jobs[0].title} report for {pretty_date} from NS Retail."
    if not warn_before_run(notify, what=what):
        print("\nPostponed - nothing was changed.")
        logger.warning("Run postponed by the operator.")
        return EXIT_SKIPPED

    exit_code = EXIT_SKIPPED
    for job in jobs:
        label = f" ({job.title})" if multiple else ""
        logger.info("Starting NS Retail automation (%s, %s)", job.key, report_date.isoformat())
        try:
            result: RunResult = job.run(report_date)
        except AutomationError as exc:
            # The operator is unlikely to be watching the console, so the failure
            # has to reach them on screen.
            show_result(
                notify,
                title="NS Retail automation failed",
                message=f"{exc.message}\n\n{exc.hint or ''}\n\nLog: {log_path or '(none)'}",
                success=False,
            )
            raise

        if result.skipped:
            print(f"\nSkipped{label}: {result.message}")
            if result.hint:
                print(f"         {result.hint}")
            show_result(
                notify,
                title=f"NS Retail automation - nothing to do{label}",
                message=f"{result.message}\n\n{result.hint or ''}",
                success=True,
            )
            continue

        exit_code = EXIT_OK
        print(f"\nSuccess{label}: {result.message}")
        if log_path:
            print(f"Log: {log_path}")
        show_result(
            notify,
            title="NS Retail report saved",
            message=(
                f"The {job.title} report for {pretty_date} was saved to:\n\n{result.path}"
            ),
            success=True,
        )

    return exit_code


def _check(settings: Settings, args: argparse.Namespace) -> int:
    environment = describe_environment()
    print("Environment")
    print("-----------")
    print(f"Project version : {__version__}")
    for line in environment.summary_lines():
        print(line)

    print("\nConfiguration")
    print("-------------")
    print(f"File            : {settings.source_path or '(built-in defaults)'}")
    print(f"Default report  : {settings.default_report}")
    print(f"Default date    : {settings.schedule.default_report_date}")
    print(f"Base path       : {settings.storage.base_path}")
    print(f"On existing file: {settings.storage.on_existing_file}")
    print(f"Automatic login : {'enabled' if settings.login.enabled else 'disabled (manual login)'}")
    print(f"NS Retail exe   : {settings.application.executable_path or '(not set)'}")

    selectors = load_selectors(args.selectors)
    print("\nNS Retail control mapping")
    print("-------------------------")
    print(f"File            : {selectors.source_path or '(none found)'}")
    backend = get_backend(settings.application.ui_backend)
    automation = NSRetailAutomation(settings, selectors, backend)
    missing_windows = automation.missing_windows()
    missing_steps = automation.missing_steps()
    if not missing_windows and not missing_steps:
        print("All required windows and steps are mapped.")
    else:
        if missing_windows:
            print("Windows still to identify : " + ", ".join(missing_windows))
        if missing_steps:
            print("Steps still to map        : " + ", ".join(missing_steps))
        print(
            "\nNext step: on the Windows PC run "
            "'python -m ns_retail_automation.inspect --windows', then inspect each "
            "NS Retail screen and record the controls in config/selectors.json."
        )
    return EXIT_OK


def _build_automation(settings: Settings, args: argparse.Namespace) -> NSRetailAutomation:
    backend = get_backend(settings.application.ui_backend)
    selectors = load_selectors(args.selectors)
    return NSRetailAutomation(settings, selectors, backend)


def _list_steps(settings: Settings, args: argparse.Namespace) -> int:
    automation = _build_automation(settings, args)
    print("Workflow steps (in order):\n")
    for name, mapped, description in automation.step_status():
        mark = "mapped    " if mapped else "NOT MAPPED"
        print(f"  [{mark}] {name}")
        if description:
            print(f"               {description}")
    print("\nTest one step against the running NS Retail with:")
    print("  ns-retail-automation --try-step open_reports")
    return EXIT_OK


def _try_step(settings: Settings, args: argparse.Namespace) -> int:
    """Run a single step, so a new selector can be verified on its own."""
    automation = _build_automation(settings, args)
    # "+" as well as "," because cmd.exe splits arguments on commas, so a
    # comma-separated list arrives as several arguments instead of one.
    names = [
        name.strip()
        for name in args.try_step.replace(",", "+").split("+")
        if name.strip()
    ]
    if not names:
        raise ConfigError("No step name was given to --try-step.")

    if not automation.backend.is_supported:
        raise AutomationError(
            "NS Retail automation is not available on this computer.",
            hint="Run this on the Windows PC where NS Retail is installed.",
        )

    report_date = None
    if args.date:
        dates = DateManager(
            fiscal_year_start_month=settings.dates.fiscal_year_start_month,
            fiscal_year_label_format=settings.dates.fiscal_year_label_format,
        )
        report_date = dates.resolve(args.date)

    print(f"Connecting to {settings.application.name} ...")
    automation.launch()
    automation.connect()

    for name in names:
        print(f"Running step '{name}' ...")
        automation.run_named_step(name, report_date=report_date)
        print(f"  step '{name}' finished without an error.")

    print(f"\n{len(names)} step(s) finished: {', '.join(names)}")

    if args.send_keys:
        from pywinauto.keyboard import send_keys  # noqa: PLC0415

        print(
            f"Sending keys {args.send_keys!r} to whatever has focus "
            f"({args.key_pause:.2f}s between presses) ..."
        )
        send_keys(args.send_keys, with_spaces=True, pause=args.key_pause)
        print("Sent. Check NS Retail on screen to see where it landed.")
        return EXIT_OK

    if args.probe:
        # Whatever the step opened is still on screen and still has focus,
        # which is the only moment a ribbon popup can be read.
        from .inspect import search_every_window  # noqa: PLC0415

        print(f"\nLooking for '{args.probe}' in every window ...\n")
        search_every_window(automation.backend, args.probe, depth=10)
        return EXIT_OK

    print("Check NS Retail on screen to confirm it did what you expected.")
    return EXIT_OK


def _list_reports(settings: Settings) -> int:
    print("Configured reports:")
    for key, report in sorted(settings.reports.items()):
        state = "enabled" if report.enabled else "disabled"
        default = " (default)" if key == settings.default_report else ""
        print(f"  {key:<12} {state}{default}")
    return EXIT_OK


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _ask_user(question: str) -> bool:  # pragma: no cover - interactive
    try:
        answer = input(f"{question} [y/N] ").strip().lower()
    except EOFError:
        return False
    return answer in ("y", "yes")


def _confirm_yes(question: str) -> bool:
    logger.warning("%s -> answered 'yes' because --yes was given.", question)
    return True


def _print_error(exc: AutomationError) -> None:
    print(f"[ERROR] {exc.message}", file=sys.stderr)
    if exc.hint:
        print(f"        {exc.hint}", file=sys.stderr)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
