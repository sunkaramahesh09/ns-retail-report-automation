# Where this project stands

Last updated: 2026-09-09, after the first fully successful end-to-end runs.

## The full end-to-end run works

```bat
scripts\run_report.bat go 08-09-2026
```

Run twice against the real application (NS Retail v4.0.3) with no manual
intervention, start to finish, each in under two minutes:

* `07-09-2026` (a date with no existing file) — completed, file verified on
  disk (130,976 bytes), exit code 0.
* `08-09-2026` (a date already exported) — correctly refused to touch it and
  exited with code 3 ("A report already exists... Nothing was changed"),
  without even opening NS Retail. This is the `skip` default working as
  intended, not a bug.

Every step of the workflow is now verified against the real application:
detect/reuse NS Retail, `close_report_screens`, `open_reports`,
`open_stock_reports`, `select_purchase_report`, `set_date`,
`open_column_settings`, `include_all_columns`, `apply_and_search`,
`generate_report`, `export_to`, `choose_csv_format`, `confirm_export`,
`save_set_path`, `save_confirm`, `dismiss_open_prompt`, file verification.

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
* The export format list is **invisible to UI Automation** (0 descendants
  under the popup's MenuBar), but it is a **fixed 10-entry list**, always in
  this order: PDF, HTML, MHT, RTF, DOCX, XLS, XLSX, CSV, Text, Image — CSV is
  always the 8th (index 7). Confirmed from a screenshot of the open menu, not
  guessed. An earlier "most-recently-used ordering" theory was wrong; it was
  concluded from a trial-and-error loop whose own repeated selections kept
  promoting whatever it tried, which is what actually looked like reordering.
  `export_to` now opens the dropdown and sends `{HOME}{HOME}{DOWN 7}{ENTER}`
  directly (the doubled Home absorbs the popup's render time — without it,
  the first few keystrokes land before the menu can accept them and the
  selection undershoots). `choose_csv_format` still verifies the resulting
  dialog really says CSV, so a future menu change fails loudly instead of
  silently exporting the wrong format.
* **A leftover Preview window from an interrupted run blocks whatever the
  next run does first** — it sits on top of the MDI area and disables
  everything under it, so depending on timing the next run has failed at
  `set_date`, `select_purchase_report`, or `export_to`, which looked like
  three unrelated bugs before the common cause was found. Fixed by closing
  any existing Preview at the very start of `close_report_screens()`, not
  only right before generating a new report.
* The Windows **Save As dialog is a child of the Preview window**, not a
  top-level window — `export_csv()` was searching for it with a top-level-only
  desktop search and would never find it, no matter the timeout. Fixed to use
  `wait_for_child_window` when the selector says `"inside"`.
* Setting the Save As dialog's File name box via UI Automation's `ValuePattern`
  (`set_edit_text`) **passes its own readback check but does not update the
  dialog's actual committed filename** — confirmed live: the box visibly
  showed the full target path, yet clicking Save opened a "Document.csv
  already exists?" prompt for the file's old default name. `save_set_path`
  now sends real keystrokes (`^a{destination_path}`, select-all then type)
  instead, which the dialog does honor.
* NS Retail asks **"Do you want to open this file?"** after every export.
  `dismiss_open_prompt` clicks No, so the Preview stays usable for the next
  run instead of sitting disabled behind an unanswered prompt.
* `select_purchase_report`'s wait target was an auto_id (`ucPurchases`) that
  does not exist on the live screen — the screen loaded fine, the wait just
  never matched. Corrected to `layoutControl1`, the screen's real root pane.
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

1. Map `login` if unattended running is wanted later.
2. Package as `NS-Retail-Report-Automation.exe` with PyInstaller (Phase 7).
3. Set up the office PC: VC++ redistributable, Python 3.12, then
   `scripts\setup_windows.bat` and set the base path.
