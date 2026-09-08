"""Explicit waiting helpers.

Rule of thumb for this project: never ``time.sleep`` for a fixed long period.
Poll for a condition with a timeout and raise a descriptive error instead.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from ..errors import TimeoutError_

logger = logging.getLogger(__name__)

T = TypeVar("T")

DEFAULT_POLL_INTERVAL = 0.5


def wait_until(
    condition: Callable[[], T | None],
    *,
    timeout: float,
    interval: float = DEFAULT_POLL_INTERVAL,
    description: str = "condition",
    timeout_error: type[TimeoutError_] = TimeoutError_,
    swallow: tuple[type[BaseException], ...] = (),
) -> T:
    """Poll ``condition`` until it returns something truthy.

    ``swallow`` lists exception types treated as "not ready yet" - useful while
    a window is still opening and the UI library raises lookup errors.
    """
    deadline = time.monotonic() + timeout
    last_error: BaseException | None = None
    while True:
        try:
            result = condition()
            if result:
                return result
        except swallow as exc:  # type: ignore[misc]
            last_error = exc
        if time.monotonic() >= deadline:
            message = f"{description} did not happen within {timeout:.0f} seconds."
            if last_error is not None:
                message += f" Last error: {last_error}"
            raise timeout_error(message)
        time.sleep(interval)


def wait_for_file(
    path: str | Path,
    *,
    timeout: float = 60.0,
    interval: float = DEFAULT_POLL_INTERVAL,
    min_size: int = 1,
    stable_for: float = 1.0,
) -> Path:
    """Wait until ``path`` exists, is non-empty and has stopped growing.

    ``stable_for`` guards against reading a file while the export is still
    writing it.
    """
    target = Path(path)
    deadline = time.monotonic() + timeout
    last_size = -1
    stable_since: float | None = None

    while True:
        if target.exists():
            size = target.stat().st_size
            if size >= min_size:
                now = time.monotonic()
                if size == last_size:
                    if stable_since is not None and now - stable_since >= stable_for:
                        return target
                else:
                    stable_since = now
                last_size = size
        if time.monotonic() >= deadline:
            if target.exists():
                raise TimeoutError_(
                    f"The file '{target}' was created but was still being written "
                    f"after {timeout:.0f} seconds."
                )
            raise TimeoutError_(
                f"The file '{target}' was not created within {timeout:.0f} seconds."
            )
        time.sleep(interval)


def wait_for_absence(
    condition: Callable[[], bool],
    *,
    timeout: float,
    interval: float = DEFAULT_POLL_INTERVAL,
    description: str = "condition",
) -> None:
    """Wait until ``condition`` stops being true (e.g. a busy dialog closes)."""
    wait_until(
        lambda: not condition(),
        timeout=timeout,
        interval=interval,
        description=f"{description} to finish",
    )
