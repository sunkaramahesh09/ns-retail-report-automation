@echo off
REM ---------------------------------------------------------------
REM  NS Retail Report Automation - Windows setup
REM  Safe to run again after every ZIP update: it reuses .venv and
REM  never touches your settings.
REM
REM  Run from the project folder:   scripts\setup_windows.bat
REM ---------------------------------------------------------------
setlocal
cd /d "%~dp0.."
set "USERCFGDIR=%USERPROFILE%\.ns_retail_automation"
set "USERCFG=%USERCFGDIR%\config.json"

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
echo === 2/5  Virtual environment =====================================
if not exist .venv (
    echo Creating .venv ...
    python -m venv .venv
) else (
    echo Reusing the existing .venv
)

echo.
echo === 3/5  Installing packages ======================================
.venv\Scripts\python.exe -m pip install --upgrade pip --quiet
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt --quiet
if errorlevel 1 (
    echo.
    echo [ERROR] Package installation failed. Send the message above back.
    pause
    exit /b 1
)
.venv\Scripts\python.exe -m pip install -e . --quiet
echo Packages installed.

echo.
echo === 4/5  Your settings ============================================
REM Settings live in your user profile, NOT in the project folder, so that
REM downloading a new ZIP never wipes them.
if not exist "%USERCFGDIR%" mkdir "%USERCFGDIR%"

if not exist "%USERCFG%" (
    copy config\config.example.json "%USERCFG%" >nul
    echo Created your settings file:
    echo     %USERCFG%
    echo Edit it and set "base_path" to your real reports folder.
) else (
    echo Using your existing settings file:
    echo     %USERCFG%
)

REM An older setup put the settings inside the project folder, where they
REM would be lost on the next ZIP update. Move it out of the way so the
REM profile copy is the one that counts - nothing is deleted.
if exist config\config.json (
    echo.
    echo NOTE: config\config.json in the project folder would override the one
    echo       above and would be lost on the next update, so it has been
    echo       renamed to config\config.json.old
    move /y config\config.json config\config.json.old >nul
)

echo.
echo === 5/5  Checking what is ready ===================================
.venv\Scripts\python.exe -m ns_retail_automation --check

echo.
echo ==================================================================
echo  Setup finished.
echo.
echo  Your settings : %USERCFG%
echo  Open it with  : notepad "%USERCFG%"
echo.
echo  Copy EVERYTHING printed above and send it back.
echo ==================================================================
pause
