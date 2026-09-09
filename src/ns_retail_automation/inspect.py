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
    if control.toggle_state:
        bits.append(f"[{control.toggle_state}]")
    if control.value:
        bits.append(f'value="{control.value}"')
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


def walk_with_path(
    control: ControlInfo, path: tuple[ControlInfo, ...] = ()
) -> list[tuple[tuple[ControlInfo, ...], ControlInfo]]:
    """Every control, together with the ancestors that lead to it."""
    here = path + (control,)
    found = [(path, control)]
    for child in control.children:
        found.extend(walk_with_path(child, here))
    return found


def short_name(control: ControlInfo) -> str:
    label = control.automation_id or control.name or control.class_name or "?"
    return f"{control.control_type or '?'}[{label}]"


def print_matches(root: ControlInfo, needle: str, *, stream=sys.stdout) -> int:
    """Find controls by any part of their name, automation id or type.

    Answers the question that actually comes up: is this control there at all,
    is it visible and enabled, and what is it nested inside?
    """
    wanted = needle.lower()
    matches = [
        (path, node)
        for path, node in walk_with_path(root)
        if wanted in node.name.lower()
        or wanted in node.automation_id.lower()
        or wanted in node.control_type.lower()
    ]
    if not matches:
        print(f"No control matched '{needle}' anywhere in this window.", file=stream)
        print(
            "It may belong to a screen that is not open, or be collapsed out of "
            "the tree entirely.",
            file=stream,
        )
        return 0

    print(f"{len(matches)} control(s) matching '{needle}':\n", file=stream)
    for path, node in matches:
        state = []
        if not node.is_visible:
            state.append("HIDDEN")
        if not node.is_enabled:
            state.append("DISABLED")
        status = ("  <-- " + ", ".join(state)) if state else "  (visible, enabled)"
        print(f"  {short_name(node)}{status}", file=stream)
        if node.name:
            print(f"      name       : {node.name}", file=stream)
        if node.automation_id:
            print(f"      auto_id    : {node.automation_id}", file=stream)
        if node.class_name:
            print(f"      class_name : {node.class_name}", file=stream)
        if node.toggle_state:
            print(f"      ticked     : {node.toggle_state}", file=stream)
        if node.value:
            print(f"      value      : {node.value}", file=stream)
        if node.rectangle:
            print(f"      rectangle  : {node.rectangle}", file=stream)
        trail = " > ".join(short_name(item) for item in path) or "(top level)"
        print(f"      inside     : {trail}", file=stream)
        if node.children:
            print(
                "      children   : "
                + ", ".join(short_name(child) for child in node.children[:8]),
                file=stream,
            )
        print(file=stream)
    return len(matches)


def print_tree(control: ControlInfo, *, stream=sys.stdout) -> None:
    for node in walk(control):
        print(format_control(node), file=stream)


def print_actionable(root: ControlInfo, *, stream=sys.stdout) -> int:
    """Print only the controls worth automating.

    A full WinForms tree runs to thousands of lines; this keeps the ones that
    have a name or an automation id and a usable control type, which is what
    goes into config/selectors.json. The complete tree is still saved with
    --json.
    """
    shown = 0
    for node in walk(root):
        if node.control_type not in INTERESTING_TYPES and node.control_type != "Window":
            continue
        if not (node.name or node.automation_id):
            continue
        print(format_control(node), file=stream)
        shown += 1
    if shown == 0:
        print(
            "(no named controls found - try --ui-backend win32, or run the full "
            "tree without --actionable)",
            file=stream,
        )
    return shown


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


def countdown(seconds: float, what: str) -> None:
    print(f"{what} - reading in {seconds:.0f} seconds...")
    for remaining in range(int(seconds), 0, -1):
        print(f"  {remaining}...", end="\r", flush=True)
        time.sleep(1)
    print(" " * 24, end="\r")


def resolve_window(
    backend: AutomationBackend,
    *,
    title_re: str | None,
    class_name: str | None,
    delay: float | None,
) -> WindowRef:
    if title_re or class_name:
        if delay:
            # Gives the operator time to open a menu or dialog that would close
            # if they had to switch to the console first.
            countdown(delay, "Open the menu or dialog you want to capture")
        spec = WindowSpec(key="inspected", title_re=title_re or "", class_name=class_name or "")
        window = backend.find_window(spec)
        if window is None:
            raise AutomationError(
                "No window matched "
                + ", ".join(f"{k}={v!r}" for k, v in spec.search_criteria().items()),
                hint="Run with --windows to see the windows that are open.",
            )
        return window

    wait = 5.0 if delay is None else delay
    if wait > 0:
        countdown(wait, "Click the window you want to inspect")
    window = backend.active_window()
    if window is None:
        raise AutomationError(
            "Could not read the active window.",
            hint="Try --title-re to name the window instead.",
        )
    return window


def search_every_window(backend: AutomationBackend, needle: str, *, depth: int) -> int:
    """Look for a control across every open window.

    Popup menus and Windows' own dialogs are separate top-level windows, so a
    search inside the application finds nothing at all - which reads as "the
    control does not exist" when it is simply somewhere else.
    """
    total = 0
    for info in backend.list_windows():
        if not info.handle:
            continue
        window = backend.window_from_handle(info.handle)
        if window is None:
            continue
        try:
            tree = backend.describe_window(window, max_depth=depth)
        except Exception as exc:  # noqa: BLE001 - a window may close mid-scan
            print(f'(skipped "{info.title}": {exc})')
            continue
        matches = [
            node
            for node in walk(tree)
            if needle.lower() in node.name.lower()
            or needle.lower() in node.automation_id.lower()
        ]
        if not matches:
            continue
        total += len(matches)
        print(f'\n=== in window: title="{info.title}"  class="{info.class_name}" ===')
        print_matches(tree, needle)
    if total == 0:
        print(f"No control matched '{needle}' in any open window.")
    else:
        print(f"{total} match(es) across all windows.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ns_retail_automation.inspect",
        description="Read-only inspection of Windows application controls.",
    )
    parser.add_argument("--windows", action="store_true", help="list all top-level windows and exit")
    parser.add_argument(
        "--all-windows",
        action="store_true",
        help=(
            "search EVERY top-level window, not just one. Use it for things "
            "that live outside the application window - a ribbon popup menu, "
            "or a Windows Save As dialog"
        ),
    )
    parser.add_argument("--title-re", help="inspect the window whose title matches this regular expression")
    parser.add_argument("--class-name", help="inspect the window with this window class name")
    parser.add_argument(
        "--child",
        metavar="AUTO_ID",
        help=(
            "inspect a dialog nested inside the window, by its automation id "
            "(NS Retail's dialogs are child windows, e.g. frmIncludeExclude)"
        ),
    )
    parser.add_argument("--child-title", help="same as --child, but matched on the dialog's name")
    parser.add_argument(
        "--delay",
        type=float,
        default=None,
        help=(
            "seconds to wait before reading, so a menu or dialog can be opened "
            "first (default: 5 when no window is named, otherwise none)"
        ),
    )
    parser.add_argument("--depth", type=int, default=8, help="how deep to walk the control tree (default: 8)")
    parser.add_argument("--json", dest="json_path", help="also write the full tree to this JSON file")
    parser.add_argument(
        "--find",
        metavar="TEXT",
        help=(
            "show only the controls whose name, automation id or type contains "
            "TEXT, with where each one sits and whether it is visible/enabled"
        ),
    )
    parser.add_argument("--no-suggestions", action="store_true", help="do not print selector suggestions")
    parser.add_argument(
        "--actionable",
        action="store_true",
        help="print only named/identified controls instead of the whole tree (much shorter)",
    )
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
            if args.delay:
                countdown(args.delay, "Open the menu or dialog you want to see")
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

        if args.all_windows:
            if not args.find:
                print("--all-windows needs --find TEXT to look for.")
                return 2
            if args.delay:
                countdown(args.delay, "Open the menu or dialog you want to capture")
            return search_every_window(backend, args.find, depth=args.depth)

        window = resolve_window(
            backend,
            title_re=args.title_re,
            class_name=args.class_name,
            delay=args.delay,
        )
        if args.child or args.child_title:
            criteria: dict[str, str] = {}
            if args.child:
                criteria["auto_id"] = args.child
            if args.child_title:
                criteria["title"] = args.child_title
            window = backend.child_window_ref(window, criteria)
            print(f"Looking inside the dialog matching {criteria}\n")

        print(
            f'Window: title="{window.info.title}"  class="{window.info.class_name}"  '
            f"pid={window.info.process_id}\n"
        )
        tree = backend.describe_window(window, max_depth=args.depth)
        if args.find:
            print_matches(tree, args.find)
            if args.json_path:
                Path(args.json_path).write_text(
                    json.dumps(tree.as_dict(), indent=2), encoding="utf-8"
                )
                print(f"Full control tree written to {args.json_path}")
            return 0
        if args.actionable:
            total = len(walk(tree))
            shown = print_actionable(tree)
            print(f"\n({shown} named controls shown out of {total} in the tree)")
        else:
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
