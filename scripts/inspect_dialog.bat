@echo off
REM ---------------------------------------------------------------
REM  Inspect a dialog that lives INSIDE the NS Retail main window.
REM  Read-only.
REM
REM    scripts\inspect_dialog.bat frmIncludeExclude
REM ---------------------------------------------------------------
setlocal
cd /d "%~dp0.."
set PY=.venv\Scripts\python.exe

if not exist "%PY%" (
    echo [ERROR] Run scripts\setup_windows.bat first.
    pause
    exit /b 1
)
if "%~1"=="" (
    echo Usage: scripts\inspect_dialog.bat ^<dialog automation id^>
    echo Example: scripts\inspect_dialog.bat frmIncludeExclude
    pause
    exit /b 1
)

if not exist docs\captures mkdir docs\captures
"%PY%" -m ns_retail_automation.inspect --title-re "Victory Bazars.*" --child "%~1" --depth 14 --json "docs\captures\%~1.json" > "docs\captures\%~1.txt" 2>&1
type "docs\captures\%~1.txt"
echo.
echo Saved: docs\captures\%~1.txt
echo.
pause
