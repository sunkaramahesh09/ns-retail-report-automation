@echo off
REM ---------------------------------------------------------------
REM  Fixes / diagnoses: DLL load failed while importing win32ui
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
echo === Python version ===============================================
"%PY%" -c "import sys; print(sys.version)"

echo.
echo === Registering pywin32's DLLs ===================================
"%PY%" .venv\Scripts\pywin32_postinstall.py -install -silent

echo.
echo === Looking for the MFC runtime that win32ui needs ===============
"%PY%" -c "import os,sys;d=os.path.join(sys.prefix,'Lib','site-packages','pythonwin');print('folder:',d);print('exists:',os.path.isdir(d));print('files :',sorted(f for f in os.listdir(d) if f.lower().endswith(('.dll','.pyd')))[:20] if os.path.isdir(d) else [])"

echo.
echo === Checking that the packages load ==============================
"%PY%" -c "import win32api, win32ui, pywinauto; print('OK - pywinauto', pywinauto.__version__, 'loads correctly')"
if errorlevel 1 (
    echo.
    echo ==================================================================
    echo  win32ui still will not load.
    echo.
    echo  This is almost always because the Python version is too new for
    echo  pywin32. The cure:
    echo.
    echo    1. Install Python 3.12:
    echo       https://www.python.org/downloads/release/python-3129/
    echo       Tick "Add python.exe to PATH" on the first screen.
    echo    2. Close this window, open a new Command Prompt here, and run:
    echo       scripts\setup_windows.bat fresh
    echo.
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
