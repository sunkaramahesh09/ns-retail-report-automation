"""Operating system detection and dependency checks.

Importing this module is safe everywhere; it never imports Windows-only
packages at module level.
"""

from __future__ import annotations

import importlib.util
import platform
import sys
from dataclasses import dataclass

#: Packages needed for the Windows automation to work.
WINDOWS_PACKAGES = ("pywinauto", "win32api", "comtypes")
#: Optional packages that unlock extra behaviour.
OPTIONAL_PACKAGES = ("keyring", "pyautogui")


def is_windows() -> bool:
    return sys.platform == "win32"


def platform_name() -> str:
    return f"{platform.system()} {platform.release()}".strip()


@dataclass(frozen=True)
class PackageStatus:
    name: str
    installed: bool
    version: str = ""
    required: bool = True


def _package_status(name: str, *, required: bool) -> PackageStatus:
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ValueError):
        spec = None
    if spec is None:
        return PackageStatus(name=name, installed=False, required=required)
    version = ""
    try:  # best effort - win32api has no dist name of its own
        from importlib.metadata import version as dist_version

        dist = {"win32api": "pywin32"}.get(name, name)
        version = dist_version(dist)
    except Exception:  # noqa: BLE001 - version is cosmetic
        version = ""
    return PackageStatus(name=name, installed=True, version=version, required=required)


def check_packages() -> list[PackageStatus]:
    """Report which automation packages are importable here."""
    statuses = [_package_status(name, required=True) for name in WINDOWS_PACKAGES]
    statuses += [_package_status(name, required=False) for name in OPTIONAL_PACKAGES]
    return statuses


def missing_required_packages() -> list[str]:
    return [s.name for s in check_packages() if s.required and not s.installed]


@dataclass(frozen=True)
class Environment:
    platform: str
    python_version: str
    is_windows: bool
    packages: list[PackageStatus]

    @property
    def can_automate(self) -> bool:
        return self.is_windows and not [
            p for p in self.packages if p.required and not p.installed
        ]

    def summary_lines(self) -> list[str]:
        lines = [
            f"Platform        : {self.platform}",
            f"Python          : {self.python_version}",
            f"Windows         : {'yes' if self.is_windows else 'no'}",
            "Packages:",
        ]
        for pkg in self.packages:
            mark = "ok     " if pkg.installed else ("MISSING" if pkg.required else "absent ")
            tag = "required" if pkg.required else "optional"
            version = f" {pkg.version}" if pkg.version else ""
            lines.append(f"  [{mark}] {pkg.name}{version} ({tag})")
        if self.can_automate:
            lines.append("NS Retail automation : available")
        elif not self.is_windows:
            lines.append(
                "NS Retail automation : NOT available on this computer "
                "(non-Windows). Date, folder and configuration logic still work."
            )
        else:
            missing = ", ".join(p.name for p in self.packages if p.required and not p.installed)
            lines.append(
                f"NS Retail automation : NOT available - missing package(s): {missing}. "
                "Run: pip install -r requirements.txt"
            )
        return lines


def describe_environment() -> Environment:
    return Environment(
        platform=platform_name(),
        python_version=platform.python_version(),
        is_windows=is_windows(),
        packages=check_packages(),
    )
