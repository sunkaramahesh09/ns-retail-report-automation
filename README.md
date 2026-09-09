# NS Retail Report Automation

Automates the daily report chore for **NS Retail v4.0.3** (Windows desktop app),
for four reports — Purchases, Dispatches, Sales, Stock As on date:

> open NS Retail → Reports → Stock Reports → <report> → pick the date → Search →
> Report → Report Viewer → Export To → CSV → save into the day-wise folder.

The automation itself **only runs on Windows** (that is where NS Retail lives).
Everything else — dates, folder structure, filenames, configuration, logging,
CLI, tests — runs anywhere, so the project can be developed on macOS.

---

**Start here:** [`docs/RUNBOOK.md`](docs/RUNBOOK.md) — how to run it, how to set up
a PC, everything learned about NS Retail's controls, and every problem hit so
far with its fix. [`docs/STATUS.md`](docs/STATUS.md) has the current state.

## Status

See [`docs/STATUS.md`](docs/STATUS.md) for the full, actively-maintained
picture. Short version as of 2026-09-09:

| Area | State |
|---|---|
| Configuration, dates, folders, filenames, existing-file safety | **Implemented and tested** |
| Logging, CLI, dry run, environment checks | **Implemented and tested** |
| Windows automation layer (pywinauto / UI Automation) | **Implemented and verified live** |
| Read-only Windows inspection tool | **Implemented and used daily for diagnosis** |
| NS Retail control mapping (`config/selectors.json`) | **Done for all four reports** |
| Purchases, Dispatches | **Verified with real, successful runs** |
| Sales | Mapped; export step fails on this report's size (~8,300 pages) — see STATUS.md |
| Stock As on date | Mapped and dry-run verified; not yet run live |
| Chained runs (every enabled report, one after another) | Chaining mechanism verified live; a full four-report run is blocked on the Sales issue above |

The control details for NS Retail are deliberately **not** in the code. Nothing
in this project guesses an automation id, a control name or a screen
coordinate. They live in `config/selectors.json`, filled in on the Windows PC
using the inspection tool.

---

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pip install -e .                   # gives you the ns-retail-automation command
```

The Windows-only packages (pywinauto, pywin32, comtypes) are marked
`sys_platform == "win32"`, so the same command works on macOS — they are just
skipped there.

## Configure

```bash
cp config/config.example.json config/config.json
```

`config/config.json` stays on your machine (it holds machine specific paths).
`config/selectors.json` — the NS Retail control mapping — **is tracked in git**,
so it is developed on the Mac and reaches the Windows PC with `git pull`. It
holds only window titles and control ids: no paths, no credentials.

Then edit `config/config.json`. The settings that matter first:

| Setting | Meaning |
|---|---|
| `application.executable_path` | Full path to `NSRetail.exe` (only needed if you want the tool to start it) |
| `application.process_name` | Executable name used to detect an already-running NS Retail |
| `storage.base_path` | Root of the report folders, e.g. `D:\2026-27 DAY WISE REPORTS` |
| `storage.*_template` | Folder and filename patterns (see below) |
| `storage.on_existing_file` | `skip` (default, safe), `overwrite`, `duplicate` or `ask` |
| `schedule.default_report_date` | `yesterday` (default), `today`, or a fixed date |
| `dates.fiscal_year_start_month` | `4` = Indian financial year (April→March); `1` = calendar year |
| `login.enabled` | `false` by default — log in by hand, the automation continues from there |

### Folder and filename templates

Templates are filled with these placeholders:

`{dd} {mm} {yyyy} {yy} {d} {m} {month_num} {month_num_padded} {month_name_upper}
{month_name} {month_name_short} {iso} {fy_label} {fy_start_year} {fy_end_year}`

The defaults reproduce the existing structure:

```
D:\2026-27 DAY WISE REPORTS\          storage.base_path
  2026-27 DAY WISE SALE REPORTS\      {fy_label} DAY WISE SALE REPORTS
    9.SEPTEMBER\                      {month_num}.{month_name_upper}
      08.09.2026\                     {dd}.{mm}.{yyyy}
        08.09.2026.csv                {dd}.{mm}.{yyyy}.csv
```

Missing month/date folders are created automatically
(`storage.create_missing_folders`). Set a folder template to `""` to drop that
level entirely.

### Credentials (only if you enable automatic login)

Passwords are never stored in the source or in `config.json`. Choose
`login.credential_source`:

* `env` — set `NS_RETAIL_USERNAME` / `NS_RETAIL_PASSWORD` (`setx NAME value` on Windows)
* `keyring` — Windows Credential Manager: `python -m keyring set "NS Retail" <username>`
* `prompt` — typed by the operator each run
* `none` — automatic login disabled (the default; log in by hand)

---

## Use

```bash
ns-retail-automation --dry-run                          # show what would happen
ns-retail-automation --date yesterday                   # run every enabled report, one after another
ns-retail-automation --date 08-09-2026 --on-existing duplicate
ns-retail-automation --report purchases --date yesterday   # just one report
ns-retail-automation --report dispatches --date yesterday
ns-retail-automation --report sales --date yesterday
ns-retail-automation --report stock_as_on_date --date yesterday
ns-retail-automation --check                            # what is ready, what is not
ns-retail-automation --list-reports
ns-retail-automation --inspect                          # Windows only, read-only
```

Without `--report`, every report with `enabled: true` in the configuration runs
for that date, in the order they appear in `config.json` (`scripts\run_report.bat`
uses this). They share one NS Retail session — the "report saved" popup after
each one is what the operator dismisses to move on to the next; a failure stops
the sequence there instead of pressing on to reports likely to hit the same
problem. Pass `--report <key>` to run only that one report.

Without installing, use `PYTHONPATH=src python3 -m ns_retail_automation ...`.

Dates accept `today`, `yesterday`, `2026-09-08`, `08-09-2026`, `08.09.2026`,
`08/09/2026` (day first).

Exit codes: `0` success · `1` automation failed · `2` configuration/usage
problem · `3` skipped because the report already existed.

### Dry run (works on macOS)

```
$ ns-retail-automation --report purchases --date yesterday --dry-run
DRY RUN - NS Retail will not be touched.

Report      : purchases
Date        : 07-09-2026 (Monday 07 September 2026)
Destination : D:\2026-27 DAY WISE REPORTS\2026-27 DAY WISE SALE REPORTS\9.SEPTEMBER\07.09.2026
Filename    : 07.09.2026.csv
Full path   : D:\...\07.09.2026\07.09.2026.csv
Existing file: no -> action 'create'

Not mapped to NS Retail yet (Phase 2 work):
  - open_reports
  ...
```

Windows paths such as `D:\...` are understood on macOS too (as
`PureWindowsPath`), so the dry run prints exactly what the Windows PC will use.

---

## Run it on the Windows PC

Download the project as a ZIP from GitHub (green **Code** button → **Download
ZIP**), extract it to a short path such as `C:\nsretail`, then open **Command
Prompt** in that folder (type `cmd` in Explorer's address bar) and run:

```bat
scripts\setup_windows.bat
```

That creates `.venv`, installs the packages, creates your settings file and
finishes with `--check`. It is safe to run again at any time.

**Your settings live outside the project folder**, at
`%USERPROFILE%\.ns_retail_automation\config.json`, so downloading a newer ZIP
never wipes them. Edit them with `scripts\edit_settings.bat`.

**Updating from a new ZIP:** extract it over the same folder and choose
*Replace the files in the destination*. `.venv` and your settings are untouched;
re-run `scripts\setup_windows.bat` afterwards only if the requirements changed.

Handy wrappers:

```bat
scripts\edit_settings.bat                REM open your settings in Notepad
scripts\run_report.bat                   REM dry run for yesterday
scripts\run_report.bat go                REM real run for yesterday
scripts\run_report.bat go 08-09-2026     REM real run for one date
scripts\inspect_windows.bat              REM list windows (read-only)
```

After that:

```bat
.venv\Scripts\activate
ns-retail-automation --dry-run
scripts\inspect_windows.bat                REM list every open window
scripts\inspect_windows.bat purchases      REM capture one screen to docs\captures\
```

A real run only works once `config/selectors.json` is filled in (Phase 2 below).

**Required Microsoft runtime.** pywinauto loads `win32ui`, which needs the MFC
runtime (`mfc140u.dll`) from the Microsoft Visual C++ Redistributable. Windows
does not always have it, and without it setup ends with
`ImportError: DLL load failed while importing win32ui`. Install it once per PC:

    https://aka.ms/vs/17/release/vc_redist.x64.exe

`scripts\fix_pywin32.bat` diagnoses this and names the missing DLL.

**Python version.** Use Python 3.12 — pywin32 and pywinauto lag behind the
newest releases. Setup picks `py -3.12` automatically when it is installed.

**PowerShell note.** PowerShell blocks virtual-environment activation by
default. Either allow it for the current window:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

…or skip activation entirely and call the interpreter directly — this always
works, in any shell:

```bat
.venv\Scripts\python.exe -m ns_retail_automation --dry-run
.venv\Scripts\python.exe -m pytest -q
```

## On Windows: inspecting NS Retail (Phase 2)

The inspection tool is **read-only** — it never clicks, types or closes
anything.

```bat
python -m ns_retail_automation.inspect --windows
python -m ns_retail_automation.inspect --delay 5
python -m ns_retail_automation.inspect --title-re "NS Retail.*" --depth 10 --json main.json
```

It prints the control tree (control type, name, automation id, class name) plus
copy-paste ready selector snippets. Work through
[`docs/PHASE2_UI_MAPPING.md`](docs/PHASE2_UI_MAPPING.md) — it lists exactly
which screens to capture and where each result goes in
`config/selectors.json`. Check your progress at any time with
`ns-retail-automation --check`.

---

## Project layout

```
src/ns_retail_automation/
  main.py                 CLI (--report/--date/--dry-run/--check/--inspect)
  inspect.py              read-only Windows control inspector
  logging_config.py       daily log file + console output
  errors.py               every error carries a plain-English message and a hint
  platform_support.py     Windows / package detection
  config/
    settings.py           JSON config -> validated dataclasses
    credentials.py        env vars, Windows Credential Manager, or prompt
  automation/
    base.py               platform-independent interface + UnsupportedBackend
    windows.py            pywinauto / UI Automation backend (Windows only)
    selectors.py          control definitions loaded from config/selectors.json
    ns_retail.py          the NS Retail workflow, step by step
  reports/
    base.py               plan -> run -> verify, existing-file safety
    purchase_report.py    Reports -> Stock Reports -> Purchases
    dispatch_report.py    Reports -> Stock Reports -> Dispatches
    sales_report.py       Reports -> Stock Reports -> Sales
    stock_as_on_date_report.py  Reports -> Stock Reports -> Stock As on date (single-date snapshot)
  filesystem/
    report_storage.py     folders, filenames, duplicates, verification
  utils/
    dates.py              today/yesterday/date/range + financial year
    retry.py, waits.py    explicit timeouts instead of long sleeps
config/                   config.example.json, selectors.example.json
tests/                    139 tests, all run on macOS
docs/                     Phase 2 mapping guide
logs/                     automation_YYYY-MM-DD.log
```

### Design rules this project follows

1. Controls are found by **accessibility properties** (automation id, name,
   control type, class name) — never by screen coordinates.
2. Selectors are **data**, not code: fixing a broken step means editing
   `config/selectors.json`, not rewriting Python.
3. **No long sleeps.** Every wait names what it waits for and times out
   (`wait_until`, `wait_for_file`, `retry_call`).
4. **Never overwrite a report silently** — the default is `skip`.
5. Windows-only code sits behind one interface, so macOS keeps working.
6. Errors are written for the employee running the tool, not for a developer.

## Tests

```bash
python3 -m pytest -q            # 139 tests, ~1s, no Windows required
python3 -m pytest -m windows    # Windows-only smoke tests (skipped elsewhere)
```

## Packaging (Phase 7 — not yet)

Once the automation is verified on Windows:

```bat
pyinstaller --onefile --name NS-Retail-Report-Automation ^
  --paths src src\ns_retail_automation\main.py
```

Ship the `.exe` next to a `config` folder. Do not package before the workflow
actually works on the real application.

## Roadmap

* **Phase 1 — done.** Structure, config, dates, folders, logging, CLI, dry run,
  inspection tool, tests.
* **Phase 2 — next.** Inspect NS Retail on Windows and fill in `config/selectors.json`.
* **Phase 3.** Verify launch → connect → Reports → Stock Reports → Purchases.
* **Phase 4.** Verify date → Search → Report.
* **Phase 5.** Verify Report Viewer → Export To → CSV → Save.
* **Phase 6.** Harden folder creation, verification, error recovery on the real app.
* **Phase 7.** Package as `NS-Retail-Report-Automation.exe`.
