"""Windows automation backend, built on pywinauto's UI Automation support.

Controls are located by their accessibility properties (automation id, name,
control type, class name) - never by screen coordinates.  ``click`` still uses
a real mouse click, but on the rectangle the control reports for itself, so it
follows the control when the window moves or the screen resolution changes.

This module imports pywinauto lazily so the file can be read and imported on
macOS; every entry point checks :func:`ensure_available` first.
"""

from __future__ import annotations

import ctypes
import logging
import subprocess
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any

from ..errors import (
    ApplicationLaunchError,
    ApplicationNotFoundError,
    ControlNotFoundError,
    MissingDependencyError,
    UnsupportedPlatformError,
    WindowNotFoundError,
)
from ..platform_support import is_windows, missing_required_packages
from .base import AutomationBackend, ControlInfo, ProcessInfo, WindowInfo, WindowRef
from .selectors import UiTarget, WindowSpec

logger = logging.getLogger(__name__)

DEFAULT_CONTROL_STATES = "exists visible enabled ready"


def ensure_available() -> None:
    """Raise a clear error unless this computer can run Windows automation."""
    if not is_windows():
        raise UnsupportedPlatformError()
    missing = missing_required_packages()
    if missing:
        raise MissingDependencyError(
            "Missing Windows automation package(s): " + ", ".join(missing),
            hint="Run: pip install -r requirements.txt",
        )


# --------------------------------------------------------------------------
# Process enumeration (ctypes - no extra dependency)
# --------------------------------------------------------------------------
TH32CS_SNAPPROCESS = 0x00000002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259


class _PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_char * 260),
    ]


def iter_processes() -> list[ProcessInfo]:
    """Every running process, as (pid, executable name)."""
    ensure_available()
    kernel32 = ctypes.windll.kernel32
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == -1:
        raise ApplicationNotFoundError("Could not read the list of running programs.")
    processes: list[ProcessInfo] = []
    try:
        entry = _PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32)
        success = kernel32.Process32First(snapshot, ctypes.byref(entry))
        while success:
            processes.append(
                ProcessInfo(
                    pid=int(entry.th32ProcessID),
                    name=entry.szExeFile.decode("mbcs", errors="replace"),
                )
            )
            success = kernel32.Process32Next(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return processes


class WindowsBackend(AutomationBackend):
    """pywinauto-backed implementation of :class:`AutomationBackend`."""

    name = "windows"

    def __init__(self, ui_backend: str = "uia") -> None:
        self.ui_backend = ui_backend or "uia"
        self._desktop: Any = None

    # -- plumbing --------------------------------------------------------
    @property
    def is_supported(self) -> bool:
        return is_windows() and not missing_required_packages()

    def _pywinauto(self) -> Any:
        ensure_available()
        import pywinauto  # noqa: PLC0415 - Windows-only, imported on demand

        return pywinauto

    def desktop(self) -> Any:
        if self._desktop is None:
            self._desktop = self._pywinauto().Desktop(backend=self.ui_backend)
        return self._desktop

    def _timeout_error_types(self) -> tuple[type[BaseException], ...]:
        pywinauto = self._pywinauto()
        from pywinauto.findwindows import (  # noqa: PLC0415
            ElementAmbiguousError,
            ElementNotFoundError,
        )

        return (pywinauto.timings.TimeoutError, ElementNotFoundError, ElementAmbiguousError)

    # -- processes -------------------------------------------------------
    def start_process(
        self,
        executable: str,
        *,
        arguments: list[str] | None = None,
        working_directory: str = "",
    ) -> ProcessInfo:
        ensure_available()
        exe_path = Path(executable)
        if not exe_path.is_file():
            raise ApplicationNotFoundError(
                f"'{executable}' does not exist.",
                hint="Set application.executable_path to the full path of the NS Retail .exe.",
            )
        command = [str(exe_path), *(arguments or [])]
        cwd = working_directory or str(exe_path.parent)
        logger.info("Starting %s", exe_path)
        try:
            process = subprocess.Popen(command, cwd=cwd)  # noqa: S603 - path comes from config
        except OSError as exc:
            raise ApplicationLaunchError(
                f"Could not start '{exe_path}': {exc}",
                hint="Check that the path is correct and that you have permission to run it.",
            ) from exc
        return ProcessInfo(pid=process.pid, name=exe_path.name, executable=str(exe_path))

    def find_processes(self, name_or_path: str) -> list[ProcessInfo]:
        wanted = Path(name_or_path).name.lower()
        if not wanted:
            return []
        return [p for p in iter_processes() if p.name.lower() == wanted]

    def is_process_running(self, pid: int) -> bool:
        ensure_available()
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return False
        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)

    # -- windows ---------------------------------------------------------
    def list_windows(self, *, visible_only: bool = True) -> list[WindowInfo]:
        ensure_available()
        windows: list[WindowInfo] = []
        for element in self.desktop().windows():
            try:
                info = element.element_info
                if visible_only and not element.is_visible():
                    continue
                windows.append(
                    WindowInfo(
                        title=info.name or "",
                        class_name=info.class_name or "",
                        handle=getattr(info, "handle", None),
                        process_id=getattr(info, "process_id", None),
                        control_type=getattr(info, "control_type", "") or "",
                        is_visible=True,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - a window may vanish mid-scan
                logger.debug("Skipping a window that could not be read: %s", exc)
        return windows

    def _window_criteria(
        self, spec: WindowSpec, process_id: int | None
    ) -> dict[str, Any]:
        criteria = spec.search_criteria()
        if not criteria:
            raise WindowNotFoundError(
                f"The '{spec.key}' window has no identifying details configured."
            )
        if process_id:
            criteria["process"] = process_id
        return criteria

    def find_window(
        self, spec: WindowSpec, *, process_id: int | None = None
    ) -> WindowRef | None:
        ensure_available()
        criteria = self._window_criteria(spec, process_id)
        window_spec = self.desktop().window(**criteria)
        try:
            if not window_spec.exists(timeout=0.5, retry_interval=0.2):
                return None
            wrapper = window_spec.wrapper_object()
        except self._timeout_error_types():
            return None
        return self._wrap(window_spec, wrapper)

    def wait_for_window(
        self, spec: WindowSpec, *, timeout: float, process_id: int | None = None
    ) -> WindowRef:
        ensure_available()
        criteria = self._window_criteria(spec, process_id)
        window_spec = self.desktop().window(**criteria)
        described = ", ".join(f"{k}={v!r}" for k, v in criteria.items())
        try:
            window_spec.wait("exists visible", timeout=timeout, retry_interval=0.5)
            wrapper = window_spec.wrapper_object()
        except self._timeout_error_types() as exc:
            raise WindowNotFoundError(
                f"The '{spec.key}' window did not appear within {timeout:.0f} seconds.",
                hint=f"Looked for: {described}. ({type(exc).__name__})",
            ) from exc
        logger.debug("Found window '%s'", spec.key)
        return self._wrap(window_spec, wrapper)

    def wait_for_window_closed(self, window: WindowRef, *, timeout: float) -> None:
        ensure_available()
        try:
            window.native.wait_not("exists visible", timeout=timeout, retry_interval=0.5)
        except self._timeout_error_types() as exc:
            raise WindowNotFoundError(
                f"The window '{window.info.title}' was still open after "
                f"{timeout:.0f} seconds."
            ) from exc

    def focus_window(self, window: WindowRef) -> None:
        ensure_available()
        try:
            window.native.set_focus()
        except Exception as exc:  # noqa: BLE001 - focus failures are recoverable
            logger.warning("Could not bring '%s' to the front: %s", window.info.title, exc)

    def close_window(self, window: WindowRef) -> None:
        ensure_available()
        try:
            window.native.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not close '%s': %s", window.info.title, exc)

    def _wrap(self, window_spec: Any, wrapper: Any) -> WindowRef:
        info = wrapper.element_info
        return WindowRef(
            native=window_spec,
            info=WindowInfo(
                title=info.name or "",
                class_name=info.class_name or "",
                handle=getattr(info, "handle", None),
                process_id=getattr(info, "process_id", None),
                control_type=getattr(info, "control_type", "") or "",
            ),
        )

    # -- controls --------------------------------------------------------
    def _container(self, window: WindowRef, target: UiTarget) -> Any:
        """The window, or a nested control the search is scoped to."""
        parent = target.parent_criteria()
        if not parent:
            return window.native
        return window.native.child_window(**parent)

    def _control(self, window: WindowRef, target: UiTarget, timeout: float) -> Any:
        criteria = target.search_criteria()
        control = self._container(window, target).child_window(**criteria)
        try:
            control.wait(DEFAULT_CONTROL_STATES, timeout=timeout, retry_interval=0.3)
        except self._timeout_error_types() as exc:
            raise ControlNotFoundError(
                f"Could not find the control for '{target.label()}' within "
                f"{timeout:.0f} seconds.",
                hint=self._not_found_hint(window),
            ) from exc
        return control.wrapper_object()

    def _not_found_hint(self, window: WindowRef) -> str:
        """Explain the most likely reason a control could not be reached.

        A modal dialog disables everything behind it, so the control is present
        but never becomes enabled - which looks identical to a wrong selector
        unless the open dialogs are named.
        """
        base = (
            "The control details in config/selectors.json may be wrong. "
            "Re-run the inspection tool on this screen to check them."
        )
        try:
            others = [
                info.title
                for info in self.list_windows()
                if info.title
                and info.process_id == window.info.process_id
                and info.title != window.info.title
            ]
        except Exception:  # noqa: BLE001 - the hint must never fail
            return base
        if others:
            return (
                "These other NS Retail windows are open: "
                + ", ".join(f"'{title}'" for title in others)
                + ". A dialog on top disables the window behind it - close it "
                "and try again. " + base
            )
        return base

    def control_exists(
        self, window: WindowRef, target: UiTarget, *, timeout: float = 0.0
    ) -> bool:
        ensure_available()
        try:
            control = self._container(window, target).child_window(**target.search_criteria())
            return bool(control.exists(timeout=max(timeout, 0.1), retry_interval=0.2))
        except self._timeout_error_types():
            return False

    def read_control_text(self, window: WindowRef, target: UiTarget, *, timeout: float) -> str:
        ensure_available()
        wrapper = self._control(window, target, timeout)
        try:
            return wrapper.window_text() or ""
        except Exception:  # noqa: BLE001 - some controls expose no text
            return ""

    def perform(self, window: WindowRef, target: UiTarget, *, timeout: float) -> None:
        ensure_available()
        action = target.action
        effective_timeout = target.timeout_seconds or timeout

        if target.targets_window_itself():
            # A keystroke aimed at the screen rather than at one control, such
            # as F3 opening NS Retail's Include/Exclude dialog.
            self.focus_window(window)
            window.native.type_keys(target.value, with_spaces=True, set_foreground=True)
            return

        if action == "menu_select":
            # Classic menu bars are addressed by their path, not by a child window.
            try:
                window.native.menu_select(target.value)
            except Exception as exc:  # noqa: BLE001 - reported as a friendly error
                raise ControlNotFoundError(
                    f"Could not use the menu path '{target.value}': {exc}"
                ) from exc
            return

        wrapper = self._control(window, target, effective_timeout)

        if action == "wait":
            return
        if action == "invoke":
            self._invoke(wrapper, target)
            return
        if action == "click":
            wrapper.click_input()
            return
        if action == "expand":
            self._call_first(wrapper, ("expand", "click_input"), target)
            return
        if action == "select":
            try:
                wrapper.select(target.value) if target.value else wrapper.select()
            except Exception as exc:  # noqa: BLE001
                raise ControlNotFoundError(
                    f"Could not select '{target.value or target.label()}': {exc}"
                ) from exc
            return
        if action == "set_text":
            self._set_text(wrapper, target)
            return
        if action == "send_keys":
            try:
                wrapper.set_focus()
            except Exception as exc:  # noqa: BLE001 - focus is best effort
                logger.debug("Could not focus %s: %s", target.label(), exc)
            wrapper.type_keys(target.value, with_spaces=True, set_foreground=True)
            return

        raise ControlNotFoundError(f"Unsupported action '{action}' for {target.label()}.")

    def _invoke(self, wrapper: Any, target: UiTarget) -> None:
        """Prefer the UI Automation Invoke pattern; fall back to a click."""
        for method in ("invoke", "click", "click_input"):
            action = getattr(wrapper, method, None)
            if action is None:
                continue
            try:
                action()
                return
            except Exception as exc:  # noqa: BLE001 - try the next technique
                logger.debug("%s() failed for %s: %s", method, target.label(), exc)
        raise ControlNotFoundError(f"Could not activate '{target.label()}'.")

    def _set_text(self, wrapper: Any, target: UiTarget) -> None:
        value = target.value
        for method in ("set_edit_text", "set_text"):
            setter = getattr(wrapper, method, None)
            if setter is None:
                continue
            try:
                setter(value)
                return
            except Exception as exc:  # noqa: BLE001 - try the next technique
                logger.debug("%s() failed for %s: %s", method, target.label(), exc)
        try:  # last resort: type into the focused control
            wrapper.set_focus()
            wrapper.type_keys(value, with_spaces=True, set_foreground=True)
        except Exception as exc:  # noqa: BLE001
            raise ControlNotFoundError(
                f"Could not type '{value}' into '{target.label()}': {exc}"
            ) from exc

    def _call_first(self, wrapper: Any, methods: tuple[str, ...], target: UiTarget) -> None:
        for method in methods:
            action = getattr(wrapper, method, None)
            if action is None:
                continue
            try:
                action()
                return
            except Exception as exc:  # noqa: BLE001
                logger.debug("%s() failed for %s: %s", method, target.label(), exc)
        raise ControlNotFoundError(f"Could not act on '{target.label()}'.")

    # -- inspection (read-only) -----------------------------------------
    def active_window(self) -> WindowRef | None:
        ensure_available()
        handle = ctypes.windll.user32.GetForegroundWindow()
        if not handle:
            return None
        pywinauto = self._pywinauto()
        try:
            wrapper = pywinauto.Desktop(backend=self.ui_backend).window(handle=handle)
            resolved = wrapper.wrapper_object()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not read the active window: %s", exc)
            return None
        return self._wrap(wrapper, resolved)

    def describe_window(self, window: WindowRef, *, max_depth: int = 8) -> ControlInfo:
        ensure_available()
        wrapper = window.native.wrapper_object()
        return self._describe_element(wrapper.element_info, depth=0, max_depth=max_depth)

    def _describe_element(self, element: Any, *, depth: int, max_depth: int) -> ControlInfo:
        try:
            rectangle = str(element.rectangle)
        except Exception:  # noqa: BLE001
            rectangle = ""
        info = ControlInfo(
            depth=depth,
            control_type=getattr(element, "control_type", "") or "",
            name=getattr(element, "name", "") or "",
            automation_id=getattr(element, "automation_id", "") or "",
            class_name=getattr(element, "class_name", "") or "",
            framework_id=getattr(element, "framework_id", "") or "",
            rectangle=rectangle,
            is_enabled=bool(getattr(element, "enabled", True)),
            is_visible=bool(getattr(element, "visible", True)),
            handle=getattr(element, "handle", None),
            children=[],
        )
        if depth >= max_depth:
            return info
        try:
            children = element.children()
        except Exception as exc:  # noqa: BLE001 - some elements refuse enumeration
            logger.debug("Could not read children at depth %d: %s", depth, exc)
            children = []
        for child in children:
            info.children.append(
                self._describe_element(child, depth=depth + 1, max_depth=max_depth)
            )
        return info

    # -- convenience -----------------------------------------------------
    def wait_for_process_window(
        self, spec: WindowSpec, *, pid: int, timeout: float
    ) -> WindowRef:
        """Wait for a window belonging to a specific process."""
        deadline = time.monotonic() + timeout
        while True:
            window = self.find_window(spec, process_id=pid)
            if window is not None:
                return window
            if time.monotonic() >= deadline:
                raise WindowNotFoundError(
                    f"No '{spec.key}' window from process {pid} appeared within "
                    f"{timeout:.0f} seconds."
                )
            time.sleep(0.5)
