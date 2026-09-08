from __future__ import annotations

import time

import pytest

from ns_retail_automation.errors import AutomationError, TimeoutError_
from ns_retail_automation.utils.retry import first_success, retry_call
from ns_retail_automation.utils.waits import wait_for_file, wait_until


class TestRetry:
    def test_success_on_the_first_attempt(self):
        calls = []
        assert retry_call(lambda: calls.append(1) or "done", attempts=3, delay=0) == "done"
        assert len(calls) == 1

    def test_retries_then_succeeds(self):
        attempts = {"n": 0}

        def flaky():
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise ValueError("not yet")
            return "ok"

        assert retry_call(flaky, attempts=3, delay=0) == "ok"
        assert attempts["n"] == 3

    def test_the_last_error_is_raised(self):
        with pytest.raises(ValueError, match="always"):
            retry_call(lambda: (_ for _ in ()).throw(ValueError("always")), attempts=2, delay=0)

    def test_unlisted_exceptions_are_not_retried(self):
        attempts = {"n": 0}

        def boom():
            attempts["n"] += 1
            raise KeyError("nope")

        with pytest.raises(KeyError):
            retry_call(boom, attempts=3, delay=0, exceptions=(ValueError,))
        assert attempts["n"] == 1

    def test_first_success_falls_through_to_the_next_strategy(self):
        def fails():
            raise RuntimeError("no")

        assert first_success([fails, lambda: "second"], description="test") == "second"

    def test_first_success_reports_every_failure(self):
        def fails():
            raise RuntimeError("no")

        with pytest.raises(AutomationError) as excinfo:
            first_success([fails], description="opening the menu")
        assert "opening the menu" in excinfo.value.message


class TestWaits:
    def test_returns_as_soon_as_the_condition_holds(self):
        started = time.monotonic()
        assert wait_until(lambda: "ready", timeout=5, interval=0.01) == "ready"
        assert time.monotonic() - started < 1

    def test_timeout_message_names_the_thing_waited_for(self):
        with pytest.raises(TimeoutError_) as excinfo:
            wait_until(lambda: False, timeout=0.2, interval=0.05, description="The Report Viewer")
        assert "The Report Viewer did not happen within 0 seconds." in excinfo.value.message

    def test_swallowed_errors_count_as_not_ready(self):
        state = {"n": 0}

        def condition():
            state["n"] += 1
            if state["n"] < 3:
                raise LookupError("window not there yet")
            return True

        assert wait_until(
            condition, timeout=2, interval=0.01, description="window", swallow=(LookupError,)
        )

    def test_wait_for_file_returns_the_path(self, tmp_path):
        target = tmp_path / "report.csv"
        target.write_text("Item,Qty\n")
        assert wait_for_file(target, timeout=2, interval=0.05, stable_for=0.05) == target

    def test_wait_for_file_times_out_clearly(self, tmp_path):
        with pytest.raises(TimeoutError_, match="was not created"):
            wait_for_file(tmp_path / "missing.csv", timeout=0.2, interval=0.05)

    def test_wait_for_file_ignores_an_empty_file(self, tmp_path):
        target = tmp_path / "report.csv"
        target.write_text("")
        with pytest.raises(TimeoutError_):
            wait_for_file(target, timeout=0.3, interval=0.05, stable_for=0.05)
