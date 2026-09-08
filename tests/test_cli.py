"""CLI behaviour that must work on macOS (no NS Retail involved)."""

from __future__ import annotations

import json

import pytest

from ns_retail_automation.main import EXIT_CONFIG, EXIT_FAILED, EXIT_OK, main


@pytest.fixture
def project_config(tmp_path, monkeypatch):
    """A configuration whose reports land inside tmp_path."""
    config = {
        "application": {"executable_path": "", "process_name": "NSRetail.exe"},
        "storage": {"base_path": str(tmp_path / "REPORTS")},
        "logging": {"directory": str(tmp_path / "logs")},
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return str(path)


class TestDryRun:
    def test_dry_run_reports_date_folder_and_filename(self, project_config, capsys):
        code = main(["--report", "purchases", "--date", "08-09-2026", "--dry-run", "--config", project_config])
        out = capsys.readouterr().out
        assert code == EXIT_OK
        assert "DRY RUN" in out
        assert "08-09-2026" in out
        assert "9.SEPTEMBER" in out
        assert "08.09.2026.csv" in out

    def test_dry_run_defaults_to_yesterday(self, project_config, capsys):
        assert main(["--dry-run", "--config", project_config]) == EXIT_OK
        assert "Report      : purchases" in capsys.readouterr().out

    def test_dry_run_lists_what_is_not_mapped_yet(self, project_config, capsys, tmp_path):
        main(["--dry-run", "--config", project_config, "--selectors", "config/selectors.example.json"])
        out = capsys.readouterr().out
        assert "Not mapped to NS Retail yet" in out
        assert "open_reports" in out

    def test_dry_run_creates_no_folders(self, project_config, tmp_path):
        main(["--dry-run", "--config", project_config])
        assert not (tmp_path / "REPORTS").exists()

    def test_bad_date_is_a_configuration_error(self, project_config, capsys):
        code = main(["--date", "not-a-date", "--dry-run", "--config", project_config])
        assert code == EXIT_CONFIG
        assert "[ERROR]" in capsys.readouterr().err

    def test_date_range_is_rejected_for_now(self, project_config, capsys):
        code = main(["--date", "01-09-2026..03-09-2026", "--dry-run", "--config", project_config])
        assert code == EXIT_CONFIG
        assert "one date at a time" in capsys.readouterr().err

    def test_unknown_report_is_rejected(self, project_config, capsys):
        code = main(["--report", "sales", "--dry-run", "--config", project_config])
        assert code == EXIT_CONFIG
        assert "purchases" in capsys.readouterr().err

    def test_base_path_can_be_overridden(self, project_config, capsys):
        main(["--dry-run", "--config", project_config, "--base-path", "Z:\\OTHER"])
        assert "Z:\\OTHER" in capsys.readouterr().out


class TestOtherCommands:
    def test_check_summarises_environment_and_mapping(self, project_config, capsys):
        assert main(["--check", "--config", project_config]) == EXIT_OK
        out = capsys.readouterr().out
        assert "Environment" in out
        assert "NS Retail control mapping" in out
        assert "Steps still to map" in out

    def test_list_reports(self, project_config, capsys):
        assert main(["--list-reports", "--config", project_config]) == EXIT_OK
        assert "purchases" in capsys.readouterr().out

    def test_missing_config_file_is_reported(self, tmp_path, capsys):
        code = main(["--dry-run", "--config", str(tmp_path / "nope.json")])
        assert code == EXIT_CONFIG
        assert "does not exist" in capsys.readouterr().err

    def test_a_real_run_on_macos_fails_with_a_clear_message(self, project_config, capsys):
        code = main(["--report", "purchases", "--date", "08-09-2026", "--config", project_config])
        assert code == EXIT_FAILED
        err = capsys.readouterr().err
        assert "[ERROR]" in err
        assert "Windows" in err


class TestLogging:
    def test_a_log_file_is_written(self, project_config, tmp_path):
        main(["--dry-run", "--config", project_config])
        logs = list((tmp_path / "logs").glob("automation_*.log"))
        assert len(logs) == 1
