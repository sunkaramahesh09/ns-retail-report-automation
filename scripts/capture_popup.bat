@echo off
REM ---------------------------------------------------------------
REM  Find a control ANYWHERE on screen, including popup menus and
REM  Windows' own dialogs, which are separate windows from NS Retail.
REM  Read-only.
REM
REM    scripts\capture_popup.bat CSV 10
REM        -> waits 10 seconds while you open the Export To menu,
REM           then searches every window for "CSV"
REM
REM    scripts\capture_popup.bat "File name" 10
REM        -> same, for the Save As dialog
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
    echo Usage: scripts\capture_popup.bat ^<text^> [seconds to wait first]
    echo Example: scripts\capture_popup.bat CSV 10
    pause
    exit /b 1
)

set "WAIT=10"
if not "%~2"=="" set "WAIT=%~2"

"%PY%" -m ns_retail_automation.inspect --all-windows --find "%~1" --delay %WAIT% --depth 10
echo.
pause
