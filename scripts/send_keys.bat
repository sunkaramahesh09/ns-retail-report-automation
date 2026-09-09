@echo off
REM ---------------------------------------------------------------
REM  Run a step, then send keystrokes to whatever it opened.
REM  For menus UI Automation cannot see - the keys go to the popup
REM  without stealing its focus.
REM
REM    scripts\send_keys.bat export_to "{HOME}{DOWN 7}{ENTER}"
REM    scripts\send_keys.bat export_to "{UP 15}{DOWN 7}{ENTER}"
REM    scripts\send_keys.bat export_to "C{ENTER}"
REM    scripts\send_keys.bat export_to "{DOWN 8}{ENTER}" 0.3
REM
REM  Key names: {DOWN} {UP} {HOME} {END} {ENTER} {ESC} {TAB}
REM  Repeat with a number: {DOWN 7}
REM ---------------------------------------------------------------
setlocal
cd /d "%~dp0.."
set PY=.venv\Scripts\python.exe

if not exist "%PY%" (
    echo [ERROR] Run scripts\setup_windows.bat first.
    pause
    exit /b 1
)
if "%~2"=="" (
    echo Usage: scripts\send_keys.bat ^<step^> "^<keys^>" [seconds between presses]
    echo Example: scripts\send_keys.bat export_to "{HOME}{DOWN 7}{ENTER}"
    pause
    exit /b 1
)

set "PAUSE_SECS=0.15"
if not "%~3"=="" set "PAUSE_SECS=%~3"

"%PY%" -m ns_retail_automation --try-step "%~1" --send-keys "%~2" --key-pause %PAUSE_SECS%
echo.
pause
