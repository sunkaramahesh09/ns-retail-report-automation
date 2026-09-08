"""Destination folder and filename logic.

All of this is pure path arithmetic - it never touches NS Retail - so it is
fully testable on macOS.  Windows-style paths such as ``D:\\REPORTS`` are
understood on macOS too (as :class:`~pathlib.PureWindowsPath`) so that
``--dry-run`` prints exactly what the Windows PC will use; only the actual
folder creation requires the matching operating system.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePath, PureWindowsPath

from ..config.settings import StorageSettings
from ..errors import (
    ConfigError,
    DestinationUnavailableError,
    FileAlreadyExistsError,
    FileNotCreatedError,
    StorageError,
)
from ..utils.dates import DateManager

logger = logging.getLogger(__name__)

_WINDOWS_PATH_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")
_ILLEGAL_NAME_CHARS = re.compile(r'[<>:"/\\|?*]')


def looks_like_windows_path(value: str) -> bool:
    """True for ``D:\\...``, ``\\\\server\\share`` or any path with a backslash."""
    return bool(_WINDOWS_PATH_RE.match(value)) or "\\" in value


def render(template: str, tokens: dict[str, object], *, where: str) -> str:
    """Fill a folder/filename template, reporting unknown tokens clearly."""
    try:
        return template.format(**tokens)
    except KeyError as exc:
        raise ConfigError(
            f"{where} uses unknown placeholder {{{exc.args[0]}}}.",
            hint="Available placeholders: " + ", ".join(sorted(tokens)),
        ) from exc
    except (IndexError, ValueError) as exc:
        raise ConfigError(f"{where} is not a valid template: {exc}") from exc


@dataclass(frozen=True)
class ReportDestination:
    """Where one report should be written."""

    folder: PurePath
    filename: str
    report_date: date

    @property
    def path(self) -> PurePath:
        return self.folder / self.filename

    @property
    def is_native(self) -> bool:
        """True when this path can actually be created on this computer."""
        return isinstance(self.folder, Path)

    def as_concrete(self) -> Path:
        if not self.is_native:
            raise DestinationUnavailableError(
                f"'{self.folder}' is a Windows path and cannot be created on "
                f"{os.name!r} systems.",
                hint="Run the automation on the Windows PC where NS Retail is installed.",
            )
        return Path(self.folder)


@dataclass(frozen=True)
class FilePlan:
    """What to do about an already existing destination file."""

    action: str  # "create" | "skip" | "overwrite" | "duplicate" | "ask"
    path: PurePath
    existing: bool
    reason: str


class ReportStorage:
    """Builds destination folders/filenames and manages existing files."""

    def __init__(self, settings: StorageSettings, dates: DateManager) -> None:
        self.settings = settings
        self.dates = dates

    # -- path building ---------------------------------------------------
    def _path_class(self) -> type[PurePath]:
        if os.name == "nt":
            return Path
        if looks_like_windows_path(self.settings.base_path):
            return PureWindowsPath
        return Path

    def base_path(self, day: date) -> PurePath:
        tokens = self.dates.tokens(day)
        base = render(
            self.settings.base_path, tokens, where="storage.base_path"
        ).strip()
        if not base:
            raise ConfigError(
                "storage.base_path is empty.",
                hint="Set it to the folder holding the day-wise reports, e.g. "
                'D:\\\\2026-27 DAY WISE REPORTS',
            )
        return self._path_class()(base)

    def resolve(self, day: date, *, filename: str | None = None) -> ReportDestination:
        """Work out the folder and filename for ``day``."""
        tokens = self.dates.tokens(day)
        folder = self.base_path(day)

        for template, where in (
            (self.settings.report_folder_template, "storage.report_folder_template"),
            (self.settings.month_folder_template, "storage.month_folder_template"),
            (self.settings.date_folder_template, "storage.date_folder_template"),
        ):
            if not template.strip():
                continue  # an empty template simply means "no folder level here"
            name = render(template, tokens, where=where).strip()
            _check_name(name, where)
            folder = folder / name

        name = filename or render(
            self.settings.filename_template, tokens, where="storage.filename_template"
        ).strip()
        _check_name(name, "storage.filename_template")
        return ReportDestination(folder=folder, filename=name, report_date=day)

    # -- folders ---------------------------------------------------------
    def ensure_folder(self, destination: ReportDestination, *, create: bool | None = None) -> Path:
        """Create the destination folder if allowed, and return it."""
        folder = destination.as_concrete()
        should_create = self.settings.create_missing_folders if create is None else create

        if folder.exists():
            if not folder.is_dir():
                raise DestinationUnavailableError(
                    f"'{folder}' exists but is a file, not a folder."
                )
            return folder

        if not should_create:
            raise DestinationUnavailableError(
                f"The folder '{folder}' does not exist.",
                hint=(
                    "Create it by hand, or set storage.create_missing_folders to "
                    "true in the configuration."
                ),
            )

        root = _existing_ancestor(folder)
        if root is None:
            raise DestinationUnavailableError(
                f"None of the parent folders of '{folder}' exist.",
                hint="Check that the drive is connected and storage.base_path is correct.",
            )
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise DestinationUnavailableError(
                f"Could not create the folder '{folder}': {exc}"
            ) from exc
        logger.info("Created destination folder: %s", folder)
        return folder

    # -- existing files --------------------------------------------------
    def plan(self, destination: ReportDestination, *, on_existing: str | None = None) -> FilePlan:
        """Decide what to do if the destination file already exists."""
        action = (on_existing or self.settings.on_existing_file).lower()
        path = destination.path

        if not destination.is_native:
            # Cannot inspect a Windows path from macOS; report the intent only.
            return FilePlan(
                action="create",
                path=path,
                existing=False,
                reason="Existing-file check happens on the Windows PC.",
            )

        concrete = Path(path)
        if not concrete.exists():
            return FilePlan(action="create", path=concrete, existing=False, reason="No file exists yet.")

        if action == "overwrite":
            return FilePlan(
                action="overwrite",
                path=concrete,
                existing=True,
                reason="storage.on_existing_file is 'overwrite'.",
            )
        if action == "duplicate":
            new_path = self.next_available_path(concrete)
            return FilePlan(
                action="duplicate",
                path=new_path,
                existing=True,
                reason=f"'{concrete.name}' exists; writing '{new_path.name}' instead.",
            )
        if action == "ask":
            return FilePlan(
                action="ask",
                path=concrete,
                existing=True,
                reason=f"'{concrete.name}' already exists.",
            )
        return FilePlan(
            action="skip",
            path=concrete,
            existing=True,
            reason=f"'{concrete.name}' already exists and on_existing_file is 'skip'.",
        )

    def next_available_path(self, path: Path, *, limit: int = 999) -> Path:
        """``08.09.2026.csv`` -> ``08.09.2026 (2).csv`` -> ``(3)`` ..."""
        for index in range(2, limit + 1):
            suffix = render(
                self.settings.duplicate_suffix_template,
                {"n": index},
                where="storage.duplicate_suffix_template",
            )
            candidate = path.with_name(f"{path.stem}{suffix}{path.suffix}")
            if not candidate.exists():
                return candidate
        raise StorageError(
            f"Could not find a free filename for '{path.name}' after {limit} tries."
        )

    def guard_existing(self, plan: FilePlan) -> None:
        """Raise the friendly error for a plan the caller must not proceed with."""
        if plan.action == "skip":
            raise FileAlreadyExistsError(
                f"A report already exists at '{plan.path}'.",
                hint=(
                    "Nothing was changed. Re-run with --on-existing overwrite or "
                    "--on-existing duplicate if you want a new copy."
                ),
            )

    # -- verification ----------------------------------------------------
    def verify_created(self, path: str | PurePath, *, min_size: int = 1) -> Path:
        """Confirm the export really produced a file."""
        concrete = Path(path)
        if not concrete.exists():
            raise FileNotCreatedError(
                f"NS Retail reported success but '{concrete}' does not exist."
            )
        size = concrete.stat().st_size
        if size < min_size:
            raise FileNotCreatedError(
                f"'{concrete}' was created but is empty (0 bytes).",
                hint="The report probably contained no data for that date.",
            )
        logger.info("Verified report file: %s (%d bytes)", concrete, size)
        return concrete


def _check_name(name: str, where: str) -> None:
    if not name:
        raise ConfigError(f"{where} produced an empty name.")
    # Folder/file names are single path components: a separator here means the
    # template is wrong (or the value contains an illegal character).
    illegal = set(_ILLEGAL_NAME_CHARS.findall(name))
    if illegal:
        raise ConfigError(
            f"{where} produced '{name}', which contains character(s) Windows does "
            f"not allow in a name: {' '.join(sorted(illegal))}",
        )


def _existing_ancestor(folder: Path) -> Path | None:
    for candidate in [folder, *folder.parents]:
        if candidate.exists():
            return candidate
    return None
