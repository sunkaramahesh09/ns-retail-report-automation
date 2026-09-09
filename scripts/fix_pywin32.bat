@echo off
REM ---------------------------------------------------------------
REM  Fixes: ImportError: DLL load failed while importing win32ui
REM
REM  pip installs pywin32's Python files but not its DLLs; they have to be
REM  registered by a post-install script that pip does not run. This does it
REM  and then proves that the automation packages really load.
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
echo === Registering pywin32's DLLs ===================================
"%PY%" .venv\Scripts\pywin32_postinstall.py -install -silent
if errorlevel 1 (
    echo.
    echo The post-install script failed. Trying a reinstall of pywin32...
    "%PY%" -m pip install --force-reinstall --no-cache-dir pywin32
    "%PY%" .venv\Scripts\pywin32_postinstall.py -install -silent
)

echo.
echo === Checking that the packages load ==============================
"%PY%" -c "import win32api, win32ui, pywinauto; print('OK - pywinauto', pywinauto.__version__, 'loads correctly')"
if errorlevel 1 (
    echo.
    echo [ERROR] The packages still do not load.
    echo         Send everything above back. The usual cure is to install
    echo         Python 3.12 instead of the newest version and re-run
    echo         scripts\setup_windows.bat.
    pause
    exit /b 1
)

echo.
echo === Readiness ====================================================
"%PY%" -m ns_retail_automation --check

echo.
pause
