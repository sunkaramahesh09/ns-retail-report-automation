# Where this project stands

Last updated: 2026-09-09, end of the mapping session.

## What works, verified against NS Retail v4.0.3

Run against the real application on the Windows PC, not just written:

| Step | State |
|---|---|
| detect / reuse a running NS Retail, connect to the main window | verified |
| `open_reports` — Reports tab on the ribbon | verified |
| `open_stock_reports` — Stock Reports button | verified |
| `set_date` — both date pickers, read back afterwards | verified |
| `open_column_settings` — F3 opens the Include/Exclude dialog | verified |
| `apply_and_search` — Apply and Search inside that dialog | verified |
| `export_to` → `choose_csv_format` → `confirm_export` | verified as a chain |
| destination folder + filename logic, dry run | verified |

Mapped from inspection but not yet exercised end to end:
`close_report_screens`, `select_purchase_report`, `include_all_columns`,
`generate_report`, `save_set_path`, `save_confirm`.

## What has never run yet

The **full end-to-end run**:

```bat
scripts\run_report.bat go 08-09-2026
```

The last attempt stopped at `close_report_screens` and `select_purchase_report`
because the actions that tolerate duplicate controls were dispatched after the
check that forbids duplicates. Fixed in 0.4.1; not retried since.

## Things learned about NS Retail that the code depends on

* It is a **WinForms MDI application**. Almost everything is a child window of
  `frmMain`, including the print preview (`PrintPreviewRibbonFormExBase`), the
  Include/Exclude dialog (`frmIncludeExclude`), the CSV options dialog
  (`LinesForm`) and even Windows' own Save As dialog. Window definitions use
  `"inside": "main"` rather than top-level title matching.
* The WindowsForms10 class-name suffix (`...fb11c8_r8_ad1`) changes between
  launches. Never match on it.
* Date pickers hold an `Edit` whose automation id is a window handle and
  changes every launch, so it is found through its parent ComboBox
  (`dtpFromDate` / `dtpToDate`). Typing `08 September 2026` works.
* **Each visit to Stock Reports opens another copy of the Purchases screen**
  and never closes the old one. Three were found stacked up. Two copies make
  every control on the screen ambiguous, so `close_report_screens` runs first.
* The report preview also stays open after an export. It is closed before
  generating, otherwise the next run would export the previous day's report
  under today's name.
* The export format list is **invisible to UI Automation** - a scan of every
  open window with the menu on screen found none of its entries. The split
  button repeats the last-used format, which is CSV at this site, so the
  automation uses that and verifies it twice: the options dialog must be the
  CSV one, and the save dialog's file type must say CSV. The keyboard route
  (`{UP 12}{DOWN 7}{ENTER}` at 0.4s per key) is recorded in the selector file
  as a fallback.
* The Include/Exclude grid reports each cell as `Checked` / `Unchecked`, so
  only unticked rows are touched and rows are paged through as the grid only
  loads what is visible.

## Environment prerequisites (both PCs)

* **Microsoft Visual C++ Redistributable** — without `mfc140u.dll`, pywinauto
  cannot import `win32ui` and nothing runs: https://aka.ms/vs/17/release/vc_redist.x64.exe
* **Python 3.12** — not the newest release; pywin32 lags behind.

## Configuration

Settings live at `%USERPROFILE%\.ns_retail_automation\config.json`, outside the
project folder, so re-downloading the project never wipes them.

* Test PC: `base_path` = `C:\NSRetail Reports TEST`
* Office PC: `base_path` = `D:\2026-27 DAY WISE REPORTS`
* File name: `08.09.2026.csv` (dots), confirmed with the operator
* Automatic login is off — the operator logs in by hand

## Next steps

1. Run the full workflow end to end and fix whatever it finds.
2. Map `login` if unattended running is wanted later.
3. Decide whether the automation should close the preview and report screen
   when it finishes, so the app is left clean.
4. Package as `NS-Retail-Report-Automation.exe` with PyInstaller (Phase 7).
5. Set up the office PC: VC++ redistributable, Python 3.12, then
   `scripts\setup_windows.bat` and set the base path.
