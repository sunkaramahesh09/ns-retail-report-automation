from __future__ import annotations

from datetime import date
from pathlib import Path, PureWindowsPath

import pytest

from ns_retail_automation.config.settings import StorageSettings
from ns_retail_automation.errors import (
    ConfigError,
    DestinationUnavailableError,
    FileAlreadyExistsError,
    FileNotCreatedError,
)
from ns_retail_automation.filesystem.report_storage import ReportStorage, looks_like_windows_path
from ns_retail_automation.utils.dates import DateManager

REPORT_DAY = date(2026, 9, 8)


def _storage(base_path: str, overrides: dict) -> ReportStorage:
    fields = {
        "base_path": base_path,
        "report_folder_template": "{fy_label} DAY WISE SALE REPORTS",
        "month_folder_template": "{month_num}.{month_name_upper}",
        "date_folder_template": "{dd}.{mm}.{yyyy}",
        "filename_template": "{dd}.{mm}.{yyyy}.csv",
        **overrides,
    }
    return ReportStorage(StorageSettings(**fields), DateManager(fiscal_year_start_month=4))


def windows_storage(**overrides) -> ReportStorage:
    return _storage("D:\\2026-27 DAY WISE REPORTS", overrides)


def local_storage(tmp_path: Path, **overrides) -> ReportStorage:
    return _storage(str(tmp_path), overrides)


class TestPathBuilding:
    def test_matches_the_existing_folder_structure(self):
        destination = windows_storage().resolve(REPORT_DAY)
        assert destination.folder == PureWindowsPath(
            r"D:\2026-27 DAY WISE REPORTS"
            "\\2026-27 DAY WISE SALE REPORTS"
            "\\9.SEPTEMBER"
            "\\08.09.2026"
        )
        assert destination.filename == "08.09.2026.csv"

    def test_windows_paths_are_understood_on_macos(self):
        destination = windows_storage().resolve(REPORT_DAY)
        assert isinstance(destination.folder, PureWindowsPath)
        assert not destination.is_native  # cannot be created here
        assert str(destination.path).endswith(r"08.09.2026\08.09.2026.csv")

    def test_fiscal_year_label_flows_into_the_base_path(self):
        storage = _storage("D:\\{fy_label} DAY WISE REPORTS", {})
        assert str(storage.resolve(REPORT_DAY).folder).startswith(
            r"D:\2026-27 DAY WISE REPORTS"
        )

    def test_march_belongs_to_the_previous_financial_year(self):
        folder = str(windows_storage().resolve(date(2026, 3, 15)).folder)
        assert "3.MARCH" in folder
        assert "15.03.2026" in folder

    def test_empty_template_skips_that_folder_level(self):
        storage = windows_storage(report_folder_template="")
        folder = str(storage.resolve(REPORT_DAY).folder)
        assert "SALE REPORTS" not in folder
        assert folder.endswith(r"9.SEPTEMBER\08.09.2026")

    def test_unknown_placeholder_is_reported_clearly(self):
        storage = windows_storage(date_folder_template="{not_a_token}")
        with pytest.raises(ConfigError, match="unknown placeholder"):
            storage.resolve(REPORT_DAY)

    def test_template_producing_an_illegal_name_is_rejected(self):
        storage = windows_storage(date_folder_template="{dd}/{mm}")
        with pytest.raises(ConfigError, match="does not allow"):
            storage.resolve(REPORT_DAY)

    def test_empty_base_path_is_rejected(self):
        storage = windows_storage(base_path="")
        with pytest.raises(ConfigError, match="base_path is empty"):
            storage.resolve(REPORT_DAY)

    def test_filename_template_is_configurable(self):
        storage = windows_storage(filename_template="PURCHASES_{yyyy}-{mm}-{dd}.csv")
        assert storage.resolve(REPORT_DAY).filename == "PURCHASES_2026-09-08.csv"


class TestFolderCreation:
    def test_missing_folders_are_created(self, tmp_path):
        storage = local_storage(tmp_path)
        destination = storage.resolve(REPORT_DAY)
        folder = storage.ensure_folder(destination)
        assert folder.is_dir()
        assert folder.name == "08.09.2026"
        assert folder.parent.name == "9.SEPTEMBER"

    def test_existing_folder_is_reused(self, tmp_path):
        storage = local_storage(tmp_path)
        destination = storage.resolve(REPORT_DAY)
        first = storage.ensure_folder(destination)
        second = storage.ensure_folder(destination)
        assert first == second

    def test_creation_can_be_switched_off(self, tmp_path):
        storage = local_storage(tmp_path, create_missing_folders=False)
        destination = storage.resolve(REPORT_DAY)
        with pytest.raises(DestinationUnavailableError, match="does not exist"):
            storage.ensure_folder(destination)

    def test_windows_path_cannot_be_created_on_macos(self):
        storage = windows_storage()
        with pytest.raises(DestinationUnavailableError, match="Windows path"):
            storage.ensure_folder(storage.resolve(REPORT_DAY))

    def test_file_where_a_folder_should_be(self, tmp_path):
        storage = local_storage(tmp_path)
        destination = storage.resolve(REPORT_DAY)
        folder = Path(destination.folder)
        folder.parent.mkdir(parents=True, exist_ok=True)
        folder.write_text("not a folder")
        with pytest.raises(DestinationUnavailableError, match="is a file"):
            storage.ensure_folder(destination)


class TestExistingFiles:
    def _prepare(self, tmp_path, **overrides):
        storage = local_storage(tmp_path, **overrides)
        destination = storage.resolve(REPORT_DAY)
        storage.ensure_folder(destination)
        return storage, destination

    def test_no_existing_file_means_create(self, tmp_path):
        storage, destination = self._prepare(tmp_path)
        plan = storage.plan(destination)
        assert plan.action == "create"
        assert plan.existing is False

    def test_default_is_the_safe_skip(self, tmp_path):
        storage, destination = self._prepare(tmp_path)
        Path(destination.path).write_text("old report")
        plan = storage.plan(destination)
        assert plan.action == "skip"
        with pytest.raises(FileAlreadyExistsError):
            storage.guard_existing(plan)
        # The existing report is untouched.
        assert Path(destination.path).read_text() == "old report"

    def test_overwrite_is_opt_in(self, tmp_path):
        storage, destination = self._prepare(tmp_path)
        Path(destination.path).write_text("old report")
        plan = storage.plan(destination, on_existing="overwrite")
        assert plan.action == "overwrite"
        assert plan.path == Path(destination.path)

    def test_duplicate_picks_the_next_free_name(self, tmp_path):
        storage, destination = self._prepare(tmp_path)
        Path(destination.path).write_text("old report")
        plan = storage.plan(destination, on_existing="duplicate")
        assert plan.action == "duplicate"
        assert plan.path.name == "08.09.2026 (2).csv"

    def test_duplicate_keeps_counting(self, tmp_path):
        storage, destination = self._prepare(tmp_path)
        Path(destination.path).write_text("first")
        Path(destination.path).with_name("08.09.2026 (2).csv").write_text("second")
        plan = storage.plan(destination, on_existing="duplicate")
        assert plan.path.name == "08.09.2026 (3).csv"

    def test_duplicate_suffix_is_configurable(self, tmp_path):
        storage, destination = self._prepare(tmp_path, duplicate_suffix_template="_v{n}")
        Path(destination.path).write_text("first")
        plan = storage.plan(destination, on_existing="duplicate")
        assert plan.path.name == "08.09.2026_v2.csv"

    def test_ask_defers_the_decision(self, tmp_path):
        storage, destination = self._prepare(tmp_path)
        Path(destination.path).write_text("old report")
        assert storage.plan(destination, on_existing="ask").action == "ask"


class TestVerification:
    def test_a_written_file_verifies(self, tmp_path):
        target = tmp_path / "08.09.2026.csv"
        target.write_text("Item,Qty\nRice,10\n")
        assert local_storage(tmp_path).verify_created(target) == target

    def test_missing_file_is_reported(self, tmp_path):
        with pytest.raises(FileNotCreatedError, match="does not exist"):
            local_storage(tmp_path).verify_created(tmp_path / "nope.csv")

    def test_empty_file_is_reported(self, tmp_path):
        target = tmp_path / "08.09.2026.csv"
        target.write_text("")
        with pytest.raises(FileNotCreatedError, match="empty"):
            local_storage(tmp_path).verify_created(target)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("D:\\REPORTS", True),
        ("\\\\server\\share\\reports", True),
        ("C:/Reports", True),
        ("/Users/mahesh/reports", False),
        ("reports", False),
    ],
)
def test_windows_path_detection(value, expected):
    assert looks_like_windows_path(value) is expected
