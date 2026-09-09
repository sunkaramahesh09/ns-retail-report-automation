"""Change settings without hand-editing JSON.

    python -m ns_retail_automation.configure --show
    python -m ns_retail_automation.configure --base-path "D:\\2026-27 DAY WISE REPORTS"
    python -m ns_retail_automation.configure --exe "C:\\NS Retail\\NSRetail.exe"
    python -m ns_retail_automation.configure --fix

Typing a Windows path into a JSON file by hand is a trap: ``D:\\2026`` is not a
valid JSON escape, so the file stops loading. This tool writes the value
correctly, and ``--fix`` repairs a file that was already edited by hand.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path, PureWindowsPath
from typing import Any

from .config.settings import (
    DEFAULT_CONFIG_LOCATIONS,
    VALID_EXISTING_FILE_ACTIONS,
    build_settings,
    escape_lone_backslashes,
    find_config_file,
    load_config,
    parse_config_text,
)
from .errors import AutomationError
from .filesystem.report_storage import looks_like_windows_path

PROFILE_CONFIG = Path.home() / ".ns_retail_automation" / "config.json"


def resolve_config_path(explicit: str | None) -> Path:
    """The file to edit: the one in use, or the profile one to be created."""
    if explicit:
        return Path(explicit).expanduser()
    found = find_config_file()
    return found if found is not None else PROFILE_CONFIG


def read_config(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return parse_config_text(path.read_text(encoding="utf-8"), path)


def write_config(path: Path, data: dict[str, Any]) -> None:
    """Write the file, keeping a .bak of what was there before."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    # json.dump escapes backslashes correctly - that is the whole point.
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def set_in(data: dict[str, Any], section: str, key: str, value: Any) -> None:
    data.setdefault(section, {})[key] = value


def show(path: Path) -> int:
    settings = load_config(path if path.is_file() else None)
    print(f"Settings file   : {settings.source_path or '(built-in defaults)'}")
    print(f"Base path       : {settings.storage.base_path}")
    print(f"Report folder   : {settings.storage.report_folder_template}")
    print(f"Month folder    : {settings.storage.month_folder_template}")
    print(f"Date folder     : {settings.storage.date_folder_template}")
    print(f"Filename        : {settings.storage.filename_template}")
    print(f"On existing file: {settings.storage.on_existing_file}")
    print(f"Default date    : {settings.schedule.default_report_date}")
    print(f"NS Retail exe   : {settings.application.executable_path or '(not set)'}")
    print(f"Automatic login : {'enabled' if settings.login.enabled else 'disabled'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ns_retail_automation.configure",
        description="Change settings safely, without editing JSON by hand.",
    )
    parser.add_argument("--config", help="settings file to change (default: the one in use)")
    parser.add_argument("--show", action="store_true", help="print the current settings and exit")
    parser.add_argument("--base-path", help="folder holding the day-wise report folders")
    parser.add_argument("--exe", help="full path to NSRetail.exe")
    parser.add_argument("--process-name", help="NS Retail executable name, e.g. NSRetail.exe")
    parser.add_argument("--filename-template", help='e.g. "{dd}.{mm}.{yyyy}.csv"')
    parser.add_argument(
        "--on-existing",
        choices=VALID_EXISTING_FILE_ACTIONS,
        help="what to do when the report file already exists",
    )
    parser.add_argument(
        "--default-date",
        help="date used when none is given on the command line (yesterday/today/a date)",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="repair Windows paths written with single backslashes",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    path = resolve_config_path(args.config)

    try:
        if args.show:
            return show(path)

        data = read_config(path)
        changes: list[str] = []

        if args.base_path:
            set_in(data, "storage", "base_path", args.base_path.rstrip("\\/"))
            changes.append(f"base_path        -> {args.base_path}")
        if args.exe:
            set_in(data, "application", "executable_path", args.exe)
            changes.append(f"executable_path  -> {args.exe}")
            if not data.get("application", {}).get("process_name"):
                # A Windows path must be split on backslashes even when this
                # runs on macOS, so pathlib's local flavour cannot be used.
                flavour = PureWindowsPath if looks_like_windows_path(args.exe) else Path
                name = flavour(args.exe).name
                set_in(data, "application", "process_name", name)
                changes.append(f"process_name     -> {name}")
        if args.process_name:
            set_in(data, "application", "process_name", args.process_name)
            changes.append(f"process_name     -> {args.process_name}")
        if args.filename_template:
            set_in(data, "storage", "filename_template", args.filename_template)
            changes.append(f"filename_template-> {args.filename_template}")
        if args.on_existing:
            set_in(data, "storage", "on_existing_file", args.on_existing)
            changes.append(f"on_existing_file -> {args.on_existing}")
        if args.default_date:
            set_in(data, "schedule", "default_report_date", args.default_date)
            changes.append(f"default_date     -> {args.default_date}")

        if not changes and not args.fix:
            build_parser().print_help()
            return 0

        # Refuse to write something that would not load afterwards.
        build_settings(data)
        write_config(path, data)

        print(f"Settings file: {path}")
        for change in changes:
            print(f"  {change}")
        if args.fix and not changes:
            print("  rewritten with correct JSON escaping")
        print("\nCheck it with:  ns-retail-automation --dry-run")
        return 0
    except AutomationError as exc:
        print(f"[ERROR] {exc.message}", file=sys.stderr)
        if exc.hint:
            print(f"        {exc.hint}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
