@echo off
REM ---------------------------------------------------------------
REM  Test ONE automation step against the running NS Retail.
REM  This DOES click inside NS Retail - have it open and logged in.
REM
REM    scripts\try_step.bat open_reports
REM    scripts\try_step.bat set_date 08-09-2026
REM    scripts\try_step.bat                     ^(lists the steps^)
REM
REM  Several steps at once, back to back - needed for the export menu,
REM  which closes as soon as you click back to this window. Join them
REM  with + : cmd.exe splits arguments on commas.
REM
REM    scripts\try_step.bat export_to+choose_csv_format+confirm_export
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
    "%PY%" -m ns_retail_automation --list-steps
    echo.
    pause
    exit /b 0
)

REM Guard against the comma trap: cmd splits "a,b,c" into three arguments,
REM so the second one would otherwise be read as a date.
echo %~1| findstr /c:"," >nul
if not errorlevel 1 (
    if not "%~2"=="" (
        echo [ERROR] Join steps with + instead of a comma - cmd.exe splits on commas.
        echo         Example: scripts\try_step.bat export_to+choose_csv_format
        pause
        exit /b 1
    )
)

if "%~2"=="" (
    "%PY%" -m ns_retail_automation --try-step "%~1"
) else (
    "%PY%" -m ns_retail_automation --try-step "%~1" --date "%~2"
)
echo.
pause
