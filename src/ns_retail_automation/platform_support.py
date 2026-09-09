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
    #: Why the package is unusable, when it is present but will not import.
    error: str = ""

    @property
    def usable(self) -> bool:
        return self.installed and not self.error


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

    # Being installed is not the same as being usable: pywin32 ships DLLs that
    # a plain "pip install" does not put where Windows can find them, so the
    # import fails at run time. Only a real import proves the package works.
    error = ""
    if required and is_windows():
        try:
            importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001 - any import failure disqualifies it
            error = f"{type(exc).__name__}: {exc}"

    return PackageStatus(
        name=name, installed=True, version=version, required=required, error=error
    )


def check_packages() -> list[PackageStatus]:
    """Report which automation packages are importable here."""
    statuses = [_package_status(name, required=True) for name in WINDOWS_PACKAGES]
    statuses += [_package_status(name, required=False) for name in OPTIONAL_PACKAGES]
    return statuses


def missing_required_packages() -> list[str]:
    """Required packages that are absent, or present but not importable."""
    return [s.name for s in check_packages() if s.required and not s.usable]


def package_problems() -> list[PackageStatus]:
    """Required packages that are installed but broken."""
    return [s for s in check_packages() if s.required and s.installed and s.error]


@dataclass(frozen=True)
class Environment:
    platform: str
    python_version: str
    is_windows: bool
    packages: list[PackageStatus]

    @property
    def can_automate(self) -> bool:
        return self.is_windows and not [
            p for p in self.packages if p.required and not p.usable
        ]

    def summary_lines(self) -> list[str]:
        lines = [
            f"Platform        : {self.platform}",
            f"Python          : {self.python_version}",
            f"Windows         : {'yes' if self.is_windows else 'no'}",
            "Packages:",
        ]
        for pkg in self.packages:
            if pkg.usable:
                mark = "ok     "
            elif pkg.error:
                mark = "BROKEN "
            elif pkg.required:
                mark = "MISSING"
            else:
                mark = "absent "
            tag = "required" if pkg.required else "optional"
            version = f" {pkg.version}" if pkg.version else ""
            lines.append(f"  [{mark}] {pkg.name}{version} ({tag})")
            if pkg.error:
                lines.append(f"           {pkg.error}")

        if self.can_automate:
            lines.append("NS Retail automation : available")
        elif not self.is_windows:
            lines.append(
                "NS Retail automation : NOT available on this computer "
                "(non-Windows). Date, folder and configuration logic still work."
            )
        else:
            broken = [p for p in self.packages if p.required and p.installed and p.error]
            absent = [p for p in self.packages if p.required and not p.installed]
            if absent:
                lines.append(
                    "NS Retail automation : NOT available - missing package(s): "
                    + ", ".join(p.name for p in absent)
                    + ". Run: scripts\\setup_windows.bat"
                )
            if broken:
                lines.append(
                    "NS Retail automation : NOT available - installed but not "
                    "loadable: " + ", ".join(p.name for p in broken)
                )
                if any(p.name in ("win32api", "pywinauto") for p in broken):
                    lines.append(
                        "           pywin32's DLLs are not registered. Fix it with: "
                        "scripts\\fix_pywin32.bat"
                    )
        return lines


def describe_environment() -> Environment:
    return Environment(
        platform=platform_name(),
        python_version=platform.python_version(),
        is_windows=is_windows(),
        packages=check_packages(),
    )
