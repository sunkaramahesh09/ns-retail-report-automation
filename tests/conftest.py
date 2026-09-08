"""Shared test fixtures.

Everything here runs on macOS: no Windows and no NS Retail required.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from ns_retail_automation.config.settings import DEFAULTS, build_settings
from ns_retail_automation.utils.dates import DateManager


@pytest.fixture
def dates() -> DateManager:
    return DateManager(fiscal_year_start_month=4)


@pytest.fixture
def config_data() -> dict[str, Any]:
    return copy.deepcopy(DEFAULTS)


@pytest.fixture
def settings(config_data):
    return build_settings(config_data)


@pytest.fixture
def make_settings():
    """Build settings from the defaults with a few sections overridden."""

    def _make(**sections: dict[str, Any]):
        data = copy.deepcopy(DEFAULTS)
        for name, values in sections.items():
            data.setdefault(name, {}).update(values)
        return build_settings(data)

    return _make
