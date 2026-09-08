# Phase 2 — mapping NS Retail's controls (do this on the Windows PC)

Phase 1 built the whole workflow except one thing: **which control is which**
inside NS Retail v4.0.3. Nothing in this project guesses that. This document
lists exactly what to collect and where to put it.

Everything below is **read-only** — the inspection tool never clicks or types.

## 0. Prepare

```bat
cd ns-retail-report-automation
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
pip install -e .
copy config\config.example.json config\config.json
copy config\selectors.example.json config\selectors.json
ns-retail-automation --check
```

`--check` must report that Python and pywinauto are available. Then start NS
Retail and log in by hand (automatic login stays off for now).

Tip: if a screen shows nothing useful with the default UI Automation backend,
try `--ui-backend win32` on the inspector, and set
`"application": {"ui_backend": "win32"}` in the config if that works better.

## 1. Windows to identify

```bat
python -m ns_retail_automation.inspect --windows
```

Record for each window the **title** (turn it into a regular expression) and the
**class name**:

| Key in `selectors.json` | Which window | Collect |
|---|---|---|
| `main` | The NS Retail main window | title, class name |
| `login` | The login window (only if you later enable automatic login) | title, class name |
| `report_viewer` | The window that opens after clicking **Report** | title, class name |
| `export_dialog` | The dialog that appears after **Export To** (if it is a separate window) | title, class name |
| `save_dialog` | The "save the file where?" dialog | title, class name |

Example once collected:

```json
"windows": {
  "main": { "title_re": "NS Retail.*", "class_name": "WindowsForms10.Window.8.app.0.xxxxx" }
}
```

Titles often contain the branch or financial year — prefer `title_re` with a
pattern that survives those changes (e.g. `"NS Retail.*"`).

## 2. Screens to capture

For each screen: put NS Retail on that screen, run the inspector, click the NS
Retail window during the 5-second countdown, and save the output.

```bat
python -m ns_retail_automation.inspect --delay 5 --json reports_menu.json
```

| # | Put NS Retail on this screen | Fills in step(s) |
|---|---|---|
| 1 | Main window, before opening anything | `open_reports` |
| 2 | Reports section open | `open_stock_reports` |
| 3 | Stock Reports open | `select_purchase_report` |
| 4 | Purchases screen with the date field visible | `set_date`, `search`, `generate_report` |
| 5 | Report Viewer, after a report was generated | `export_to` |
| 6 | The Export To menu / format dialog open | `choose_csv_format`, `confirm_export` |
| 7 | The save dialog open | `save_set_path`, `save_confirm` |

For each control write down: **control type**, **name**, **automation id**,
**class name**. The inspector prints "Selector suggestions" you can copy
directly.

Also note these behaviours, which decide the timeouts and the waiting logic:

* Roughly how long report generation takes (seconds) → `reports.purchases.generation_timeout_seconds`.
* Whether **Export To** is a menu, a toolbar button, or a dropdown.
* Whether the CSV choice is a list item, a radio button or a combo box entry.
* Whether the save dialog is the standard Windows one (class `#32770`) or a custom one.
* Whether the save dialog accepts a **full path** in its filename box (this is the
  easiest way to save into the right folder), or whether the folder must be
  navigated to separately.
* Any confirmation popup that appears (e.g. "file exists, replace?", "export
  complete") — those become extra targets, with `"optional": true` when they do
  not always appear.
* Whether NS Retail adds its own extension to the filename.

## 3. Write the selectors

Fill `config/selectors.json`. Each step is a list of controls acted on in order:

```json
"steps": {
  "open_reports": {
    "window": "main",
    "targets": [
      { "action": "invoke", "title": "Reports", "control_type": "MenuItem" }
    ]
  },
  "set_date": {
    "window": "main",
    "targets": [
      { "action": "set_text", "auto_id": "dtpFrom", "value": "{date_dd_mm_yyyy}" },
      { "action": "set_text", "auto_id": "dtpTo",   "value": "{date_dd_mm_yyyy}" }
    ]
  },
  "save_set_path": {
    "window": "save_dialog",
    "targets": [
      { "action": "set_text", "control_type": "Edit", "auto_id": "1148", "value": "{destination_path}" }
    ]
  }
}
```

**Actions:** `invoke` (UI Automation, no mouse — prefer it), `click` (real click
on the control's own rectangle), `select`, `expand`, `set_text`, `menu_select`
(classic menu path such as `"Reports->Stock Reports"`), `wait`.

**Placeholders** available in `value`:

* date step: `{date_dd_mm_yyyy}`, `{date_dd_mm_yyyy_dots}`, `{date_dd_mm_yyyy_slashes}`,
  `{date_mm_dd_yyyy_slashes}`, `{date_iso}`, `{date_ddmmyyyy}`, `{dd}`, `{mm}`, `{yyyy}`
* save step: `{destination_path}`, `{destination_folder}`, `{filename}`, `{filename_stem}`
* login step: `{username}`, `{password}`

Other useful fields: `"optional": true`, `"found_index": 0`,
`"timeout_seconds": 60`, `"title_re"`, `"class_name_re"`.

## 4. Verify

```bat
ns-retail-automation --check
```

It must report **"All required windows and steps are mapped."** Then try one
real run on a date you can afford to re-generate:

```bat
ns-retail-automation --report purchases --date yesterday
```

Read `logs\automation_<today>.log` — every step is logged. If a step fails, the
error names the step and the control, so only that entry in `selectors.json`
needs fixing.

## 5. What to send back for help

If a step will not work, share:

1. The inspector output for that screen (`--json` file is ideal).
2. The relevant part of `config/selectors.json`.
3. The lines from `logs\automation_<date>.log` around the failure.
