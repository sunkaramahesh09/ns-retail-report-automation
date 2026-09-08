"""Logging setup.

One log file per day (``logs/automation_2026-09-08.log``) plus readable console
output.  The log is what we will use to work out why an unattended run failed,
so every major action goes into it.
"""

from __future__ import annotations

import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from .config.settings import LoggingSettings

FILE_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
CONSOLE_FORMAT = "%(message)s"
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

ROOT_LOGGER_NAME = "ns_retail_automation"


class _ConsoleFormatter(logging.Formatter):
    """Prefixes anything above INFO so problems stand out in the terminal."""

    PREFIXES = {
        logging.WARNING: "[WARNING] ",
        logging.ERROR: "[ERROR] ",
        logging.CRITICAL: "[ERROR] ",
    }

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        prefix = self.PREFIXES.get(record.levelno, "")
        return f"{prefix}{message}"


def setup_logging(
    settings: LoggingSettings | None = None,
    *,
    verbose: bool = False,
    quiet: bool = False,
    log_directory: str | Path | None = None,
) -> Path | None:
    """Configure logging and return the path of the log file (if any)."""
    settings = settings or LoggingSettings()

    logger = logging.getLogger(ROOT_LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    for handler in list(logger.handlers):  # make repeated calls harmless
        logger.removeHandler(handler)
        handler.close()

    console_level = logging.DEBUG if verbose else _level(settings.console_level)
    if quiet:
        console_level = logging.WARNING
    console = logging.StreamHandler(stream=sys.stdout)
    console.setLevel(console_level)
    console.setFormatter(_ConsoleFormatter(CONSOLE_FORMAT))
    logger.addHandler(console)

    directory = Path(log_directory or settings.directory)
    log_path: Path | None = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        log_path = directory / settings.filename_template.format(
            date=date.today().isoformat(),
            datetime=datetime.now().strftime("%Y-%m-%d_%H-%M-%S"),
        )
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG if verbose else _level(settings.level))
        file_handler.setFormatter(logging.Formatter(FILE_FORMAT, TIME_FORMAT))
        logger.addHandler(file_handler)
    except OSError as exc:
        logger.warning(
            "Could not write to the log folder '%s' (%s) - logging to the screen only.",
            directory,
            exc,
        )
        return None

    _prune_old_logs(directory, settings)
    return log_path


def get_logger(name: str = "") -> logging.Logger:
    """Return a logger under the application's root logger."""
    if not name or name == ROOT_LOGGER_NAME:
        return logging.getLogger(ROOT_LOGGER_NAME)
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{name}")


def _level(name: str) -> int:
    value = logging.getLevelName(str(name).upper())
    return value if isinstance(value, int) else logging.INFO


def _prune_old_logs(directory: Path, settings: LoggingSettings) -> None:
    """Delete log files older than the retention period (0 disables pruning)."""
    days = settings.retention_days
    if days <= 0:
        return
    cutoff = datetime.now() - timedelta(days=days)
    prefix = settings.filename_template.split("{")[0]
    for path in directory.glob(f"{prefix}*"):
        try:
            if datetime.fromtimestamp(path.stat().st_mtime) < cutoff:
                path.unlink()
        except OSError:  # pragma: no cover - a locked file is not worth failing over
            continue
