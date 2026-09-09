"""Selector definitions - how each automation step finds its controls.

The selectors are DATA, not code, so that the control details discovered on the
Windows PC (Phase 2) can be filled in without touching any Python file, and a
single broken step can be fixed on its own.

Nothing here invents NS Retail control names.  Until ``config/selectors.json``
is filled in, every step reports that it is not mapped yet.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..errors import ConfigError, SelectorNotConfiguredError

#: Actions a step may perform on a control.  Keep this list small and explicit.
VALID_ACTIONS = (
    "click",          # click_input() - a real mouse click on the control's centre
    "invoke",         # UI Automation Invoke pattern - no mouse movement
    "select",         # select an item in a list / combo / tab
    "expand",         # expand a menu or tree node
    "set_text",       # type a value into an edit control
    "send_keys",      # send keystrokes to the control, e.g. "{TAB}" or "^a"
    "menu_select",    # walk a classic menu path, e.g. "Reports->Stock Reports"
    "check_all_rows", # tick every unticked row of a grid, scrolling through it
    "wait",           # only wait for the control to exist (no interaction)
)

#: How to choose when several controls match the same description.
VALID_PICKS = ("first", "last", "topmost", "bottommost", "largest")

#: Criteria accepted inside a target's "parent" block.
PARENT_CRITERIA_FIELDS = (
    "auto_id",
    "title",
    "title_re",
    "control_type",
    "class_name",
    "class_name_re",
    "found_index",
)

#: Named windows a step can be scoped to.
DEFAULT_WINDOW_KEYS = ("main", "login", "report_viewer", "export_dialog", "save_dialog")


@dataclass(frozen=True)
class UiTarget:
    """One control to find, and what to do with it."""

    action: str = "click"
    description: str = ""
    #: Empty means "the window the step runs in". Set it when a single step
    #: has to reach into another window, such as a dialog it just opened.
    window: str = ""
    control_type: str = ""
    title: str = ""
    title_re: str = ""
    auto_id: str = ""
    class_name: str = ""
    class_name_re: str = ""
    found_index: int | None = None
    value: str = ""
    optional: bool = False
    timeout_seconds: float | None = None
    #: Which one to use when the criteria match several controls. Left empty,
    #: several matches is an error rather than a coin toss.
    pick: str = ""
    #: Optional container to search inside. Use it when the control itself has
    #: no stable identity - NS Retail's date fields hold an Edit whose
    #: automation id is a window handle and changes on every launch, but their
    #: parent ComboBox is reliably "dtpFromDate" / "dtpToDate".
    parent: dict[str, Any] = field(default_factory=dict)

    def parent_criteria(self) -> dict[str, Any]:
        return {k: v for k, v in self.parent.items() if k in PARENT_CRITERIA_FIELDS and v != ""}

    def search_criteria(self) -> dict[str, Any]:
        """Translate to pywinauto ``child_window`` keyword arguments."""
        criteria: dict[str, Any] = {}
        if self.control_type:
            criteria["control_type"] = self.control_type
        if self.title:
            criteria["title"] = self.title
        if self.title_re:
            criteria["title_re"] = self.title_re
        if self.auto_id:
            criteria["auto_id"] = self.auto_id
        if self.class_name:
            criteria["class_name"] = self.class_name
        if self.class_name_re:
            criteria["class_name_re"] = self.class_name_re
        if self.found_index is not None:
            criteria["found_index"] = self.found_index
        return criteria

    def label(self) -> str:
        if self.description:
            return self.description
        parts = [f"{k}={v!r}" for k, v in self.search_criteria().items()]
        label = ", ".join(parts) or "(no criteria)"
        if self.parent:
            inside = ", ".join(f"{k}={v!r}" for k, v in self.parent_criteria().items())
            label = f"{label} inside [{inside}]"
        return label

    def targets_window_itself(self) -> bool:
        """A send_keys target with no criteria types into the window itself."""
        return self.action == "send_keys" and not self.search_criteria()

    def validate(self, where: str) -> None:
        if self.action not in VALID_ACTIONS:
            raise ConfigError(
                f"{where}: action '{self.action}' is not supported.",
                hint="Valid actions: " + ", ".join(VALID_ACTIONS),
            )
        if self.targets_window_itself():
            if not self.value:
                raise ConfigError(f"{where}: 'send_keys' needs a 'value'.")
            return
        if not self.search_criteria():
            raise ConfigError(
                f"{where}: no search criteria given.",
                hint=(
                    "Provide at least one of auto_id, title, title_re, "
                    "control_type or class_name."
                ),
            )
        if self.action in ("set_text", "send_keys", "menu_select") and not self.value:
            raise ConfigError(
                f"{where}: action '{self.action}' needs a 'value'."
            )
        if self.pick and self.pick not in VALID_PICKS:
            raise ConfigError(
                f"{where}: pick '{self.pick}' is not supported.",
                hint="Valid picks: " + ", ".join(VALID_PICKS),
            )
        if self.parent:
            if not isinstance(self.parent, dict):
                raise ConfigError(f"{where}: 'parent' must be an object.")
            unknown = set(self.parent) - set(PARENT_CRITERIA_FIELDS)
            if unknown:
                raise ConfigError(
                    f"{where}: unknown field(s) in 'parent': {', '.join(sorted(unknown))}.",
                    hint="Allowed: " + ", ".join(PARENT_CRITERIA_FIELDS),
                )
            if not self.parent_criteria():
                raise ConfigError(f"{where}: 'parent' has no usable criteria.")


@dataclass(frozen=True)
class WindowSpec:
    """How to recognise one of the application's windows.

    NS Retail keeps almost everything inside its main form: the print preview,
    the Include/Exclude dialog and the report screens are all child windows,
    not top-level ones. ``inside`` names the window they live in; without it
    the window is looked for among the desktop's top-level windows.
    """

    key: str
    title: str = ""
    title_re: str = ""
    class_name: str = ""
    control_type: str = ""
    auto_id: str = ""
    inside: str = ""
    timeout_seconds: float | None = None

    def is_configured(self) -> bool:
        return bool(self.title or self.title_re or self.class_name or self.auto_id)

    def search_criteria(self) -> dict[str, Any]:
        criteria: dict[str, Any] = {}
        if self.title:
            criteria["title"] = self.title
        if self.title_re:
            criteria["title_re"] = self.title_re
        if self.class_name:
            criteria["class_name"] = self.class_name
        if self.control_type:
            criteria["control_type"] = self.control_type
        if self.auto_id:
            criteria["auto_id"] = self.auto_id
        return criteria


@dataclass(frozen=True)
class Step:
    """A named automation step: the window it happens in and its targets."""

    name: str
    window: str = "main"
    targets: list[UiTarget] = field(default_factory=list)
    description: str = ""

    def is_configured(self) -> bool:
        return bool(self.targets)


@dataclass(frozen=True)
class Selectors:
    """All window specs and steps loaded from ``config/selectors.json``."""

    windows: dict[str, WindowSpec] = field(default_factory=dict)
    steps: dict[str, Step] = field(default_factory=dict)
    source_path: Path | None = None

    # -- lookups ---------------------------------------------------------
    def window(self, key: str) -> WindowSpec:
        spec = self.windows.get(key)
        if spec is None or not spec.is_configured():
            raise SelectorNotConfiguredError(
                f"The '{key}' window has not been identified yet.",
                hint=(
                    "On the Windows PC run 'python -m ns_retail_automation.inspect "
                    "--windows', then add the window title or class name under "
                    f"\"windows\": {{\"{key}\": ...}} in config/selectors.json."
                ),
            )
        return spec

    def has_window(self, key: str) -> bool:
        spec = self.windows.get(key)
        return spec is not None and spec.is_configured()

    def step(self, name: str) -> Step:
        step = self.steps.get(name)
        if step is None or not step.is_configured():
            raise SelectorNotConfiguredError(
                f"Automation step '{name}' has not been mapped to NS Retail yet.",
                hint=(
                    "On the Windows PC run 'python -m ns_retail_automation.inspect' "
                    "with NS Retail on the relevant screen, then add the control "
                    f"details under \"steps\": {{\"{name}\": ...}} in "
                    "config/selectors.json."
                ),
            )
        return step

    def has_step(self, name: str) -> bool:
        step = self.steps.get(name)
        return step is not None and step.is_configured()

    def missing_steps(self, required: list[str]) -> list[str]:
        return [name for name in required if not self.has_step(name)]


DEFAULT_SELECTOR_LOCATIONS = (
    Path("config/selectors.json"),
    Path("selectors.json"),
)


def find_selectors_file(explicit: str | Path | None = None) -> Path | None:
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise ConfigError(f"Selector file '{path}' does not exist.")
        return path
    for candidate in DEFAULT_SELECTOR_LOCATIONS:
        if candidate.is_file():
            return candidate
    return None


def load_selectors(path: str | Path | None = None) -> Selectors:
    """Load selectors, returning an empty (unmapped) set when the file is absent."""
    selector_path = find_selectors_file(path)
    if selector_path is None:
        return Selectors()

    try:
        raw = json.loads(selector_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"'{selector_path}' is not valid JSON (line {exc.lineno}, column "
            f"{exc.colno}: {exc.msg})."
        ) from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"'{selector_path}' must contain a JSON object.")

    return build_selectors(raw, source_path=selector_path)


def build_selectors(raw: dict[str, Any], *, source_path: Path | None = None) -> Selectors:
    windows: dict[str, WindowSpec] = {}
    for key, value in (raw.get("windows") or {}).items():
        if key.startswith("_"):
            continue
        if not isinstance(value, dict):
            raise ConfigError(f"windows.{key} must be an object.")
        windows[key] = WindowSpec(key=key, **_filtered(value, WindowSpec, f"windows.{key}"))

    steps: dict[str, Step] = {}
    for name, value in (raw.get("steps") or {}).items():
        if name.startswith("_"):
            continue
        if isinstance(value, list):
            value = {"targets": value}
        if not isinstance(value, dict):
            raise ConfigError(f"steps.{name} must be an object or a list of targets.")
        targets = []
        for index, target_raw in enumerate(value.get("targets") or []):
            if not isinstance(target_raw, dict):
                raise ConfigError(f"steps.{name}.targets[{index}] must be an object.")
            where = f"steps.{name}.targets[{index}]"
            target = UiTarget(**_filtered(target_raw, UiTarget, where))
            target.validate(where)
            targets.append(target)
        steps[name] = Step(
            name=name,
            window=str(value.get("window", "main")),
            description=str(value.get("description", "")),
            targets=targets,
        )

    return Selectors(windows=windows, steps=steps, source_path=source_path)


def _filtered(data: dict[str, Any], cls: type, where: str) -> dict[str, Any]:
    known = set(cls.__dataclass_fields__) - {"key", "name"}
    unknown = {k for k in data if not k.startswith("_")} - known
    if unknown:
        raise ConfigError(
            f"{where}: unknown field(s) {', '.join(sorted(unknown))}.",
            hint="Allowed fields: " + ", ".join(sorted(known)),
        )
    return {k: v for k, v in data.items() if k in known}
