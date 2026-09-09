"""Error hierarchy for NS Retail Report Automation.

Every error carries a message that a non-developer can understand.  The CLI
prints ``[ERROR] <message>`` plus an optional ``hint`` telling the user what to
do next, so avoid raw tracebacks reaching the user for expected failures.
"""

from __future__ import annotations


class AutomationError(Exception):
    """Base class for every error this application raises deliberately."""

    #: Short, human readable explanation of what went wrong.
    default_message = "An unexpected automation error occurred."
    #: Optional follow-up action the user can take.
    default_hint: str | None = None

    def __init__(self, message: str | None = None, hint: str | None = None) -> None:
        self.message = message or self.default_message
        self.hint = hint if hint is not None else self.default_hint
        super().__init__(self.message)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


# --------------------------------------------------------------------------
# Configuration / environment
# --------------------------------------------------------------------------
class ConfigError(AutomationError):
    default_message = "The configuration file is invalid."
    default_hint = "Check config/config.json against config/config.example.json."


class ConfigNotFoundError(ConfigError):
    default_message = "No configuration file was found."
    default_hint = "Copy config/config.example.json to config/config.json and edit it."


class UnsupportedPlatformError(AutomationError):
    default_message = "This action can only run on Windows."
    default_hint = (
        "NS Retail is a Windows desktop application. Copy this project onto the "
        "Windows PC and run it there."
    )


class MissingDependencyError(AutomationError):
    default_message = "A required Windows automation package is not installed."
    default_hint = "On Windows run: pip install -r requirements.txt"


# --------------------------------------------------------------------------
# Application lifecycle
# --------------------------------------------------------------------------
class ApplicationNotFoundError(AutomationError):
    default_message = "NS Retail could not be found on this computer."
    default_hint = (
        "Set application.executable_path in the configuration file to the full "
        "path of the NS Retail .exe file."
    )


class ApplicationLaunchError(AutomationError):
    default_message = "NS Retail could not be started."


class ApplicationNotRespondingError(AutomationError):
    default_message = "NS Retail stopped responding."
    default_hint = "Close NS Retail manually and run the automation again."


class ConnectionError_(AutomationError):
    """Named with a trailing underscore so it does not shadow the builtin."""

    default_message = "Could not connect to the running NS Retail window."


class LoginError(AutomationError):
    default_message = "Could not log in to NS Retail."
    default_hint = (
        "Check the configured credentials, or disable automatic login and log in "
        "by hand before running the automation."
    )


# --------------------------------------------------------------------------
# UI interaction
# --------------------------------------------------------------------------
class SelectorNotConfiguredError(AutomationError):
    """Raised when a UI step has no verified selector yet (Phase 2 work)."""

    default_message = "This automation step has not been mapped to NS Retail yet."
    default_hint = (
        "Run the inspection tool on Windows (python -m ns_retail_automation.inspect) "
        "and record the control details in config/selectors.json."
    )


class WindowNotFoundError(AutomationError):
    default_message = "The expected NS Retail window did not appear."


class ControlNotFoundError(AutomationError):
    default_message = "A required control could not be found on screen."


class AmbiguousControlError(AutomationError):
    """More than one control matches - acting on the wrong one is dangerous."""

    default_message = "More than one control matches this description."
    default_hint = (
        "Narrow the selector, or add \"pick\" to say which one to use "
        "(first, last, topmost, bottommost)."
    )


class TimeoutError_(AutomationError):
    """Named with a trailing underscore so it does not shadow the builtin."""

    default_message = "The operation did not finish within the allowed time."


class ReportGenerationError(AutomationError):
    default_message = "The report could not be generated."


class ReportViewerError(AutomationError):
    default_message = "The Report Viewer window did not behave as expected."


class ExportError(AutomationError):
    default_message = "The report could not be exported to CSV."


# --------------------------------------------------------------------------
# Filesystem
# --------------------------------------------------------------------------
class StorageError(AutomationError):
    default_message = "The report could not be stored in the destination folder."


class DestinationUnavailableError(StorageError):
    default_message = "The destination folder is not available."
    default_hint = "Check that the drive is connected and the base path is correct."


class FileAlreadyExistsError(StorageError):
    default_message = "A report file already exists for this date."
    default_hint = (
        "Use --on-existing overwrite or --on-existing duplicate if you really want "
        "to run again."
    )


class FileNotCreatedError(StorageError):
    default_message = "The export finished but no file was created."
