@echo off
REM ---------------------------------------------------------------
REM  Sets the folder your reports are filed into, without editing JSON.
REM  Backslashes are handled for you.
REM ---------------------------------------------------------------
setlocal
cd /d "%~dp0.."
set PY=.venv\Scripts\python.exe

if not exist "%PY%" (
    echo [ERROR] Run scripts\setup_windows.bat first.
    pause
    exit /b 1
)

echo Current settings:
echo.
"%PY%" -m ns_retail_automation.configure --show
echo.
echo Type the folder that holds your day-wise report folders.
echo Example:  D:\2026-27 DAY WISE REPORTS
echo (press Enter on its own to leave it unchanged)
echo.
set "NEWPATH="
set /p "NEWPATH=Reports folder: "

if "%NEWPATH%"=="" (
    echo Nothing changed.
) else (
    "%PY%" -m ns_retail_automation.configure --base-path "%NEWPATH%"
)

echo.
echo === Dry run =====================================================
"%PY%" -m ns_retail_automation --dry-run
echo.
pause
