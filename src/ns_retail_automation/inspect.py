"""Read-only Windows UI inspection tool.

    python -m ns_retail_automation.inspect --windows      # list top-level windows
    python -m ns_retail_automation.inspect                # inspect the active window
    python -m ns_retail_automation.inspect --title-re "NS Retail.*" --json tree.json

It NEVER clicks, types or closes anything - it only reads accessibility
properties.  Use it on the Windows PC to discover the automation ids, names and
control types that go into ``config/selectors.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .automation import get_backend
from .automation.base import AutomationBackend, ControlInfo, WindowRef
from .automation.selectors import WindowSpec
from .errors import AutomationError
from .platform_support import describe_environment

INTERESTING_TYPES = (
    "Button",
    "MenuItem",
    "Menu",
    "Edit",
    "ComboBox",
    "List",
    "ListItem",
    "Tab",
    "TabItem",
    "TreeItem",
    "CheckBox",
    "RadioButton",
    "Hyperlink",
    "Custom",
    "Pane",
)


def format_control(control: ControlInfo, *, indent: str = "  ") -> str:
    pad = indent * control.depth
    bits = [f"{pad}{control.control_type or '?'}"]
    if control.name:
        bits.append(f'name="{control.name}"')
    if control.automation_id:
        bits.append(f'auto_id="{control.automation_id}"')
    if control.class_name:
        bits.append(f'class="{control.class_name}"')
    if not control.is_enabled:
        bits.append("(disabled)")
    if not control.is_visible:
        bits.append("(hidden)")
    return "  ".join(bits)


def walk(control: ControlInfo) -> list[ControlInfo]:
    found = [control]
    for child in control.children:
        found.extend(walk(child))
    return found


def print_tree(control: ControlInfo, *, stream=sys.stdout) -> None:
    for node in walk(control):
        print(format_control(node), file=stream)


def print_selector_suggestions(root: ControlInfo, *, stream=sys.stdout) -> None:
    """Print copy-paste ready selector snippets for the actionable controls."""
    print("\nSelector suggestions (copy into config/selectors.json):", file=stream)
    seen: set[str] = set()
    for node in walk(root):
        if node.control_type not in INTERESTING_TYPES:
            continue
        if not (node.name or node.automation_id):
            continue
        selector = node.suggested_selector()
        key = json.dumps(selector, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        selector = {"action": "invoke", **selector}
        print("  " + json.dumps(selector), file=stream)


def resolve_window(
    backend: AutomationBackend,
    *,
    title_re: str | None,
    class_name: str | None,
    delay: float,
) -> WindowRef:
    if title_re or class_name:
        spec = WindowSpec(key="inspected", title_re=title_re or "", class_name=class_name or "")
        window = backend.find_window(spec)
        if window is None:
            raise AutomationError(
                "No window matched "
                + ", ".join(f"{k}={v!r}" for k, v in spec.search_criteria().items()),
                hint="Run with --windows to see the windows that are open.",
            )
        return window

    if delay > 0:
        print(f"Click the NS Retail window you want to inspect - reading it in {delay:.0f} seconds...")
        for remaining in range(int(delay), 0, -1):
            print(f"  {remaining}...", end="\r", flush=True)
            time.sleep(1)
        print(" " * 20, end="\r")
    window = backend.active_window()
    if window is None:
        raise AutomationError(
            "Could not read the active window.",
            hint="Try --title-re to name the window instead.",
        )
    return window


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ns_retail_automation.inspect",
        description="Read-only inspection of Windows application controls.",
    )
    parser.add_argument("--windows", action="store_true", help="list all top-level windows and exit")
    parser.add_argument("--title-re", help="inspect the window whose title matches this regular expression")
    parser.add_argument("--class-name", help="inspect the window with this window class name")
    parser.add_argument(
        "--delay",
        type=float,
        default=5.0,
        help="seconds to wait before reading the active window (default: 5)",
    )
    parser.add_argument("--depth", type=int, default=8, help="how deep to walk the control tree (default: 8)")
    parser.add_argument("--json", dest="json_path", help="also write the full tree to this JSON file")
    parser.add_argument("--no-suggestions", action="store_true", help="do not print selector suggestions")
    parser.add_argument("--ui-backend", default="uia", choices=("uia", "win32"), help="pywinauto backend (default: uia)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    environment = describe_environment()
    if not environment.can_automate:
        print("The inspection tool needs Windows and the automation packages.\n")
        for line in environment.summary_lines():
            print(line)
        return 2

    backend = get_backend(args.ui_backend)

    try:
        if args.windows:
            print("Top-level windows:\n")
            for window in backend.list_windows():
                print(
                    f'  title="{window.title}"  class="{window.class_name}"  '
                    f"pid={window.process_id}  handle={window.handle}"
                )
            print(
                "\nUse the title (or a regular expression matching it) as the "
                '"title_re" of a window in config/selectors.json.'
            )
            return 0

        window = resolve_window(
            backend,
            title_re=args.title_re,
            class_name=args.class_name,
            delay=args.delay,
        )
        print(
            f'Window: title="{window.info.title}"  class="{window.info.class_name}"  '
            f"pid={window.info.process_id}\n"
        )
        tree = backend.describe_window(window, max_depth=args.depth)
        print_tree(tree)

        if not args.no_suggestions:
            print_selector_suggestions(tree)

        if args.json_path:
            path = Path(args.json_path)
            path.write_text(json.dumps(tree.as_dict(), indent=2), encoding="utf-8")
            print(f"\nFull control tree written to {path}")
        return 0
    except AutomationError as exc:
        print(f"[ERROR] {exc.message}")
        if exc.hint:
            print(f"        {exc.hint}")
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
