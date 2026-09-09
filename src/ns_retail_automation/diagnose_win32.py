"""Work out exactly which DLL is missing behind a win32ui import failure.

    python -m ns_retail_automation.diagnose_win32

"DLL load failed while importing win32ui: The specified module could not be
found" does not say WHICH module is missing - it is usually a dependency of
win32ui, not win32ui itself. This loads each dependency by hand so the missing
one is named.
"""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

#: DLLs win32ui needs. mfc140u.dll comes from the Microsoft Visual C++
#: Redistributable and is the usual culprit.
CANDIDATE_DLLS = (
    "vcruntime140.dll",
    "msvcp140.dll",
    "mfc140u.dll",
    f"pywintypes{sys.version_info.major}{sys.version_info.minor}.dll",
    f"pythoncom{sys.version_info.major}{sys.version_info.minor}.dll",
)


def site_packages() -> Path:
    for entry in sys.path:
        if entry.endswith("site-packages"):
            return Path(entry)
    return Path(sys.prefix) / "Lib" / "site-packages"


def report_folder(folder: Path, label: str) -> None:
    print(f"\n{label}: {folder}")
    if not folder.is_dir():
        print("  (folder does not exist)")
        return
    interesting = sorted(
        item.name
        for item in folder.iterdir()
        if item.suffix.lower() in (".dll", ".pyd")
    )
    if not interesting:
        print("  (no .dll or .pyd files)")
        return
    for name in interesting[:25]:
        print(f"  {name}")
    if len(interesting) > 25:
        print(f"  ... and {len(interesting) - 25} more")


def main() -> int:
    if sys.platform != "win32":
        print("This diagnostic only means anything on Windows.")
        return 2

    packages = site_packages()
    report_folder(packages / "pythonwin", "pythonwin folder (holds win32ui.pyd)")
    report_folder(packages / "pywin32_system32", "pywin32_system32 folder")

    print("\nLoading each dependency by hand:")
    missing: list[str] = []
    for name in CANDIDATE_DLLS:
        try:
            ctypes.WinDLL(name)
        except OSError as exc:
            print(f"  MISSING  {name}   ({exc.__class__.__name__})")
            missing.append(name)
        else:
            print(f"  found    {name}")

    print("\nImporting the modules:")
    for module in ("win32api", "pythoncom", "win32ui", "pywinauto"):
        try:
            __import__(module)
        except Exception as exc:  # noqa: BLE001 - reporting is the point
            print(f"  FAILED   {module}: {exc}")
        else:
            print(f"  ok       {module}")

    if missing:
        print("\nWhat to do:")
        if any(name.startswith(("mfc", "vcruntime", "msvcp")) for name in missing):
            print(
                "  Install the Microsoft Visual C++ Redistributable (x64):\n"
                "      https://aka.ms/vs/17/release/vc_redist.x64.exe\n"
                "  Then open a new Command Prompt and run "
                "scripts\\fix_pywin32.bat again."
            )
        else:
            print(
                "  Run:  .venv\\Scripts\\python.exe "
                ".venv\\Scripts\\pywin32_postinstall.py -install"
            )
    else:
        print("\nAll of those DLLs load. If win32ui still fails, send this output back.")

    print(f"\nPATH entries containing 'python' or 'pywin':")
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if "python" in entry.lower() or "pywin" in entry.lower():
            print(f"  {entry}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
