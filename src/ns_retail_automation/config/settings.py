"""Configuration loading and validation.

Nothing company specific belongs in the source code - it all lives in a JSON
file.  This module reads that file, merges it over the built-in defaults and
turns it into typed dataclasses.
"""

from __future__ import annotations

import copy
import json
import logging
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from ..errors import ConfigError, ConfigNotFoundError

logger = logging.getLogger(__name__)

ENV_CONFIG_PATH = "NS_RETAIL_CONFIG"

#: Where a configuration file is looked for, in order, when none is given.
DEFAULT_CONFIG_LOCATIONS = (
    Path("config/config.json"),
    Path("config.json"),
    Path.home() / ".ns_retail_automation" / "config.json",
)

VALID_EXISTING_FILE_ACTIONS = ("skip", "overwrite", "duplicate", "ask")
VALID_CREDENTIAL_SOURCES = ("none", "env", "keyring", "prompt")

DEFAULTS: dict[str, Any] = {
    "application": {
        "name": "NS Retail",
        "version": "4.0.3",
        "executable_path": "",
        "working_directory": "",
        "process_name": "",
        "main_window_title_regex": "",
        "ui_backend": "uia",
        "launch_timeout_seconds": 90,
        "connect_timeout_seconds": 30,
        "reuse_running_instance": True,
        "close_when_finished": False,
    },
    "login": {
        "enabled": False,
        "credential_source": "none",
        "username": "",
        "username_env_var": "NS_RETAIL_USERNAME",
        "password_env_var": "NS_RETAIL_PASSWORD",
        "keyring_service": "NS Retail",
        "timeout_seconds": 60,
    },
    "dates": {
        "fiscal_year_start_month": 4,
        "fiscal_year_label_format": "{start_year}-{end_year_short}",
    },
    "schedule": {
        "default_report_date": "yesterday",
    },
    "reports": {
        "default_report": "purchases",
        "purchases": {
            "enabled": True,
            "export_format": "CSV",
            "generation_timeout_seconds": 300,
            "storage_overrides": {},
        },
    },
    "storage": {
        "base_path": "D:\\{fy_label} DAY WISE REPORTS",
        "report_folder_template": "{fy_label} DAY WISE SALE REPORTS",
        "month_folder_template": "{month_num}.{month_name_upper}",
        "date_folder_template": "{dd}.{mm}.{yyyy}",
        "filename_template": "{dd}.{mm}.{yyyy}.csv",
        "create_missing_folders": True,
        "on_existing_file": "skip",
        "duplicate_suffix_template": " ({n})",
    },
    "timeouts": {
        "window_seconds": 30,
        "control_seconds": 15,
        "menu_seconds": 15,
        "report_seconds": 300,
        "export_seconds": 120,
        "file_seconds": 120,
    },
    "retry": {
        "attempts": 3,
        "delay_seconds": 1.0,
        "backoff": 1.5,
    },
    "logging": {
        "level": "INFO",
        "console_level": "INFO",
        "directory": "logs",
        "filename_template": "automation_{date}.log",
        "retention_days": 30,
    },
}


# --------------------------------------------------------------------------
# Dataclasses
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ApplicationSettings:
    name: str = "NS Retail"
    version: str = ""
    executable_path: str = ""
    working_directory: str = ""
    process_name: str = ""
    main_window_title_regex: str = ""
    ui_backend: str = "uia"
    launch_timeout_seconds: float = 90.0
    connect_timeout_seconds: float = 30.0
    reuse_running_instance: bool = True
    close_when_finished: bool = False


@dataclass(frozen=True)
class LoginSettings:
    enabled: bool = False
    credential_source: str = "none"
    username: str = ""
    username_env_var: str = "NS_RETAIL_USERNAME"
    password_env_var: str = "NS_RETAIL_PASSWORD"
    keyring_service: str = "NS Retail"
    timeout_seconds: float = 60.0


@dataclass(frozen=True)
class DateSettings:
    fiscal_year_start_month: int = 4
    fiscal_year_label_format: str = "{start_year}-{end_year_short}"


@dataclass(frozen=True)
class ScheduleSettings:
    default_report_date: str = "yesterday"


@dataclass(frozen=True)
class StorageSettings:
    base_path: str = ""
    report_folder_template: str = ""
    month_folder_template: str = "{month_num}.{month_name_upper}"
    date_folder_template: str = "{dd}.{mm}.{yyyy}"
    filename_template: str = "{dd}.{mm}.{yyyy}.csv"
    create_missing_folders: bool = True
    on_existing_file: str = "skip"
    duplicate_suffix_template: str = " ({n})"

    def merged_with(self, overrides: dict[str, Any]) -> StorageSettings:
        """Return a copy with per-report overrides applied."""
        if not overrides:
            return self
        known = {f for f in self.__dataclass_fields__}
        unknown = set(overrides) - known
        if unknown:
            raise ConfigError(
                "Unknown storage override(s): " + ", ".join(sorted(unknown))
            )
        return replace(self, **overrides)


@dataclass(frozen=True)
class ReportSettings:
    key: str
    enabled: bool = True
    export_format: str = "CSV"
    generation_timeout_seconds: float = 300.0
    storage_overrides: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TimeoutSettings:
    window_seconds: float = 30.0
    control_seconds: float = 15.0
    menu_seconds: float = 15.0
    report_seconds: float = 300.0
    export_seconds: float = 120.0
    file_seconds: float = 120.0


@dataclass(frozen=True)
class RetrySettings:
    attempts: int = 3
    delay_seconds: float = 1.0
    backoff: float = 1.5


@dataclass(frozen=True)
class LoggingSettings:
    level: str = "INFO"
    console_level: str = "INFO"
    directory: str = "logs"
    filename_template: str = "automation_{date}.log"
    retention_days: int = 30


@dataclass(frozen=True)
class Settings:
    """The whole configuration, already validated."""

    application: ApplicationSettings
    login: LoginSettings
    dates: DateSettings
    schedule: ScheduleSettings
    storage: StorageSettings
    reports: dict[str, ReportSettings]
    default_report: str
    timeouts: TimeoutSettings
    retry: RetrySettings
    logging: LoggingSettings
    source_path: Path | None = None

    def report(self, key: str | None = None) -> ReportSettings:
        """Look up a report definition by key, defaulting to the configured one."""
        name = (key or self.default_report).strip().lower()
        try:
            return self.reports[name]
        except KeyError:
            available = ", ".join(sorted(self.reports)) or "(none configured)"
            raise ConfigError(
                f"No report named '{name}' is configured.",
                hint=f"Configured reports: {available}",
            ) from None

    def storage_for(self, report: ReportSettings) -> StorageSettings:
        """Storage settings for a report, with its overrides applied."""
        return self.storage.merged_with(report.storage_overrides)


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------
def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"Configuration section '{name}' must be an object.")
    return value


def _build(cls: type, data: dict[str, Any], section: str, **extra: Any) -> Any:
    known = set(cls.__dataclass_fields__)
    unknown = set(data) - known - set(extra)
    if unknown:
        logger.warning(
            "Ignoring unknown setting(s) in '%s': %s", section, ", ".join(sorted(unknown))
        )
    accepted = {k: v for k, v in data.items() if k in known}
    accepted.update(extra)
    try:
        return cls(**accepted)
    except TypeError as exc:  # pragma: no cover - defensive
        raise ConfigError(f"Invalid '{section}' section: {exc}") from exc


def find_config_file(explicit: str | Path | None = None) -> Path | None:
    """Locate a configuration file, or return ``None`` if there is none."""
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise ConfigNotFoundError(f"Configuration file '{path}' does not exist.")
        return path

    env_value = os.environ.get(ENV_CONFIG_PATH)
    if env_value:
        path = Path(env_value).expanduser()
        if not path.is_file():
            raise ConfigNotFoundError(
                f"{ENV_CONFIG_PATH} points at '{path}', which does not exist."
            )
        return path

    for candidate in DEFAULT_CONFIG_LOCATIONS:
        if candidate.is_file():
            return candidate
    return None


def load_config(
    path: str | Path | None = None, *, required: bool = False
) -> Settings:
    """Load configuration, falling back to built-in defaults when absent."""
    config_path = find_config_file(path)
    if config_path is None:
        if required:
            raise ConfigNotFoundError()
        logger.warning(
            "No configuration file found - using built-in defaults. "
            "Copy config/config.example.json to config/config.json to change them."
        )
        return build_settings(DEFAULTS, source_path=None)

    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Could not read '{config_path}': {exc}") from exc

    raw = parse_config_text(text, config_path)

    return build_settings(raw, source_path=config_path)


VALID_JSON_ESCAPES = '"\\/bfnrtu'


def escape_lone_backslashes(text: str) -> str:
    """Double any backslash that JSON would reject.

    Windows paths are typed as ``D:\\2026-27 REPORTS`` in a text editor, but JSON
    reads ``\\2`` as an escape sequence and refuses the file. Rather than making
    the user learn JSON escaping, a file that fails only for this reason is
    repaired in memory (and can be repaired on disk with ``--fix-config``).
    """
    out: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            following = text[index + 1]
            if following in VALID_JSON_ESCAPES:
                out.append(char)
                out.append(following)
                index += 2
                continue
            out.append("\\\\")
            index += 1
            continue
        out.append(char)
        index += 1
    return "".join(out)


def parse_config_text(text: str, config_path: Path) -> dict[str, Any]:
    """Parse configuration JSON, repairing un-escaped Windows paths."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        repaired_error: json.JSONDecodeError | None = None
        if "escape" in exc.msg.lower():
            try:
                raw = json.loads(escape_lone_backslashes(text))
            except json.JSONDecodeError as second:
                repaired_error = second
            else:
                logger.warning(
                    "'%s' contains Windows paths written with single backslashes "
                    "(line %d). It was read anyway. Repair the file for good with: "
                    "python -m ns_retail_automation.configure --fix",
                    config_path,
                    exc.lineno,
                )
                return _as_object(raw, config_path)
        problem = repaired_error or exc
        raise ConfigError(
            f"'{config_path}' is not valid JSON (line {problem.lineno}, column "
            f"{problem.colno}: {problem.msg}).",
            hint=(
                "A missing comma, a stray trailing comma, or a Windows path "
                "written with single backslashes is the usual cause. Set paths "
                "with: python -m ns_retail_automation.configure --base-path "
                '"D:\\REPORTS"'
            ),
        ) from problem
    return _as_object(raw, config_path)


def _as_object(raw: Any, config_path: Path) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ConfigError(f"'{config_path}' must contain a JSON object.")
    return raw


def build_settings(data: dict[str, Any], *, source_path: Path | None = None) -> Settings:
    """Turn a (possibly partial) configuration dictionary into validated dataclasses.

    Anything the caller leaves out falls back to :data:`DEFAULTS`.
    """
    unknown_sections = set(data) - set(DEFAULTS)
    data = _deep_merge(DEFAULTS, data)
    if unknown_sections:
        logger.warning(
            "Ignoring unknown configuration section(s): %s",
            ", ".join(sorted(unknown_sections)),
        )

    application = _build(ApplicationSettings, _section(data, "application"), "application")
    login = _build(LoginSettings, _section(data, "login"), "login")
    dates = _build(DateSettings, _section(data, "dates"), "dates")
    schedule = _build(ScheduleSettings, _section(data, "schedule"), "schedule")
    storage = _build(StorageSettings, _section(data, "storage"), "storage")
    timeouts = _build(TimeoutSettings, _section(data, "timeouts"), "timeouts")
    retry = _build(RetrySettings, _section(data, "retry"), "retry")
    logging_settings = _build(LoggingSettings, _section(data, "logging"), "logging")

    reports_section = _section(data, "reports")
    default_report = str(reports_section.get("default_report", "purchases")).lower()
    reports: dict[str, ReportSettings] = {}
    for key, value in reports_section.items():
        if key == "default_report":
            continue
        if not isinstance(value, dict):
            raise ConfigError(f"Report '{key}' must be an object.")
        reports[key.lower()] = _build(
            ReportSettings, value, f"reports.{key}", key=key.lower()
        )

    settings = Settings(
        application=application,
        login=login,
        dates=dates,
        schedule=schedule,
        storage=storage,
        reports=reports,
        default_report=default_report,
        timeouts=timeouts,
        retry=retry,
        logging=logging_settings,
        source_path=source_path,
    )
    validate(settings)
    return settings


def validate(settings: Settings) -> None:
    """Raise :class:`ConfigError` for values that cannot possibly work."""
    if not 1 <= settings.dates.fiscal_year_start_month <= 12:
        raise ConfigError(
            "dates.fiscal_year_start_month must be a month number between 1 and 12."
        )

    action = settings.storage.on_existing_file.lower()
    if action not in VALID_EXISTING_FILE_ACTIONS:
        raise ConfigError(
            f"storage.on_existing_file must be one of "
            f"{', '.join(VALID_EXISTING_FILE_ACTIONS)} (got '{action}')."
        )

    source = settings.login.credential_source.lower()
    if source not in VALID_CREDENTIAL_SOURCES:
        raise ConfigError(
            f"login.credential_source must be one of "
            f"{', '.join(VALID_CREDENTIAL_SOURCES)} (got '{source}')."
        )
    if settings.login.enabled and source == "none":
        raise ConfigError(
            "login.enabled is true but login.credential_source is 'none'.",
            hint=(
                "Set credential_source to 'env' or 'keyring', or set "
                "login.enabled to false and log in to NS Retail by hand."
            ),
        )

    if settings.retry.attempts < 1:
        raise ConfigError("retry.attempts must be at least 1.")

    for name, value in vars(settings.timeouts).items():
        if value <= 0:
            raise ConfigError(f"timeouts.{name} must be greater than zero.")

    if not settings.reports:
        raise ConfigError(
            "No reports are configured.",
            hint="Add a 'reports' section, e.g. \"purchases\": {\"enabled\": true}.",
        )
    if settings.default_report not in settings.reports:
        raise ConfigError(
            f"reports.default_report is '{settings.default_report}' but no such "
            "report is configured.",
            hint="Configured reports: " + ", ".join(sorted(settings.reports)),
        )

    if not settings.storage.filename_template.strip():
        raise ConfigError("storage.filename_template must not be empty.")
