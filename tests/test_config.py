from __future__ import annotations

import json

import pytest

from ns_retail_automation.config.settings import (
    DEFAULTS,
    build_settings,
    find_config_file,
    load_config,
)
from ns_retail_automation.errors import ConfigError, ConfigNotFoundError


def write_config(tmp_path, data) -> str:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


class TestLoading:
    def test_defaults_are_valid(self):
        settings = build_settings(DEFAULTS)
        assert settings.default_report == "purchases"
        assert settings.schedule.default_report_date == "yesterday"
        assert settings.storage.on_existing_file == "skip"
        assert settings.login.enabled is False

    def test_the_shipped_example_file_loads(self):
        settings = load_config("config/config.example.json")
        assert settings.application.name == "NS Retail"
        assert settings.storage.filename_template == "{dd}.{mm}.{yyyy}.csv"
        assert settings.source_path is not None

    def test_user_values_override_defaults_section_by_section(self, tmp_path):
        path = write_config(tmp_path, {"storage": {"base_path": "E:\\REPORTS"}})
        settings = load_config(path)
        assert settings.storage.base_path == "E:\\REPORTS"
        # Untouched keys keep their default.
        assert settings.storage.filename_template == "{dd}.{mm}.{yyyy}.csv"

    def test_missing_file_falls_back_to_defaults(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        settings = load_config()
        assert settings.source_path is None
        assert settings.default_report == "purchases"

    def test_missing_file_can_be_made_fatal(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ConfigNotFoundError):
            load_config(required=True)

    def test_explicit_missing_path_is_an_error(self, tmp_path):
        with pytest.raises(ConfigNotFoundError):
            load_config(tmp_path / "nowhere.json")

    def test_broken_json_names_the_line(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text('{"storage": {"base_path": "D:\\\\R",}}', encoding="utf-8")
        with pytest.raises(ConfigError, match="not valid JSON"):
            load_config(path)

    def test_environment_variable_is_honoured(self, tmp_path, monkeypatch):
        path = write_config(tmp_path, {"storage": {"base_path": "F:\\FROM ENV"}})
        monkeypatch.setenv("NS_RETAIL_CONFIG", path)
        assert load_config().storage.base_path == "F:\\FROM ENV"

    def test_config_is_discovered_in_the_working_directory(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "config.json").write_text(
            json.dumps({"storage": {"base_path": "G:\\FOUND"}}), encoding="utf-8"
        )
        assert find_config_file() is not None
        assert load_config().storage.base_path == "G:\\FOUND"

    def test_unknown_keys_are_ignored_not_fatal(self, tmp_path, caplog):
        path = write_config(tmp_path, {"storage": {"colour": "blue"}, "nonsense": {}})
        settings = load_config(path)
        assert settings.storage.base_path  # still usable


class TestValidation:
    def test_bad_existing_file_action(self, tmp_path):
        path = write_config(tmp_path, {"storage": {"on_existing_file": "delete_everything"}})
        with pytest.raises(ConfigError, match="on_existing_file"):
            load_config(path)

    def test_bad_fiscal_year_month(self, tmp_path):
        path = write_config(tmp_path, {"dates": {"fiscal_year_start_month": 0}})
        with pytest.raises(ConfigError, match="fiscal_year_start_month"):
            load_config(path)

    def test_login_enabled_without_a_credential_source_is_rejected(self, tmp_path):
        path = write_config(tmp_path, {"login": {"enabled": True, "credential_source": "none"}})
        with pytest.raises(ConfigError, match="credential_source"):
            load_config(path)

    def test_login_enabled_with_environment_credentials_is_accepted(self, tmp_path):
        path = write_config(tmp_path, {"login": {"enabled": True, "credential_source": "env"}})
        assert load_config(path).login.enabled is True

    def test_default_report_must_exist(self, tmp_path):
        path = write_config(tmp_path, {"reports": {"default_report": "sales"}})
        with pytest.raises(ConfigError, match="no such"):
            load_config(path)

    def test_zero_timeout_is_rejected(self, tmp_path):
        path = write_config(tmp_path, {"timeouts": {"window_seconds": 0}})
        with pytest.raises(ConfigError, match="greater than zero"):
            load_config(path)

    def test_empty_filename_template_is_rejected(self, tmp_path):
        path = write_config(tmp_path, {"storage": {"filename_template": "  "}})
        with pytest.raises(ConfigError, match="filename_template"):
            load_config(path)


class TestReportLookup:
    def test_lookup_by_key(self, settings):
        assert settings.report("purchases").enabled is True

    def test_default_lookup(self, settings):
        assert settings.report().key == "purchases"

    def test_unknown_report_lists_what_is_available(self, settings):
        with pytest.raises(ConfigError) as excinfo:
            settings.report("weekly-sales")
        assert "purchases" in (excinfo.value.hint or "")

    def test_storage_overrides_apply_to_one_report_only(self, make_settings):
        settings = make_settings(
            reports={
                "default_report": "purchases",
                "purchases": {
                    "enabled": True,
                    "storage_overrides": {"report_folder_template": "PURCHASE REPORTS"},
                },
            }
        )
        report = settings.report("purchases")
        assert settings.storage_for(report).report_folder_template == "PURCHASE REPORTS"
        # The global default is untouched.
        assert "SALE REPORTS" in settings.storage.report_folder_template

    def test_unknown_storage_override_is_rejected(self, make_settings):
        settings = make_settings(
            reports={
                "default_report": "purchases",
                "purchases": {"storage_overrides": {"colour": "blue"}},
            }
        )
        with pytest.raises(ConfigError, match="Unknown storage override"):
            settings.storage_for(settings.report("purchases"))


class TestWindowsPathTolerance:
    """A Windows path typed by hand breaks JSON; the loader repairs it."""

    def test_single_backslash_path_is_repaired(self, tmp_path, caplog):
        path = tmp_path / "config.json"
        path.write_text(
            '{"storage": {"base_path": "D:\\2026-27 DAY WISE REPORTS"}}', encoding="utf-8"
        )
        settings = load_config(path)
        assert settings.storage.base_path == "D:\\2026-27 DAY WISE REPORTS"

    def test_correctly_escaped_file_is_untouched(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(
            '{"storage": {"base_path": "D:\\\\REPORTS", "filename_template": "a\\nb.csv"}}',
            encoding="utf-8",
        )
        settings = load_config(path)
        assert settings.storage.base_path == "D:\\REPORTS"
        assert settings.storage.filename_template == "a\nb.csv"

    def test_a_genuine_syntax_error_is_still_an_error(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text('{"storage": {"base_path": "D:\\R",}}', encoding="utf-8")
        with pytest.raises(ConfigError, match="not valid JSON"):
            load_config(path)

    def test_escaping_helper(self):
        from ns_retail_automation.config.settings import escape_lone_backslashes

        assert escape_lone_backslashes(r'"D:\2026"') == r'"D:\\2026"'
        assert escape_lone_backslashes(r'"D:\\ok"') == r'"D:\\ok"'
        assert escape_lone_backslashes('"a\\nb"') == '"a\\nb"'


class TestConfigureTool:
    def test_setting_a_windows_path_writes_valid_json(self, tmp_path):
        from ns_retail_automation.configure import main as configure_main

        path = tmp_path / "config.json"
        code = configure_main(
            ["--config", str(path), "--base-path", "D:\\2026-27 DAY WISE REPORTS"]
        )
        assert code == 0
        # The file must now be loadable without any repair.
        assert json.loads(path.read_text())["storage"]["base_path"] == (
            "D:\\2026-27 DAY WISE REPORTS"
        )
        assert load_config(path).storage.base_path == "D:\\2026-27 DAY WISE REPORTS"

    def test_exe_also_sets_the_process_name(self, tmp_path):
        from ns_retail_automation.configure import main as configure_main

        path = tmp_path / "config.json"
        configure_main(["--config", str(path), "--exe", "C:\\NS Retail\\NSRetail.exe"])
        settings = load_config(path)
        assert settings.application.executable_path == "C:\\NS Retail\\NSRetail.exe"
        assert settings.application.process_name == "NSRetail.exe"

    def test_fix_rewrites_a_hand_edited_file(self, tmp_path):
        from ns_retail_automation.configure import main as configure_main

        path = tmp_path / "config.json"
        path.write_text('{"storage": {"base_path": "D:\\REPORTS"}}', encoding="utf-8")
        assert configure_main(["--config", str(path), "--fix"]) == 0
        # Now valid JSON on disk, and the backup keeps the original.
        assert json.loads(path.read_text())["storage"]["base_path"] == "D:\\REPORTS"
        assert (tmp_path / "config.json.bak").exists()

    def test_invalid_value_is_refused_before_writing(self, tmp_path, capsys):
        from ns_retail_automation.configure import main as configure_main

        path = tmp_path / "config.json"
        code = configure_main(["--config", str(path), "--default-date", "yesterday"])
        assert code == 0
        before = path.read_text()
        code = configure_main(["--config", str(path), "--on-existing", "skip"])
        assert code == 0
        assert path.is_file() and before  # unchanged file is still valid JSON
