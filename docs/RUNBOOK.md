# NS Retail Report Automation — Runbook

Everything needed to run, fix, extend or hand over this project. Written so
someone arriving cold — a person or a new Claude session — can pick it up
without the original conversation.

Last full update: 2026-09-09.

---

## 1. What this replaces

A daily manual routine in **NS Retail v4.0.3** (WinForms desktop app, titled
"Victory Bazars"):

```
open NS Retail → log in → Reports → Stock Reports → Purchases
  → set From Date and To Date to yesterday
  → F3 → tick every column → Apply and Search
  → Report → wait for the preview
  → Export To → CSV File → OK
  → type a file name → Save into the day-wise folder
```

The automation performs all of it and files the CSV as, for example:

```
D:\2026-27 DAY WISE REPORTS\
  2026-27 DAY WISE SALE REPORTS\
    9.SEPTEMBER\
      08.09.2026\
        08.09.2026.csv
```

---

## 2. Daily use

```bat
scripts\run_report.bat                    REM dry run for yesterday
scripts\run_report.bat go                 REM real run for yesterday
scripts\run_report.bat go 08-09-2026      REM real run for one date
```

Or directly:

```bat
.venv\Scripts\python.exe -m ns_retail_automation --report purchases --date yesterday
```

Useful flags: `--dry-run`, `--check`, `--list-steps`, `--on-existing skip|overwrite|duplicate|ask`,
`-v` for full detail, `--yes` for unattended runs.

Exit codes: `0` success · `1` automation failed · `2` configuration problem ·
`3` skipped because the report already existed.

Logs: `logs\automation_YYYY-MM-DD.log`, one file per day, 30 days retained.

### Safety rules the program follows

* An existing report is **never** silently overwritten — the default is to skip.
* The destination folder is created before NS Retail is touched.
* A leftover report preview is closed before generating, so an old report can
  never be exported under today's name.
* The export format is verified twice before anything is written.
* After saving, the file must exist and be non-empty, or the run fails.

---

## 3. Setting up a new PC

Two prerequisites cost a full day to discover. Install them **first**:

1. **Microsoft Visual C++ Redistributable** —
   https://aka.ms/vs/17/release/vc_redist.x64.exe
   Without `mfc140u.dll`, pywinauto cannot import `win32ui` and nothing runs.
2. **Python 3.12** (not the newest release) —
   https://www.python.org/downloads/release/python-3129/
   Tick "Add python.exe to PATH". pywin32 lags behind new Python versions; 3.14
   installs fine and then fails at import.

Then:

```bat
cd /d C:\nsretail
git clone https://github.com/sunkaramahesh09/ns-retail-report-automation.git app
cd app
scripts\setup_windows.bat
```

Setup picks `py -3.12` automatically, rebuilds `.venv` if it finds one on an
unusable Python, registers pywin32's DLLs, and creates your settings file. It
is safe to re-run at any time.

Then set the report folder:

```bat
.venv\Scripts\python.exe -m ns_retail_automation.configure --base-path "D:\2026-27 DAY WISE REPORTS"
scripts\run_report.bat
```

Confirm `--check` reports **`NS Retail automation : available`**.

### Settings

Settings live at `%USERPROFILE%\.ns_retail_automation\config.json`, deliberately
**outside** the project folder so re-downloading or re-cloning never wipes them.

Never edit that file by hand — a Windows path typed into JSON breaks it
(`D:\2026` is an invalid escape). Use:

```bat
scripts\set_report_folder.bat
.venv\Scripts\python.exe -m ns_retail_automation.configure --show
.venv\Scripts\python.exe -m ns_retail_automation.configure --fix
```

Known values: test PC `C:\NSRetail Reports TEST`; office PC
`D:\2026-27 DAY WISE REPORTS`. Filename format is dots — `08.09.2026.csv`.
Automatic login is off; the operator logs in by hand.

---

## 4. How the project is put together

```
src/ns_retail_automation/
  main.py              CLI
  inspect.py           read-only control inspector
  configure.py         change settings without editing JSON
  diagnose_win32.py    names the DLL behind a win32ui failure
  logging_config.py    daily log file
  errors.py            every error carries a plain message and a hint
  platform_support.py  Windows / package detection (imports for real)
  config/              settings + credentials (env, keyring or prompt)
  automation/
    base.py            platform-independent interface
    windows.py         pywinauto / UI Automation backend
    selectors.py       control definitions, loaded from config/selectors.json
    ns_retail.py       the workflow, one method per step
  reports/             plan → run → verify
  filesystem/          folders, filenames, duplicates, verification
  utils/               dates, retries, explicit waits
config/selectors.json  THE CONTROL MAP - tracked in git, read this first
```

**The central idea:** control identities are *data*, not code. Fixing a broken
step means editing `config/selectors.json`, not Python. Every entry there
carries a comment saying whether it was VERIFIED (run against the app),
CONFIRMED (read from an inspection) or TODO, and why it is written that way.

Actions available to a target: `invoke` (preferred), `click`, `select`,
`expand`, `set_text`, `send_keys`, `menu_select`, `wait`, `verify_text`,
`check_all_rows`, `invoke_until_gone`.
Extras: `parent` (search inside a container), `window` (reach into another
window), `pick` (choose between duplicates), `optional`, `focus`,
`pause_seconds`, `timeout_seconds`.

---

## 5. What we learned about NS Retail

Everything here was measured on the real application. It is why the code looks
the way it does.

| Behaviour | Consequence |
|---|---|
| WinForms **MDI** app: the preview, the F3 dialog, the CSV options dialog and even Windows' own Save As are **child windows of `frmMain`** | Window specs use `"inside": "main"` and `auto_id`, not top-level titles |
| The main window title changes with the active screen (`Victory Bazars - [Report Viewer]`) | Match `^Victory Bazars`, never the full title |
| The WindowsForms10 class suffix (`...fb11c8_r8_ad1`) changes between launches | Never match on class name |
| Date pickers contain an `Edit` whose automation id is a window handle, different every launch | Found through the parent ComboBox `dtpFromDate` / `dtpToDate` |
| Typing `08 September 2026` into a date picker works | `{date_dd_month_yyyy}` placeholder |
| **Each visit to Stock Reports opens another copy of the Purchases screen** and never closes the old one | Three were found stacked. Two make every control ambiguous, so `close_report_screens` runs first |
| There is **no separate "Purchases" chooser** — Stock Reports opens it directly | `select_purchase_report` waits for `ucPurchases` to confirm the screen instead |
| The report preview stays open after an export | Closed before generating, or the next run exports yesterday's data under today's name |
| The Include/Exclude grid reports cells as `Checked` / `Unchecked`, and only loads visible rows | `check_all_rows` ticks only unticked rows and pages down |
| The **export format menu is invisible to UI Automation** — a scan of every open window with it on screen found none of its entries | Cannot be addressed by selector at all |
| The Export To split button repeats the **last used format** | Used deliberately (CSV), then verified twice: the options dialog must be the CSV one, and the save dialog's file type must say CSV |
| DevExpress menus **drop key presses** sent at full speed, and open on the last-used entry | The keyboard fallback needs `{UP 12}{DOWN 7}{ENTER}` at `pause_seconds: 0.4` |
| The Save As dialog accepts a **full path** in its File name box (`Edit` auto_id `1001`) | No folder navigation at all — the whole path is typed at once |

### The control map, in short

| Thing | How it is found |
|---|---|
| main window | `title_re: ^Victory Bazars` |
| report preview | child of main, `auto_id: PrintPreviewRibbonFormExBase` |
| F3 dialog | child of main, `auto_id: frmIncludeExclude` |
| CSV options | child of preview, `auto_id: LinesForm` |
| Save As | child of preview, `title: Save As`, `class_name: #32770` |
| Reports tab | `TabItem "Reports"` inside `ribbonControl1` |
| Stock Reports | `Button "Stock Reports"` inside `ribbonControl1` |
| dates | `Edit` inside `dtpFromDate` / `dtpToDate` |
| column grid | `Table auto_id gcIncExc` |
| Apply and Search | `btnApplyAndSearch` |
| Report | `btnReport` |
| close a report screen | `btnClose` |
| Export To | `SplitButton "Export To"` |
| CSV options OK | `btnOK` |
| file name box | `Edit auto_id 1001` |
| Save | `Button auto_id 1` |

---

## 6. Diagnostic tools

Each exists because a specific problem was hard to see. All are read-only
except `try_step` and `send_keys`.

| Command | Use it when |
|---|---|
| `scripts\inspect_windows.bat` | list every top-level window |
| `scripts\inspect_windows.bat <name> "Victory Bazars.*"` | capture a whole screen to `docs\captures\` |
| `scripts\inspect_dialog.bat <auto_id>` | dump a dialog that lives inside the main window |
| `scripts\find_control.bat <text>` | **the workhorse** — is this control there, is it visible/enabled/ticked, what is it inside, how many are there |
| `scripts\capture_popup.bat <text> [secs]` | search *every* window — for popups and Windows' own dialogs |
| `scripts\try_step.bat <step> [date]` | run one step against the live app |
| `scripts\try_step.bat a+b+c` | run steps back-to-back — the only way to test a popup, since clicking back to the console closes it |
| `scripts\try_step_probe.bat <step> <text>` | run a step then immediately search for what it revealed |
| `scripts\send_keys.bat <step> "<keys>"` | try a route through a menu UI Automation cannot see |
| `scripts\fix_pywin32.bat` | `DLL load failed while importing win32ui` |
| `--check`, `--list-steps`, `--dry-run` | what is ready, what is mapped, what would happen |

---

## 7. Troubleshooting — every problem hit so far

| Symptom | Cause and fix |
|---|---|
| `ImportError: DLL load failed while importing win32ui` | `mfc140u.dll` missing. Install the VC++ Redistributable. Not a Python version problem, despite appearances |
| `--check` says available but the run fails | Fixed: `--check` now imports the packages for real rather than only looking for them |
| `is not valid JSON ... Invalid \escape` | A Windows path typed into the settings file. Use `configure --base-path` or `--fix` |
| `'scripts' is not recognized` | Backslash, not forward slash: `scripts\setup_windows.bat` |
| `Activate.ps1 cannot be loaded` | PowerShell policy. Use `.venv\Scripts\python.exe -m ...` and skip activation |
| `'choose_csv_format' is not a date` | cmd splits arguments on commas. Join steps with `+` |
| `Could not find the control` while a dialog is open | A modal dialog disables everything behind it. The error now lists the open dialogs |
| `N controls match — refusing to guess` | NS Retail left several copies of a screen open. `close_report_screens` clears them; restarting NS Retail also works |
| Setup reuses a broken `.venv` | Fixed: setup rebuilds it when the interpreter is unusable. `scripts\setup_windows.bat fresh` forces it |
| A step "succeeded" but nothing changed | `set_text` now reads the field back and warns if the value did not take |
| Wrong export format | Verified in two places; the run stops rather than writing the wrong thing |

---

## 8. Where the project stands

See `docs/STATUS.md` for the live state. As of 2026-09-09: all fourteen
workflow steps are mapped; connect, `open_reports`, `open_stock_reports`,
`set_date`, `open_column_settings`, `apply_and_search` and the export chain are
verified against the running application; the full end-to-end run has not yet
completed.

153 tests pass on macOS, covering dates, fiscal years, folder structure,
filenames, existing-file handling, configuration, selectors, retries, waits,
the CLI and the workflow's ordering. Windows-only tests are marked and skipped
elsewhere.

### Next

1. Complete the end-to-end run and fix what it turns up.
2. Decide whether the automation should close the preview and report screen
   when it finishes, leaving NS Retail clean.
3. Set up the office PC (prerequisites above, then `base_path` = `D:\...`).
4. Map `login` if unattended running is wanted.
5. Package with PyInstaller so no Python install is needed:
   `pyinstaller --onefile --name NS-Retail-Report-Automation --paths src src\ns_retail_automation\main.py`

---

## 9. Working agreements

* **Never invent** an automation id, a control name, a window title or a screen
  coordinate. Verify against the running application, and record in the
  selector file how it was verified.
* Prefer accessibility properties over clicks by position; `invoke` over
  `click`.
* No long sleeps. Every wait names what it waits for and times out.
* A wrong report filed in the right place is worse than a failed run. Where an
  assumption cannot be removed, verify it and fail loudly.
* Fix one step at a time against the real application, and commit each fix with
  the reasoning.
