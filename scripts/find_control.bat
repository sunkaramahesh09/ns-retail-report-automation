@echo off
REM ---------------------------------------------------------------
REM  Find a control in the NS Retail window and show whether it is
REM  there, visible, enabled, and what it sits inside. Read-only.
REM
REM    scripts\find_control.bat dtpFromDate
REM    scripts\find_control.bat Search
REM    scripts\find_control.bat Date "Include Exclude Settings.*"
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
    echo Usage: scripts\find_control.bat ^<text to look for^> [window title regex]
    echo Example: scripts\find_control.bat dtpFromDate
    pause
    exit /b 1
)

set "WINDOW=Victory Bazars.*"
if not "%~2"=="" set "WINDOW=%~2"

"%PY%" -m ns_retail_automation.inspect --title-re "%WINDOW%" --depth 14 --find "%~1"
echo.
pause
