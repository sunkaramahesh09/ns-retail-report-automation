@echo off
REM ---------------------------------------------------------------
REM  Run a step, then immediately look for a control it revealed.
REM  For menus that close as soon as anything else is clicked.
REM
REM    scripts\try_step_probe.bat export_to CSV
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
    echo Usage: scripts\try_step_probe.bat ^<step^> ^<text to look for^>
    echo Example: scripts\try_step_probe.bat export_to CSV
    pause
    exit /b 1
)

"%PY%" -m ns_retail_automation --try-step "%~1" --probe "%~2"
echo.
pause
