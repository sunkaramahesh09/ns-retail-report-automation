@echo off
REM ---------------------------------------------------------------
REM  Diagnoses and fixes: DLL load failed while importing win32ui
REM ---------------------------------------------------------------
setlocal
cd /d "%~dp0.."
set PY=.venv\Scripts\python.exe

if not exist "%PY%" (
    echo [ERROR] Run scripts\setup_windows.bat first.
    pause
    exit /b 1
)

echo.
echo === Python =======================================================
"%PY%" -c "import sys; print(sys.version); print(sys.prefix)"

echo.
echo === Registering pywin32's DLLs ===================================
"%PY%" .venv\Scripts\pywin32_postinstall.py -install -silent

echo.
echo === Which DLL is actually missing? ===============================
"%PY%" -m ns_retail_automation.diagnose_win32

echo.
echo === Checking that the packages load ==============================
"%PY%" -c "import win32api, win32ui, pywinauto; print('OK - pywinauto', pywinauto.__version__, 'loads correctly')"
if errorlevel 1 (
    echo.
    echo ==================================================================
    echo  win32ui still will not load. Read the "missing" lines above.
    echo.
    echo  If mfc140u.dll is missing, install the Microsoft Visual C++
    echo  Redistributable (a 25 MB Microsoft download):
    echo.
    echo      https://aka.ms/vs/17/release/vc_redist.x64.exe
    echo.
    echo  Run it, restart this Command Prompt, and run this script again.
    echo  Send the output above back if it still fails.
    echo ==================================================================
    pause
    exit /b 1
)

echo.
echo === Readiness ====================================================
"%PY%" -m ns_retail_automation --check
echo.
pause
