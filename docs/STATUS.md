# Where this project stands

Last updated: 2026-09-09, after extending the working Purchases pipeline to
three more report types and adding a chained run across all of them.

## Four reports mapped; two confirmed live, two still to prove out

```bat
scripts\run_report.bat go 08-09-2026
```

`run_report.bat` (and a plain `ns-retail-automation --date <date>` with no
`--report`) now runs **every enabled report for that date, one after
another**, on a single NS Retail session — see "Chained multi-report runs"
below. Pass `--report <key>` to run just one:

```
ns-retail-automation --report purchases --date 08-09-2026
ns-retail-automation --report dispatches --date 08-09-2026
ns-retail-automation --report sales --date 08-09-2026
ns-retail-automation --report stock_as_on_date --date 08-09-2026
```

Real-run status per report, from `logs/automation_2026-09-09.log`:

* **Purchases** — run twice against the real application with no manual
  intervention, start to finish, each in under two minutes: `07-09-2026` (no
  existing file) completed, file verified on disk (130,976 bytes), exit code
  0; `08-09-2026` (already exported) correctly refused to touch it and exited
  with code 3, without even opening NS Retail. Every step of its workflow is
  verified live: detect/reuse NS Retail, `close_report_screens`,
  `open_reports`, `open_stock_reports`, `select_purchase_report`, `set_date`,
  `open_column_settings`, `include_all_columns`, `apply_and_search`,
  `generate_report`, `export_to`, `choose_csv_format`, `confirm_export`,
  `save_set_path`, `save_confirm`, `dismiss_open_prompt`, file verification.
* **Dispatches** — run for real 16:26–16:31, succeeded end to end: file
  verified at `...\Dispatches\...\08.09.2026\08.09.2026.csv` (4,614,203
  bytes).
* **Sales** — attempted for real three times (16:32, 17:38, and again after
  the 90s `export_to` timeout was added) and **failed every time**:
  `export_to` can't find the "Export To" `SplitButton` within its wait
  window. Root cause confirmed live with a read-only inspection
  (`scripts\find_control.bat Export "Victory Bazars - \[Report Viewer\]"`)
  while the failed run's Preview was still open: the control was a
  **disabled `Button`**, not a `SplitButton` — NS Retail had not finished
  internally processing the report yet even though the Preview window itself
  had already appeared. Left alone for a few more minutes it turned into an
  enabled `SplitButton` on its own. This is a report-size problem, not a
  selector bug: the operator reports Sales with every column ticked runs to
  **~8,300 pages** of data, which is far more than 2×90s of retrying can wait
  out. Operator is checking with their manager whether Sales actually needs
  every column (`include_all_columns` ticks all of them today) — a smaller
  column set would shrink the report and likely make this a non-issue.
  **Do not change `include_all_columns`/timeout behavior for Sales until
  that's confirmed** - noted here so it isn't lost between sessions.
* **Stock As on date** — mapped (`select_stock_as_on_date_report` = Node4 in
  the catalog tree, the single `dtAsOnDate` field via the new `set_as_on_date`
  step) and dry-run verified, but **never attempted live**.

`select_dispatches_report` / `select_sales_report` were confirmed live against
the real `tlReport` catalog tree (Dispatches is Node9, Sales is Node10) — same
`dtpFromDate`/`dtpToDate` screen shape as Purchases, plus extra unused filters
(Branch, Periodicity, Category, Item Code). Per-report
`storage_overrides.base_path` (with `{fy_label}` templating) files each report
into its own folder tree; see `config/config.example.json`.

`--list-reports` shows all four as enabled; `--check` reports every window and
step mapped; dry runs for all four resolve correct destination paths and
filenames. **Before trusting Sales or Stock As on date unattended, run each
for real** with `--report sales --date <date>` / `--report stock_as_on_date
--date <date>` and confirm a file actually lands on disk.

## Chained multi-report runs (new, untested live)

`main.py` no longer treats "no `--report`" as shorthand for the single
configured default — `_prepare_all` now builds one `ReportJob` per report with
`enabled: true` in `config.json` (in the order they appear there: purchases,
dispatches, sales, stock_as_on_date), sharing one `NSRetailAutomation`
instance so NS Retail is only launched/connected to once. `_run_all` then
runs them in sequence: each report gets its own "report saved" popup, and
because that popup is a blocking Tk dialog in the same process, the operator
clicking its OK button is literally what lets the loop move on to the next
report. A failure raises immediately and stops the sequence there (the
operator fixes it and reruns the reports that did not finish) rather than
pressing on to reports likely to hit the same problem. `--report <key>` still
runs exactly that one report, unchanged.

**Confirmed live 2026-09-09**: ran `ns-retail-automation --date 08-09-2026`
(no `--report`) against the real application. Purchases and Dispatches
correctly skipped (already exported) and each handed off to the next report
right after the operator dismissed its "nothing to do" popup - proving the
core mechanism (one shared session, popup click advances the loop). It then
reached Sales and hit the pre-existing export_to failure described above,
which stopped the sequence there per the "stop on failure" design - Stock As
on date was never reached in this run. The chaining logic itself worked
exactly as intended; only Sales' own export step needs the fix above (or
smaller Sales reports) before a full four-report run will finish clean.

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

1. **Waiting on the operator**: confirm with their manager whether Sales
   actually needs every column ticked, given it runs to ~8,300 pages today.
   If not, narrowing `include_all_columns` for Sales (or giving it its own
   column list) would shrink the report and likely fix the export_to timeout
   as a side effect. Do not change this without that confirmation.
2. Once Sales' column scope is settled, re-run Sales for real and confirm a
   file lands on disk; then run Stock As on date for real too (never
   attempted live).
3. Run the full chained default (`scripts\run_report.bat go <date>`) end to
   end once all four reports work individually, to confirm it completes
   without stopping partway through.
4. Map `login` if unattended running is wanted later.
5. Package as `NS-Retail-Report-Automation.exe` with PyInstaller (Phase 7).
6. Set up the office PC: VC++ redistributable, Python 3.12, then
   `scripts\setup_windows.bat` and set the base path.
