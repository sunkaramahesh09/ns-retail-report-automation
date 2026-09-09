"""The platform-independent automation interface.

``NSRetailAutomation`` talks only to this interface, so the Windows specific
code stays in one file (:mod:`.windows`) and the rest of the project can be
imported, read and tested on macOS.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ..errors import UnsupportedPlatformError
from .selectors import UiTarget, WindowSpec

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    name: str
    executable: str = ""


@dataclass(frozen=True)
class ControlInfo:
    """A snapshot of one control, used by the inspection tool."""

    depth: int = 0
    control_type: str = ""
    name: str = ""
    automation_id: str = ""
    class_name: str = ""
    framework_id: str = ""
    rectangle: str = ""
    is_enabled: bool = True
    is_visible: bool = True
    handle: int | None = None
    #: "on" / "off" / "indeterminate" for anything that can be ticked.
    toggle_state: str = ""
    #: What the control currently shows, where it has a readable value.
    value: str = ""
    children: list[ControlInfo] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "control_type": self.control_type,
            "name": self.name,
            "automation_id": self.automation_id,
            "class_name": self.class_name,
            "framework_id": self.framework_id,
            "rectangle": self.rectangle,
            "is_enabled": self.is_enabled,
            "is_visible": self.is_visible,
            "handle": self.handle,
            "toggle_state": self.toggle_state,
            "value": self.value,
            "children": [child.as_dict() for child in self.children],
        }

    def suggested_selector(self) -> dict[str, str]:
        """The selector fields worth copying into config/selectors.json."""
        selector: dict[str, str] = {}
        if self.automation_id:
            selector["auto_id"] = self.automation_id
        if self.name:
            selector["title"] = self.name
        if self.control_type:
            selector["control_type"] = self.control_type
        if not self.automation_id and not self.name and self.class_name:
            selector["class_name"] = self.class_name
        return selector


@dataclass(frozen=True)
class WindowInfo:
    title: str = ""
    class_name: str = ""
    handle: int | None = None
    process_id: int | None = None
    control_type: str = ""
    is_visible: bool = True


class WindowRef:
    """Opaque handle to a window owned by a backend.

    The backend stores whatever it needs in ``native``; callers only pass this
    object back to the backend.
    """

    def __init__(self, native: Any, info: WindowInfo) -> None:
        self.native = native
        self.info = info

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"WindowRef(title={self.info.title!r}, class={self.info.class_name!r})"


class AutomationBackend(ABC):
    """Everything the NS Retail workflow needs from the operating system."""

    name = "base"

    @property
    @abstractmethod
    def is_supported(self) -> bool:
        """True when this backend can actually drive applications here."""

    # -- processes -------------------------------------------------------
    @abstractmethod
    def start_process(
        self, executable: str, *, arguments: list[str] | None = None, working_directory: str = ""
    ) -> ProcessInfo:
        """Start an application and return its process information."""

    @abstractmethod
    def find_processes(self, name_or_path: str) -> list[ProcessInfo]:
        """Find running processes matching an executable name or path."""

    @abstractmethod
    def is_process_running(self, pid: int) -> bool:
        ...

    # -- windows ---------------------------------------------------------
    @abstractmethod
    def list_windows(self, *, visible_only: bool = True) -> list[WindowInfo]:
        """List top-level windows - used by the inspection tool."""

    @abstractmethod
    def find_window(self, spec: WindowSpec, *, process_id: int | None = None) -> WindowRef | None:
        """Return the matching window, or ``None`` if it is not there yet."""

    @abstractmethod
    def wait_for_window(
        self, spec: WindowSpec, *, timeout: float, process_id: int | None = None
    ) -> WindowRef:
        """Wait for a window to appear; raise ``WindowNotFoundError`` on timeout."""

    @abstractmethod
    def wait_for_window_closed(self, window: WindowRef, *, timeout: float) -> None:
        ...

    @abstractmethod
    def child_window_ref(self, window: WindowRef, criteria: dict[str, Any]) -> WindowRef:
        """A window nested inside another one.

        NS Retail's dialogs are child windows of the main form rather than
        top-level windows, so they are addressed this way.
        """

    @abstractmethod
    def focus_window(self, window: WindowRef) -> None:
        ...

    @abstractmethod
    def close_window(self, window: WindowRef) -> None:
        ...

    # -- controls --------------------------------------------------------
    @abstractmethod
    def perform(self, window: WindowRef, target: UiTarget, *, timeout: float) -> None:
        """Carry out one :class:`UiTarget` (find the control, then act on it)."""

    @abstractmethod
    def control_exists(self, window: WindowRef, target: UiTarget, *, timeout: float = 0.0) -> bool:
        ...

    @abstractmethod
    def read_control_text(self, window: WindowRef, target: UiTarget, *, timeout: float) -> str:
        ...

    # -- inspection ------------------------------------------------------
    @abstractmethod
    def describe_window(self, window: WindowRef, *, max_depth: int = 8) -> ControlInfo:
        """Read-only control tree snapshot for the inspection tool."""

    @abstractmethod
    def active_window(self) -> WindowRef | None:
        ...


class UnsupportedBackend(AutomationBackend):
    """Stand-in used on macOS/Linux.

    Every method raises a clear, non-technical error.  This keeps the whole
    project importable and testable off Windows without pretending that any of
    the NS Retail interaction works.
    """

    name = "unsupported"

    def __init__(self, reason: str | None = None) -> None:
        self.reason = reason or (
            "NS Retail automation needs Windows; this computer is not running Windows."
        )

    @property
    def is_supported(self) -> bool:
        return False

    def _fail(self, action: str) -> Any:
        raise UnsupportedPlatformError(f"Cannot {action}: {self.reason}")

    def start_process(self, executable, *, arguments=None, working_directory=""):
        return self._fail(f"start '{executable}'")

    def find_processes(self, name_or_path):
        return self._fail("look for running applications")

    def is_process_running(self, pid):
        return self._fail("check whether an application is running")

    def list_windows(self, *, visible_only=True):
        return self._fail("list application windows")

    def find_window(self, spec, *, process_id=None):
        return self._fail("find an application window")

    def wait_for_window(self, spec, *, timeout, process_id=None):
        return self._fail("wait for an application window")

    def wait_for_window_closed(self, window, *, timeout):
        return self._fail("wait for a window to close")

    def child_window_ref(self, window, criteria):
        return self._fail("find a window inside another window")

    def focus_window(self, window):
        return self._fail("focus a window")

    def close_window(self, window):
        return self._fail("close a window")

    def perform(self, window, target, *, timeout):
        return self._fail(f"interact with '{target.label()}'")

    def control_exists(self, window, target, *, timeout=0.0):
        return self._fail("look for a control")

    def read_control_text(self, window, target, *, timeout):
        return self._fail("read text from a control")

    def describe_window(self, window, *, max_depth=8):
        return self._fail("inspect a window")

    def active_window(self):
        return self._fail("find the active window")
