"""Automation layer: a platform-independent interface plus a Windows backend."""

from __future__ import annotations

import logging

from ..platform_support import is_windows, missing_required_packages
from .base import AutomationBackend, ControlInfo, ProcessInfo, UnsupportedBackend, WindowInfo, WindowRef
from .ns_retail import PURCHASE_REPORT_STEPS, NSRetailAutomation
from .selectors import Selectors, Step, UiTarget, WindowSpec, load_selectors

logger = logging.getLogger(__name__)

__all__ = [
    "AutomationBackend",
    "ControlInfo",
    "ProcessInfo",
    "UnsupportedBackend",
    "WindowInfo",
    "WindowRef",
    "NSRetailAutomation",
    "PURCHASE_REPORT_STEPS",
    "Selectors",
    "Step",
    "UiTarget",
    "WindowSpec",
    "load_selectors",
    "get_backend",
]


def get_backend(ui_backend: str = "uia") -> AutomationBackend:
    """Return the automation backend for this computer.

    On Windows (with the automation packages installed) this is the pywinauto
    backend.  Everywhere else it is :class:`UnsupportedBackend`, whose methods
    explain why they cannot run rather than pretending to work.
    """
    if not is_windows():
        return UnsupportedBackend()

    missing = missing_required_packages()
    if missing:
        return UnsupportedBackend(
            "the Windows automation package(s) "
            + ", ".join(missing)
            + " are not installed (run: pip install -r requirements.txt)"
        )

    from .windows import WindowsBackend  # noqa: PLC0415 - Windows-only import

    return WindowsBackend(ui_backend=ui_backend)
