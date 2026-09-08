@echo off
REM ---------------------------------------------------------------
REM  NS Retail Report Automation - one-time Windows setup
REM  Run this from the project folder:  scripts\setup_windows.bat
REM ---------------------------------------------------------------
setlocal
cd /d "%~dp0.."

echo.
echo === 1/5  Checking Python ==========================================
python --version
if errorlevel 1 (
    echo.
    echo [ERROR] Python was not found.
    echo         Install Python 3.11 or 3.12 from https://www.python.org/downloads/windows/
    echo         and tick "Add python.exe to PATH" during setup.
    pause
    exit /b 1
)

echo.
echo === 2/5  Creating the virtual environment =========================
if not exist .venv (
    python -m venv .venv
) else (
    echo Already exists - reusing .venv
)

echo.
echo === 3/5  Installing packages ======================================
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
if errorlevel 1 (
    echo.
    echo [ERROR] Package installation failed. Send the message above back.
    pause
    exit /b 1
)
pip install -e .

echo.
echo === 4/5  Creating the configuration files =========================
if not exist config\config.json (
    copy config\config.example.json config\config.json
) else (
    echo config\config.json already exists - leaving it alone
)
if not exist config\selectors.json (
    copy config\selectors.example.json config\selectors.json
) else (
    echo config\selectors.json already exists - leaving it alone
)

echo.
echo === 5/5  Checking what is ready ===================================
ns-retail-automation --check

echo.
echo ==================================================================
echo Setup finished. Copy EVERYTHING printed above and send it back.
echo ==================================================================
pause
