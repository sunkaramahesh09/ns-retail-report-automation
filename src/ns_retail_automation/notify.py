"""On-screen messages for the operator.

The automation runs on a desktop somebody else is using, so it announces
itself before taking over the screen and says what happened when it is done.

Everything here degrades quietly: on a machine with no desktop (a test runner,
a server) the warning proceeds and the result is printed instead. A missing
notification must never stop a report being filed.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from .platform_support import is_windows

logger = logging.getLogger(__name__)

#: Set to 1 to suppress every window - used by the tests, and useful for a
#: run started from a script that must never block on a dialog.
ENV_DISABLE = "NS_RETAIL_NO_POPUP"

WARNING_TITLE = "NS Retail automation"


@dataclass(frozen=True)
class NotifySettings:
    enabled: bool = True
    warn_before_seconds: int = 60
    show_result: bool = True
    allow_postpone: bool = True


def warn_before_run(settings: NotifySettings, *, what: str) -> bool:
    """Warn that the screen is about to be taken over.

    Returns True to go ahead, False if the operator asked to stop. A window
    that cannot be shown counts as "go ahead": the run matters more than the
    warning.
    """
    seconds = int(settings.warn_before_seconds)
    if not _windows_allowed(settings) or seconds <= 0:
        return True

    message = (
        f"{what}\n\n"
        "This uses the mouse and keyboard, so please do not touch this "
        "computer while it runs.\n\n"
        "It usually takes one to three minutes."
    )
    try:
        return _countdown_window(message, seconds, allow_postpone=settings.allow_postpone)
    except Exception as exc:  # noqa: BLE001 - never block the run
        logger.debug("Could not show the countdown window: %s", exc)
        print(f"\n{message}\n")
        return True


def show_result(settings: NotifySettings, *, title: str, message: str, success: bool) -> None:
    """Tell the operator how it went, in a window they cannot miss."""
    if not _windows_allowed(settings) or not settings.show_result:
        logger.info("%s: %s", title, message.replace("\n", " "))
        return
    try:
        _message_box(title, message, success=success)
    except Exception as exc:  # noqa: BLE001 - never turn a good run into a failure
        logger.debug("Could not show the result window: %s", exc)


def _windows_allowed(settings: NotifySettings) -> bool:
    """Windows are for the operator at the machine, nobody else.

    They are skipped off Windows - where this project is only ever developed
    and tested - and whenever the environment asks for silence. A dialog that
    nobody can dismiss would hang the run forever.
    """
    if not settings.enabled:
        return False
    if os.environ.get(ENV_DISABLE, "").strip() in ("1", "true", "yes"):
        return False
    return is_windows()


# --------------------------------------------------------------------------
# Windows
# --------------------------------------------------------------------------
def _countdown_window(message: str, seconds: int, *, allow_postpone: bool) -> bool:
    import tkinter as tk  # noqa: PLC0415 - optional, and only on a real desktop

    decision = {"proceed": True}
    root = tk.Tk()
    root.title(WARNING_TITLE)
    root.attributes("-topmost", True)
    root.resizable(False, False)

    frame = tk.Frame(root, padx=24, pady=20)
    frame.pack()

    tk.Label(
        frame, text="NS Retail automation is about to start", font=("Segoe UI", 13, "bold")
    ).pack(anchor="w")
    tk.Label(frame, text=message, font=("Segoe UI", 10), justify="left", wraplength=420).pack(
        anchor="w", pady=(10, 14)
    )

    remaining = tk.StringVar(value=f"Starting in {seconds} seconds...")
    tk.Label(frame, textvariable=remaining, font=("Segoe UI", 11)).pack(anchor="w")

    buttons = tk.Frame(frame)
    buttons.pack(anchor="e", pady=(16, 0))

    def start_now() -> None:
        root.destroy()

    def postpone() -> None:
        decision["proceed"] = False
        root.destroy()

    if allow_postpone:
        tk.Button(buttons, text="Not now", width=12, command=postpone).pack(side="left", padx=(0, 8))
    tk.Button(buttons, text="Start now", width=12, command=start_now).pack(side="left")

    def tick(left: int) -> None:
        if left <= 0:
            root.destroy()
            return
        remaining.set(f"Starting in {left} seconds...")
        root.after(1000, tick, left - 1)

    root.after(0, tick, seconds)
    _centre(root)
    root.mainloop()

    if not decision["proceed"]:
        logger.warning("The operator asked to postpone the run.")
    return decision["proceed"]


def _message_box(title: str, message: str, *, success: bool) -> None:
    import tkinter as tk  # noqa: PLC0415
    from tkinter import messagebox  # noqa: PLC0415

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        if success:
            messagebox.showinfo(title, message, parent=root)
        else:
            messagebox.showerror(title, message, parent=root)
    finally:
        root.destroy()


def _centre(window) -> None:
    window.update_idletasks()
    width = window.winfo_width()
    height = window.winfo_height()
    x = (window.winfo_screenwidth() - width) // 2
    y = (window.winfo_screenheight() - height) // 3
    window.geometry(f"+{max(x, 0)}+{max(y, 0)}")
