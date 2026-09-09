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
import re
import subprocess
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any

from ..errors import (
    AmbiguousControlError,
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

#: Safety limit when paging through a grid whose length is not known.
MAX_GRID_PAGES = 40

#: Safety limit when closing leftover screens.
MAX_CLOSE_ROUNDS = 15


def _digit_groups(text: str) -> list[str]:
    """The runs of digits in a string, e.g. '08 September 2026' -> ['08', '2026']."""
    return re.findall(r"\d+", text or "")


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

    def wait_for_child_window(
        self, parent: WindowRef, spec: WindowSpec, *, timeout: float
    ) -> WindowRef:
        ensure_available()
        criteria = spec.search_criteria()
        if not criteria:
            raise WindowNotFoundError(
                f"The '{spec.key}' window has no identifying details configured."
            )
        window_spec = parent.native.child_window(**criteria)
        described = ", ".join(f"{k}={v!r}" for k, v in criteria.items())
        try:
            window_spec.wait("exists visible", timeout=timeout, retry_interval=0.5)
            wrapper = window_spec.wrapper_object()
        except self._timeout_error_types() as exc:
            raise WindowNotFoundError(
                f"The '{spec.key}' window did not appear inside "
                f"'{parent.info.title}' within {timeout:.0f} seconds.",
                hint=f"Looked for: {described}.",
            ) from exc
        logger.debug("Found child window '%s'", spec.key)
        return self._wrap(window_spec, wrapper)

    def child_window_ref(self, window: WindowRef, criteria: dict[str, Any]) -> WindowRef:
        ensure_available()
        if not criteria:
            raise WindowNotFoundError("No criteria were given for the child window.")
        spec = window.native.child_window(**criteria)
        described = ", ".join(f"{k}={v!r}" for k, v in criteria.items())
        try:
            if not spec.exists(timeout=2.0, retry_interval=0.3):
                raise WindowNotFoundError(
                    f"No window inside '{window.info.title}' matched {described}."
                )
            wrapper = spec.wrapper_object()
        except self._timeout_error_types() as exc:
            raise WindowNotFoundError(
                f"No window inside '{window.info.title}' matched {described}."
            ) from exc
        return self._wrap(spec, wrapper)

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

        from pywinauto.findwindows import ElementAmbiguousError  # noqa: PLC0415

        try:
            control.wait(DEFAULT_CONTROL_STATES, timeout=timeout, retry_interval=0.3)
        except ElementAmbiguousError as exc:
            # Several controls match. Acting on an arbitrary one could type a
            # date into a panel the user cannot see, so this is only resolved
            # when the selector says which one it means.
            return self._resolve_ambiguous(window, target, exc)
        except self._timeout_error_types() as exc:
            raise ControlNotFoundError(
                f"Could not find the control for '{target.label()}' within "
                f"{timeout:.0f} seconds.",
                hint=self._not_found_hint(window),
            ) from exc

        try:
            return control.wrapper_object()
        except ElementAmbiguousError as exc:
            return self._resolve_ambiguous(window, target, exc)

    def _matching_wrappers(self, window: WindowRef, target: UiTarget) -> list[Any]:
        """Every control matching the target, in tree order."""
        container = self._container(window, target)
        try:
            parent_element = container.wrapper_object().element_info
        except Exception as exc:  # noqa: BLE001 - reported by the caller
            logger.debug("Could not resolve the container: %s", exc)
            return []

        from pywinauto.findwindows import find_elements  # noqa: PLC0415

        criteria = dict(target.search_criteria())
        criteria.pop("found_index", None)
        elements = find_elements(
            parent=parent_element,
            backend=self.ui_backend,
            top_level_only=False,
            **criteria,
        )
        wrappers = []
        for element in elements:
            try:
                wrappers.append(self._pywinauto().controls.uiawrapper.UIAWrapper(element))
            except Exception:  # noqa: BLE001 - a stale element is not usable
                continue
        return wrappers

    @staticmethod
    def _rectangle_of(wrapper: Any) -> tuple[int, int, int, int]:
        rect = wrapper.rectangle()
        return (rect.top, rect.left, rect.width(), rect.height())

    def _resolve_ambiguous(self, window: WindowRef, target: UiTarget, exc: Exception) -> Any:
        matches = self._matching_wrappers(window, target)
        described = [
            f"{index}: {self._rectangle_of(match)[:2]}" for index, match in enumerate(matches)
        ]

        if not target.pick:
            raise AmbiguousControlError(
                f"{len(matches) or 'Several'} controls match '{target.label()}' - "
                "refusing to guess which one to use.",
                hint=(
                    "NS Retail can leave several copies of a screen open at once. "
                    "Close the extra ones (or restart NS Retail), or add "
                    '"pick": "topmost" to this target in config/selectors.json. '
                    f"Matches at (top, left): {'; '.join(described)}"
                ),
            ) from exc

        if not matches:
            raise ControlNotFoundError(
                f"'{target.label()}' matched several controls, but none could be read."
            ) from exc

        chosen = self._pick_one(matches, target.pick)
        logger.warning(
            "%d controls match '%s'; using the '%s' one at %s.",
            len(matches),
            target.label(),
            target.pick,
            self._rectangle_of(chosen)[:2],
        )
        return chosen

    def _pick_one(self, matches: list[Any], pick: str) -> Any:
        if pick == "first":
            return matches[0]
        if pick == "last":
            return matches[-1]
        if pick == "topmost":
            return min(matches, key=lambda m: self._rectangle_of(m)[0])
        if pick == "bottommost":
            return max(matches, key=lambda m: self._rectangle_of(m)[0])
        if pick == "largest":
            return max(matches, key=lambda m: self._rectangle_of(m)[2] * self._rectangle_of(m)[3])
        return matches[0]

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
        from pywinauto.findwindows import ElementAmbiguousError  # noqa: PLC0415

        try:
            control = self._container(window, target).child_window(**target.search_criteria())
            return bool(control.exists(timeout=max(timeout, 0.1), retry_interval=0.2))
        except ElementAmbiguousError:
            return True  # several match, so it certainly exists
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
            if target.focus:
                self.focus_window(window)
                window.native.type_keys(target.value, with_spaces=True, set_foreground=True)
                return
            # With focus:false the keys go wherever focus already is. A popup
            # menu closes if anything else is focused, so it cannot be given
            # focus explicitly first.
            from pywinauto.keyboard import send_keys  # noqa: PLC0415

            logger.debug(
                "Sending keys '%s' to whatever has focus (pause %.2fs)",
                target.value,
                target.pause_seconds,
            )
            send_keys(target.value, with_spaces=True, pause=target.pause_seconds)
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

        # These two are handled before a single control is resolved: one exists
        # to deal with duplicates, and the other only asks whether the control
        # is there at all. Demanding a unique match first would defeat both.
        if action == "invoke_until_gone":
            self._invoke_until_gone(window, target)
            return
        if action == "wait":
            self._wait_for_any(window, target, effective_timeout)
            return
        if action == "select_export_format":
            self._select_export_format(window, target, effective_timeout)
            return

        wrapper = self._control(window, target, effective_timeout)

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
        if action == "verify_text":
            actual = self._read_text(wrapper)
            if target.value.lower() not in actual.lower():
                raise ControlNotFoundError(
                    f"{target.label()} says '{actual}', but '{target.value}' was "
                    "expected.",
                    hint=(
                        "The application is not in the state the automation "
                        "assumed. Nothing was saved."
                    ),
                )
            logger.info("Checked %s: '%s'", target.label(), actual)
            return
        if action == "check_all_rows":
            self._check_all_rows(wrapper, target)
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
        before = self._read_text(wrapper)

        for method in ("set_edit_text", "set_text"):
            setter = getattr(wrapper, method, None)
            if setter is None:
                continue
            try:
                setter(value)
            except Exception as exc:  # noqa: BLE001 - try the next technique
                logger.debug("%s() failed for %s: %s", method, target.label(), exc)
                continue
            if self._confirm_text(wrapper, target, value, before, method):
                return

        try:  # last resort: select everything and type over it
            wrapper.set_focus()
            wrapper.type_keys("^a", set_foreground=True)
            wrapper.type_keys(value, with_spaces=True, set_foreground=True)
        except Exception as exc:  # noqa: BLE001
            raise ControlNotFoundError(
                f"Could not type '{value}' into '{target.label()}': {exc}"
            ) from exc
        self._confirm_text(wrapper, target, value, before, "type_keys")

    def _wait_for_any(self, window: WindowRef, target: UiTarget, timeout: float) -> None:
        """Wait until at least one control matches. Several is still a yes."""
        deadline = time.monotonic() + timeout
        while True:
            if self.control_exists(window, target, timeout=0.5):
                return
            if time.monotonic() >= deadline:
                raise ControlNotFoundError(
                    f"'{target.label()}' did not appear within {timeout:.0f} seconds.",
                    hint=self._not_found_hint(window),
                )
            time.sleep(0.3)

    def _invoke_until_gone(self, window: WindowRef, target: UiTarget) -> None:
        """Invoke every control matching the target, until none are left.

        NS Retail opens a new report screen each time one is asked for and
        never closes the old one, so several identical screens pile up. This
        clears them; ambiguity is expected here rather than a problem.
        """
        for round_number in range(1, MAX_CLOSE_ROUNDS + 1):
            matches = self._matching_wrappers(window, target)
            if not matches:
                if round_number > 1:
                    logger.info("Closed %d leftover screen(s).", round_number - 1)
                return
            logger.info(
                "Closing leftover screen %d (%d still open)", round_number, len(matches)
            )
            try:
                self._invoke(matches[0], target)
            except Exception as exc:  # noqa: BLE001 - report what is left
                raise ControlNotFoundError(
                    f"Could not close '{target.label()}': {exc}"
                ) from exc
            time.sleep(0.4)
        raise ControlNotFoundError(
            f"'{target.label()}' was still there after {MAX_CLOSE_ROUNDS} attempts.",
            hint="Close the extra report screens in NS Retail by hand.",
        )

    def _select_export_format(self, window: WindowRef, target: UiTarget, timeout: float) -> None:
        """Pick an export format from an owner-drawn popup menu by trial.

        The menu's entries are invisible to UI Automation - confirmed live,
        0 descendants under its MenuBar - and their order is not fixed
        between sessions either: the same {HOME}{DOWN n}{ENTER} sequence
        opened a different format's Options dialog on two separate runs, in
        what looks like a most-recently-used ordering. So rather than a
        fixed position, this opens the dropdown, presses Home plus an
        increasing number of Downs plus Enter, and reads the title of
        whichever Options dialog that opens. If it doesn't match "value",
        that dialog is cancelled and the next position is tried.
        """
        from pywinauto.keyboard import send_keys  # noqa: PLC0415

        opener = self._control(window, target, timeout)
        result_criteria: dict[str, Any] = {"auto_id": target.result_auto_id}
        if target.result_control_type:
            result_criteria["control_type"] = target.result_control_type
        pause = target.pause_seconds or 0.4

        for position in range(target.max_tries):
            self._invoke(opener, target)
            time.sleep(0.5)
            keys = "{HOME}" if position == 0 else f"{{HOME}}{{DOWN {position}}}"
            send_keys(f"{keys}{{ENTER}}", pause=pause)
            time.sleep(0.5)

            dialog_spec = window.native.child_window(**result_criteria)
            try:
                dialog_spec.wait("exists visible", timeout=timeout, retry_interval=0.3)
            except self._timeout_error_types():
                logger.debug(
                    "select_export_format: no dialog appeared for entry %d", position
                )
                continue
            dialog = dialog_spec.wrapper_object()
            try:
                title = dialog.window_text() or ""
            except Exception:  # noqa: BLE001 - a dialog that will not answer
                title = ""

            if target.value.lower() in title.lower():
                logger.info(
                    "Export format menu: '%s' matched at entry %d", title, position
                )
                return

            logger.debug(
                "Export format menu: '%s' at entry %d is not '%s' - trying the next entry",
                title,
                position,
                target.value,
            )
            try:
                dialog_spec.child_window(
                    auto_id="btnCancel", control_type="Button"
                ).wrapper_object().click_input()
            except Exception as exc:  # noqa: BLE001 - Escape is the fallback
                logger.warning(
                    "Could not click Cancel on the '%s' dialog (%s) - sending "
                    "Escape instead",
                    title,
                    exc,
                )
                send_keys("{ESC}", pause=pause)
            time.sleep(0.4)

        raise ControlNotFoundError(
            f"Could not find a '{target.value}' entry in the export format "
            f"menu after {target.max_tries} tries.",
            hint=(
                "Open 'Export To' by hand in NS Retail and check whether that "
                "format is still offered."
            ),
        )

    # -- grids -----------------------------------------------------------
    #: Cells report themselves like "Include row 3"; this pulls out the 3.
    _ROW_NUMBER_RE = re.compile(r"row\s+(\d+)\s*$", re.IGNORECASE)

    def _cell_value(self, cell: Any) -> str:
        try:
            return str(cell.legacy_properties().get("Value", "") or "")
        except Exception:  # noqa: BLE001 - a cell that will not answer
            return ""

    def _grid_cells(self, grid: Any, prefix: str) -> dict[int, Any]:
        """The currently loaded cells of one column, keyed by row number."""
        cells: dict[int, Any] = {}
        try:
            items = grid.descendants(control_type="DataItem")
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not read the grid rows: %s", exc)
            return cells
        for item in items:
            name = getattr(item.element_info, "name", "") or ""
            if not name.lower().startswith(prefix.lower()):
                continue
            match = self._ROW_NUMBER_RE.search(name)
            if match:
                cells[int(match.group(1))] = item
        return cells

    def _row_labels(self, grid: Any, label_prefix: str) -> dict[int, str]:
        """What each visible row is called, so the log names real columns."""
        labels: dict[int, str] = {}
        for number, cell in self._grid_cells(grid, label_prefix).items():
            labels[number] = self._cell_value(cell) or f"row {number}"
        return labels

    def _tick(self, cell: Any, label: str) -> bool:
        """Turn one cell on, verifying rather than assuming.

        Every attempt is followed by a re-read: a blind second attempt on a
        checkbox that did work would turn it back off.

        The grid's in-place checkbox editor toggles right away, but the row's
        DataItem does not report the new value until the edit is committed -
        normally by clicking the next row, which is why this only showed up
        on the last row of the grid, with no "next" row to commit it. A Tab
        moves focus off the cell and commits it without that side effect.
        """
        for attempt, action in enumerate(("click", "space"), start=1):
            try:
                if action == "click":
                    cell.click_input()
                else:
                    cell.type_keys(" ", set_foreground=True)
            except Exception as exc:  # noqa: BLE001 - try the other technique
                logger.debug("Could not %s '%s': %s", action, label, exc)
                continue
            time.sleep(0.15)
            if self._cell_value(cell).lower().startswith("check"):
                logger.info("Ticked '%s' (by %s)", label, action)
                return True
            from pywinauto.keyboard import send_keys  # noqa: PLC0415

            send_keys("{TAB}")
            time.sleep(0.15)
            if self._cell_value(cell).lower().startswith("check"):
                logger.info("Ticked '%s' (by %s, committed with Tab)", label, action)
                return True
            logger.debug("'%s' still off after %s (attempt %d)", label, action, attempt)
        return False

    def _check_all_rows(self, grid: Any, target: UiTarget) -> None:
        """Tick every row of a grid column, scrolling to reach them all.

        Only unticked rows are touched, so rows the operator had already
        selected stay selected. The grid loads rows as they scroll into view,
        so this pages down until nothing new appears.
        """
        prefix = target.value or "Include"
        label_prefix = "Column Name"
        seen: set[str] = set()
        failures: list[str] = []
        ticked = 0

        for page in range(1, MAX_GRID_PAGES + 1):
            cells = self._grid_cells(grid, prefix)
            if not cells:
                raise ControlNotFoundError(
                    f"No '{prefix}' cells were found in the grid for "
                    f"'{target.label()}'.",
                    hint="The column name may differ; inspect the dialog to check.",
                )
            labels = self._row_labels(grid, label_prefix)
            page_labels = {labels.get(number, f"row {number}") for number in cells}

            for number in sorted(cells):
                cell = cells[number]
                label = labels.get(number, f"row {number}")
                if self._cell_value(cell).lower().startswith("check"):
                    continue
                if self._tick(cell, label):
                    ticked += 1
                else:
                    failures.append(label)

            if page_labels and page_labels <= seen:
                break  # nothing new on this page - the end of the grid
            seen |= page_labels

            try:
                grid.type_keys("{PGDN}", set_foreground=True)
                time.sleep(0.2)
            except Exception as exc:  # noqa: BLE001 - a grid that will not scroll
                logger.debug("Could not scroll the grid: %s", exc)
                break
        else:
            logger.warning(
                "Stopped after %d pages of the grid - it may be longer than expected.",
                MAX_GRID_PAGES,
            )

        logger.info(
            "Column selection: %d row(s) ticked, %d row(s) seen in total.",
            ticked,
            len(seen),
        )
        if failures:
            raise ControlNotFoundError(
                "These columns could not be ticked: " + ", ".join(failures),
                hint="Tick them by hand once and check whether they stay ticked.",
            )

    def _read_text(self, wrapper: Any) -> str:
        """Best effort read of what a control currently shows.

        The legacy MSAA 'Value' is checked first: for some controls - the
        Windows Save As dialog's "Save as type" combo box, confirmed live -
        UIA's Name/window_text() returns the static label ('Save as type:')
        rather than the selected item, while the legacy Value correctly
        holds it ('CSV Document (*.csv)'). window_text()/get_value() are
        the fallback for controls that expose no legacy Value at all.
        """
        try:
            legacy_value = str(wrapper.legacy_properties().get("Value", "") or "")
        except Exception:  # noqa: BLE001 - not every control exposes this
            legacy_value = ""
        if legacy_value:
            return legacy_value
        for reader in ("window_text", "get_value"):
            method = getattr(wrapper, reader, None)
            if method is None:
                continue
            try:
                text = method()
            except Exception:  # noqa: BLE001 - not every control exposes text
                continue
            if text:
                return str(text)
        return ""

    def _confirm_text(
        self, wrapper: Any, target: UiTarget, value: str, before: str, method: str
    ) -> bool:
        """Read the control back, so a value that did not stick is not silent.

        A date picker may reformat what it was given ("08 September 2026"
        becoming "08-09-2026"), which is fine; what matters is that the value
        changed and the digits survived.
        """
        after = self._read_text(wrapper)
        logger.info(
            "Set %s to '%s' via %s - the control now shows '%s' (was '%s')",
            target.label(),
            value,
            method,
            after,
            before,
        )
        if not after:
            return True  # nothing readable; assume the setter worked

        digits_wanted = {part for part in _digit_groups(value)}
        digits_shown = {part for part in _digit_groups(after)}
        if digits_wanted and not digits_wanted & digits_shown:
            logger.warning(
                "%s still shows '%s' after being set to '%s' - the format may be "
                "wrong for this field.",
                target.label(),
                after,
                value,
            )
            return False
        return True

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

    def window_from_handle(self, handle: int) -> WindowRef | None:
        ensure_available()
        try:
            spec = self.desktop().window(handle=handle)
            wrapper = spec.wrapper_object()
        except Exception as exc:  # noqa: BLE001 - the window may have gone
            logger.debug("Could not address window %s: %s", handle, exc)
            return None
        return self._wrap(spec, wrapper)

    def describe_window(self, window: WindowRef, *, max_depth: int = 8) -> ControlInfo:
        ensure_available()
        wrapper = window.native.wrapper_object()
        return self._describe_element(wrapper.element_info, depth=0, max_depth=max_depth)

    #: Reading state costs a wrapper per control, so only ask where it means
    #: something - a grid cell that can be ticked, a field that holds a value.
    STATEFUL_TYPES = (
        "CheckBox",
        "DataItem",
        "ListItem",
        "RadioButton",
        "Edit",
        "ComboBox",
        "Custom",
    )

    def _element_state(self, element: Any) -> tuple[str, str]:
        """Toggle state and current value of a control, where it has them."""
        if getattr(element, "control_type", "") not in self.STATEFUL_TYPES:
            return "", ""
        try:
            wrapper = self._pywinauto().controls.uiawrapper.UIAWrapper(element)
        except Exception:  # noqa: BLE001 - not every element can be wrapped
            return "", ""

        toggle = ""
        try:
            state = wrapper.get_toggle_state()
            toggle = {0: "off", 1: "on", 2: "indeterminate"}.get(state, str(state))
        except Exception:  # noqa: BLE001 - no toggle pattern on this control
            toggle = ""

        value = ""
        try:
            value = str(wrapper.legacy_properties().get("Value", "") or "")
        except Exception:  # noqa: BLE001 - no legacy pattern either
            value = ""
        return toggle, value

    def _describe_element(self, element: Any, *, depth: int, max_depth: int) -> ControlInfo:
        try:
            rectangle = str(element.rectangle)
        except Exception:  # noqa: BLE001
            rectangle = ""
        toggle_state, value = self._element_state(element)
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
            toggle_state=toggle_state,
            value=value,
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
