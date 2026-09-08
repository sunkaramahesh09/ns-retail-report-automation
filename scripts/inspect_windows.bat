@echo off
REM ---------------------------------------------------------------
REM  Read-only inspection of NS Retail's windows and controls.
REM  It never clicks or types - it only reads.
REM
REM    scripts\inspect_windows.bat              -> list all windows
REM    scripts\inspect_windows.bat screen1      -> inspect the window you
REM                                                click during the countdown,
REM                                                saved to docs\captures\screen1.txt
REM ---------------------------------------------------------------
setlocal
cd /d "%~dp0.."
call .venv\Scripts\activate.bat

if "%~1"=="" (
    echo Listing every top-level window...
    echo.
    python -m ns_retail_automation.inspect --windows
    echo.
    echo Run it again with a name to capture one screen, e.g.
    echo     scripts\inspect_windows.bat purchases_screen
    pause
    exit /b 0
)

if not exist docs\captures mkdir docs\captures

echo Put NS Retail on the screen you want to capture.
echo You have 8 seconds to click that window...
echo.
python -m ns_retail_automation.inspect --delay 8 --depth 12 --json "docs\captures\%~1.json" > "docs\captures\%~1.txt" 2>&1
type "docs\captures\%~1.txt"
echo.
echo ==================================================================
echo Saved to docs\captures\%~1.txt  and  docs\captures\%~1.json
echo ==================================================================
pause
