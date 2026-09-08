from __future__ import annotations

from datetime import date

import pytest

from ns_retail_automation.errors import ConfigError
from ns_retail_automation.utils.dates import DateManager, month_name, parse_date, parse_date_range


class TestKeywords:
    def test_today(self, dates):
        assert dates.resolve("today", today=date(2026, 9, 9)) == date(2026, 9, 9)

    def test_yesterday_is_the_default_use_case(self, dates):
        # Running on 09-09-2026 must report on 08-09-2026.
        assert dates.resolve("yesterday", today=date(2026, 9, 9)) == date(2026, 9, 8)

    def test_yesterday_crosses_a_month_boundary(self, dates):
        assert dates.resolve("yesterday", today=date(2026, 9, 1)) == date(2026, 8, 31)

    def test_yesterday_crosses_a_year_boundary(self, dates):
        assert dates.resolve("yesterday", today=date(2026, 1, 1)) == date(2025, 12, 31)

    def test_keywords_are_case_insensitive(self, dates):
        assert dates.resolve("YESTERDAY", today=date(2026, 9, 9)) == date(2026, 9, 8)


class TestWrittenDates:
    @pytest.mark.parametrize(
        "written",
        ["2026-09-08", "08-09-2026", "08.09.2026", "08/09/2026", "8-9-2026"],
    )
    def test_supported_formats(self, dates, written):
        assert dates.resolve(written) == date(2026, 9, 8)

    def test_day_first_is_assumed(self, dates):
        # 03-04-2026 is 3 April, not 4 March.
        assert dates.resolve("03-04-2026") == date(2026, 4, 3)

    def test_impossible_date_is_rejected(self, dates):
        with pytest.raises(ConfigError, match="not a real calendar date"):
            dates.resolve("31-02-2026")

    def test_nonsense_is_rejected_with_a_helpful_message(self, dates):
        with pytest.raises(ConfigError) as excinfo:
            dates.resolve("last tuesday")
        assert "yesterday" in (excinfo.value.hint or "")

    def test_empty_is_rejected(self, dates):
        with pytest.raises(ConfigError):
            dates.resolve("")


class TestRanges:
    def test_single_date_is_a_one_item_range(self):
        assert parse_date_range("08-09-2026") == [date(2026, 9, 8)]

    def test_inclusive_range(self):
        days = parse_date_range("01-09-2026..03-09-2026")
        assert days == [date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)]

    def test_keywords_work_in_a_range(self):
        days = parse_date_range("yesterday..today", today=date(2026, 9, 9))
        assert days == [date(2026, 9, 8), date(2026, 9, 9)]

    def test_backwards_range_is_rejected(self):
        with pytest.raises(ConfigError, match="before the start date"):
            parse_date_range("03-09-2026..01-09-2026")


class TestFiscalYear:
    def test_indian_financial_year_after_april(self, dates):
        fy = dates.fiscal_year(date(2026, 9, 8))
        assert (fy.start, fy.end) == (date(2026, 4, 1), date(2027, 3, 31))
        assert fy.label == "2026-27"

    def test_indian_financial_year_before_april(self, dates):
        fy = dates.fiscal_year(date(2026, 3, 31))
        assert (fy.start, fy.end) == (date(2025, 4, 1), date(2026, 3, 31))
        assert fy.label == "2025-26"

    def test_first_day_of_the_financial_year(self, dates):
        fy = dates.fiscal_year(date(2026, 4, 1))
        assert fy.label == "2026-27"

    def test_calendar_year_configuration(self):
        manager = DateManager(fiscal_year_start_month=1)
        fy = manager.fiscal_year(date(2026, 9, 8))
        assert (fy.start, fy.end) == (date(2026, 1, 1), date(2026, 12, 31))
        assert fy.label == "2026-26"

    def test_july_start_configuration(self):
        manager = DateManager(fiscal_year_start_month=7)
        assert manager.fiscal_year(date(2026, 6, 30)).label == "2025-26"
        assert manager.fiscal_year(date(2026, 7, 1)).label == "2026-27"

    def test_label_format_is_configurable(self):
        manager = DateManager(
            fiscal_year_start_month=4, fiscal_year_label_format="FY{start_year}/{end_year}"
        )
        assert manager.fiscal_year(date(2026, 9, 8)).label == "FY2026/2027"

    def test_invalid_start_month_is_rejected(self):
        with pytest.raises(ConfigError):
            DateManager(fiscal_year_start_month=13)


class TestTokens:
    def test_tokens_for_a_september_date(self, dates):
        tokens = dates.tokens(date(2026, 9, 8))
        assert tokens["dd"] == "08"
        assert tokens["mm"] == "09"
        assert tokens["yyyy"] == "2026"
        assert tokens["month_num"] == "9"
        assert tokens["month_name_upper"] == "SEPTEMBER"
        assert tokens["fy_label"] == "2026-27"

    def test_month_names_do_not_depend_on_the_machine_locale(self):
        assert month_name(1) == "JANUARY"
        assert month_name(12) == "DECEMBER"

    def test_month_name_out_of_range(self):
        with pytest.raises(ConfigError):
            month_name(0)


def test_parse_date_accepts_a_date_object():
    assert parse_date(date(2026, 9, 8)) == date(2026, 9, 8)
