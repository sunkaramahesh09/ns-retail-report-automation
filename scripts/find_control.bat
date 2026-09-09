@echo off
REM ---------------------------------------------------------------
REM  Find a control in the NS Retail window and show whether it is
REM  there, visible, enabled, and what it sits inside. Read-only.
REM
REM    scripts\find_control.bat dtpFromDate
REM    scripts\find_control.bat Export
REM    scripts\find_control.bat "CSV" "Victory Bazars.*" 10
REM        ^-- waits 10 seconds first, so you can open a menu that would
REM            close if you had to click back to this window
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
    echo Usage: scripts\find_control.bat ^<text^> [window title regex] [seconds to wait first]
    echo Example: scripts\find_control.bat dtpFromDate
    echo Example: scripts\find_control.bat CSV "Victory Bazars.*" 10
    pause
    exit /b 1
)

set "WINDOW=Victory Bazars.*"
if not "%~2"=="" set "WINDOW=%~2"

if "%~3"=="" (
    "%PY%" -m ns_retail_automation.inspect --title-re "%WINDOW%" --depth 14 --find "%~1"
) else (
    "%PY%" -m ns_retail_automation.inspect --title-re "%WINDOW%" --depth 14 --delay %~3 --find "%~1"
)
echo.
pause
