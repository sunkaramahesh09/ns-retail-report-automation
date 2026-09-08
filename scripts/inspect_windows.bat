@echo off
REM ---------------------------------------------------------------
REM  Read-only inspection of NS Retail's windows and controls.
REM  It never clicks or types - it only reads.
REM
REM    scripts\inspect_windows.bat
REM        -> list every top-level window
REM
REM    scripts\inspect_windows.bat purchases "Victory Bazars.*"
REM        -> capture that window straight away (no clicking needed)
REM
REM    scripts\inspect_windows.bat purchases
REM        -> capture whichever window you click during the countdown
REM
REM  Output goes to docs\captures\<name>.txt and docs\captures\<name>.json
REM ---------------------------------------------------------------
setlocal
cd /d "%~dp0.."
set PY=.venv\Scripts\python.exe

if not exist "%PY%" (
    echo [ERROR] .venv was not found. Run scripts\setup_windows.bat first.
    pause
    exit /b 1
)

if "%~1"=="" (
    echo Listing every top-level window...
    echo.
    "%PY%" -m ns_retail_automation.inspect --windows
    echo.
    echo To capture one screen, run it again with a name, e.g.
    echo     scripts\inspect_windows.bat purchases "Victory Bazars.*"
    pause
    exit /b 0
)

if not exist docs\captures mkdir docs\captures

if not "%~2"=="" (
    echo Capturing the window matching "%~2" ...
    "%PY%" -m ns_retail_automation.inspect --title-re "%~2" --depth 12 --actionable --json "docs\captures\%~1.json" > "docs\captures\%~1.txt" 2>&1
) else (
    echo Put NS Retail on the screen you want to capture.
    echo You have 8 seconds to click that window...
    echo.
    "%PY%" -m ns_retail_automation.inspect --delay 8 --depth 12 --actionable --json "docs\captures\%~1.json" > "docs\captures\%~1.txt" 2>&1
)

echo.
type "docs\captures\%~1.txt"
echo.
echo ==================================================================
echo Saved:  docs\captures\%~1.txt
echo         docs\captures\%~1.json
echo Send me the .txt file.
echo ==================================================================
pause
