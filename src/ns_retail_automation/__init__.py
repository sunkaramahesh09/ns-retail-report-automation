"""NS Retail Report Automation.

Automates: open NS Retail -> Reports -> Stock Reports -> Purchases -> date ->
Search -> Report -> export CSV -> save into the day-wise folder structure.

The automation itself only runs on Windows; the date, folder, configuration and
logging logic runs anywhere, so the project can be developed on macOS.
"""

__version__ = "0.4.1"
__all__ = ["__version__"]
