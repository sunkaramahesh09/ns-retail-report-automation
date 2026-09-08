"""Date logic for report scheduling and folder naming.

This module is intentionally free of any UI or platform dependency so it can be
developed and tested on macOS.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from ..errors import ConfigError

# Fixed English month names.  We deliberately do NOT use ``calendar.month_name``
# or ``strftime('%B')`` because those follow the machine locale and would
# produce different folder names on differently configured PCs.
MONTH_NAMES = (
    "JANUARY",
    "FEBRUARY",
    "MARCH",
    "APRIL",
    "MAY",
    "JUNE",
    "JULY",
    "AUGUST",
    "SEPTEMBER",
    "OCTOBER",
    "NOVEMBER",
    "DECEMBER",
)

_KEYWORDS = {"today", "yesterday"}

# Accepted written date formats, most explicit first.
_DATE_PATTERNS = (
    (re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$"), ("y", "m", "d")),  # 2026-09-08
    (re.compile(r"^(\d{1,2})-(\d{1,2})-(\d{4})$"), ("d", "m", "y")),  # 08-09-2026
    (re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$"), ("d", "m", "y")),  # 08.09.2026
    (re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$"), ("d", "m", "y")),  # 08/09/2026
)


def month_name(month: int) -> str:
    """Return the uppercase English month name for ``month`` (1-12)."""
    if not 1 <= month <= 12:
        raise ConfigError(f"Month must be between 1 and 12, got {month}.")
    return MONTH_NAMES[month - 1]


def parse_date(value: str, *, today: date | None = None) -> date:
    """Parse a user supplied date.

    Accepts the keywords ``today`` / ``yesterday`` and the written formats
    ``YYYY-MM-DD``, ``DD-MM-YYYY``, ``DD.MM.YYYY`` and ``DD/MM/YYYY``.

    Note that day-first is assumed for the ambiguous formats because that is how
    dates are written in the existing report folders.
    """
    if isinstance(value, date):  # tolerate an already-parsed date
        return value

    raw = (value or "").strip()
    if not raw:
        raise ConfigError("No date was supplied.")

    today = today or date.today()
    keyword = raw.lower()
    if keyword == "today":
        return today
    if keyword == "yesterday":
        return today - timedelta(days=1)

    for pattern, order in _DATE_PATTERNS:
        match = pattern.match(raw)
        if not match:
            continue
        parts = dict(zip(order, (int(p) for p in match.groups())))
        try:
            return date(parts["y"], parts["m"], parts["d"])
        except ValueError as exc:
            raise ConfigError(
                f"'{raw}' is not a real calendar date ({exc}).",
                hint="Check the day and month values.",
            ) from exc

    raise ConfigError(
        f"'{raw}' is not a date this program understands.",
        hint=(
            "Use 'today', 'yesterday', or a date such as 2026-09-08, "
            "08-09-2026 or 08.09.2026."
        ),
    )


def parse_date_range(value: str, *, today: date | None = None) -> list[date]:
    """Parse ``A..B`` (or a single date) into an inclusive list of dates."""
    raw = (value or "").strip()
    if ".." in raw:
        start_raw, _, end_raw = raw.partition("..")
        start = parse_date(start_raw, today=today)
        end = parse_date(end_raw, today=today)
        if end < start:
            raise ConfigError(
                f"The end date ({end.isoformat()}) is before the start date "
                f"({start.isoformat()})."
            )
        span = (end - start).days
        return [start + timedelta(days=offset) for offset in range(span + 1)]
    return [parse_date(raw, today=today)]


@dataclass(frozen=True)
class FiscalYear:
    """A financial year, e.g. 1 April 2026 - 31 March 2027."""

    start_year: int
    end_year: int
    start: date
    end: date
    label: str

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end


@dataclass(frozen=True)
class DateManager:
    """Resolves report dates and the fiscal year a date belongs to.

    ``fiscal_year_start_month`` defaults to 4 (April), the Indian financial
    year, but any month is supported - set it to 1 for a calendar year.
    """

    fiscal_year_start_month: int = 4
    fiscal_year_label_format: str = "{start_year}-{end_year_short}"

    def __post_init__(self) -> None:
        if not 1 <= self.fiscal_year_start_month <= 12:
            raise ConfigError(
                "dates.fiscal_year_start_month must be between 1 and 12, got "
                f"{self.fiscal_year_start_month}."
            )

    # -- resolution ------------------------------------------------------
    def resolve(self, value: str = "yesterday", *, today: date | None = None) -> date:
        """Resolve a single report date from a keyword or written date."""
        return parse_date(value, today=today)

    def resolve_range(
        self, value: str = "yesterday", *, today: date | None = None
    ) -> list[date]:
        """Resolve one date or an inclusive ``A..B`` range."""
        return parse_date_range(value, today=today)

    def today(self, *, today: date | None = None) -> date:
        return today or date.today()

    def yesterday(self, *, today: date | None = None) -> date:
        return (today or date.today()) - timedelta(days=1)

    # -- fiscal year -----------------------------------------------------
    def fiscal_year(self, day: date) -> FiscalYear:
        """Return the fiscal year that ``day`` falls into."""
        start_month = self.fiscal_year_start_month
        start_year = day.year if day.month >= start_month else day.year - 1
        start = date(start_year, start_month, 1)
        if start_month == 1:
            end_year = start_year
            end = date(start_year, 12, 31)
        else:
            end_year = start_year + 1
            end = date(end_year, start_month, 1) - timedelta(days=1)
        label = self.fiscal_year_label_format.format(
            start_year=start_year,
            end_year=end_year,
            start_year_short=f"{start_year % 100:02d}",
            end_year_short=f"{end_year % 100:02d}",
        )
        return FiscalYear(
            start_year=start_year,
            end_year=end_year,
            start=start,
            end=end,
            label=label,
        )

    # -- template tokens -------------------------------------------------
    def tokens(self, day: date) -> dict[str, object]:
        """Values available to folder / filename templates in the config."""
        fy = self.fiscal_year(day)
        return {
            "dd": f"{day.day:02d}",
            "d": str(day.day),
            "mm": f"{day.month:02d}",
            "m": str(day.month),
            "yyyy": str(day.year),
            "yy": f"{day.year % 100:02d}",
            "month_num": str(day.month),
            "month_num_padded": f"{day.month:02d}",
            "month_name_upper": month_name(day.month),
            "month_name": month_name(day.month).capitalize(),
            "month_name_short": month_name(day.month)[:3],
            "iso": day.isoformat(),
            "fy_label": fy.label,
            "fy_start_year": str(fy.start_year),
            "fy_end_year": str(fy.end_year),
        }
