"""Retry helpers.

Used instead of long ``time.sleep`` calls: every operation states what it is
waiting for and for how long.
"""

from __future__ import annotations

import functools
import logging
import time
from collections.abc import Callable, Iterable
from typing import TypeVar

from ..errors import AutomationError

logger = logging.getLogger(__name__)

T = TypeVar("T")

DEFAULT_ATTEMPTS = 3
DEFAULT_DELAY = 1.0
DEFAULT_BACKOFF = 1.5


def retry_call(
    func: Callable[[], T],
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    delay: float = DEFAULT_DELAY,
    backoff: float = DEFAULT_BACKOFF,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    description: str | None = None,
    on_retry: Callable[[int, BaseException], None] | None = None,
) -> T:
    """Call ``func`` up to ``attempts`` times, re-raising the last failure."""
    if attempts < 1:
        raise ValueError("attempts must be at least 1")

    label = description or getattr(func, "__name__", "operation")
    current_delay = delay
    last_error: BaseException | None = None

    for attempt in range(1, attempts + 1):
        try:
            return func()
        except exceptions as exc:  # noqa: PERF203 - retry loop is the point
            last_error = exc
            if attempt >= attempts:
                break
            logger.warning(
                "%s failed (attempt %d of %d): %s - retrying in %.1fs",
                label,
                attempt,
                attempts,
                exc,
                current_delay,
            )
            if on_retry is not None:
                on_retry(attempt, exc)
            time.sleep(current_delay)
            current_delay *= backoff

    assert last_error is not None  # for type checkers
    raise last_error


def retry(
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    delay: float = DEFAULT_DELAY,
    backoff: float = DEFAULT_BACKOFF,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator form of :func:`retry_call`."""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: object, **kwargs: object) -> T:
            return retry_call(
                lambda: func(*args, **kwargs),
                attempts=attempts,
                delay=delay,
                backoff=backoff,
                exceptions=exceptions,
                description=func.__name__,
            )

        return wrapper

    return decorator


def first_success(
    candidates: Iterable[Callable[[], T]],
    *,
    description: str = "operation",
    error: type[AutomationError] = AutomationError,
) -> T:
    """Try each strategy in order and return the first one that succeeds.

    Used by the automation layer so a step can attempt UI Automation first and
    only then fall back to a less reliable technique.
    """
    failures: list[str] = []
    for candidate in candidates:
        try:
            return candidate()
        except Exception as exc:  # noqa: BLE001 - deliberately broad, reported below
            failures.append(f"{getattr(candidate, '__name__', 'strategy')}: {exc}")
    raise error(
        f"Every strategy for {description} failed.",
        hint="Tried: " + "; ".join(failures) if failures else None,
    )
