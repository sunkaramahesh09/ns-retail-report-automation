@echo off
REM ---------------------------------------------------------------
REM  Run the automation for every enabled report, one after another.
REM    scripts\run_report.bat              -> dry run for yesterday
REM    scripts\run_report.bat go           -> real run for yesterday
REM    scripts\run_report.bat go 08-09-2026 -> real run for one date
REM  To run a single report instead, pass --report <key> directly:
REM    .venv\Scripts\python.exe -m ns_retail_automation --report purchases --date yesterday
REM ---------------------------------------------------------------
setlocal
cd /d "%~dp0.."
set PY=.venv\Scripts\python.exe

if not exist "%PY%" (
    echo [ERROR] Run scripts\setup_windows.bat first.
    pause
    exit /b 1
)

set "WHEN=yesterday"
if not "%~2"=="" set "WHEN=%~2"

if /i "%~1"=="go" (
    echo Running the automation for %WHEN% ...
    "%PY%" -m ns_retail_automation --date "%WHEN%"
) else (
    echo Dry run for %WHEN% - NS Retail will not be touched.
    echo ^(add "go" to run for real:  scripts\run_report.bat go^)
    echo.
    "%PY%" -m ns_retail_automation --date "%WHEN%" --dry-run
)
echo.
pause
