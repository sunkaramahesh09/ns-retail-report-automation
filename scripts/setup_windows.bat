@echo off
REM ---------------------------------------------------------------
REM  NS Retail Report Automation - Windows setup
REM
REM    scripts\setup_windows.bat            normal setup (reuses .venv)
REM    scripts\setup_windows.bat fresh      delete .venv and rebuild it
REM    scripts\setup_windows.bat "C:\Path\To\python.exe"   use that Python
REM
REM  Safe to run again after every ZIP update. Your settings live in your
REM  user profile and are never touched.
REM ---------------------------------------------------------------
setlocal enabledelayedexpansion
cd /d "%~dp0.."
set "USERCFGDIR=%USERPROFILE%\.ns_retail_automation"
set "USERCFG=%USERCFGDIR%\config.json"

echo.
echo === 0/6  Which copy of the project is this? =======================
for /f "usebackq tokens=*" %%v in (`findstr /c:"__version__ = " src\ns_retail_automation\__init__.py`) do echo Project source: %%v
echo Folder        : %CD%
echo (If the version is not what you were told to download, extract the new
echo  ZIP over this folder and choose "Replace the files in the destination".)

echo.
echo === 1/6  Choosing a Python version ================================
REM pywinauto needs pywin32, whose newest-Python builds are often broken.
REM Python 3.12 is the version it is actually tested against, so prefer it.
set "PYCMD="

if not "%~1"=="" (
    if /i not "%~1"=="fresh" set "PYCMD=%~1"
)

if not defined PYCMD (
    py -3.12 --version >nul 2>&1
    if not errorlevel 1 set "PYCMD=py -3.12"
)
if not defined PYCMD (
    py -3.11 --version >nul 2>&1
    if not errorlevel 1 set "PYCMD=py -3.11"
)
if not defined PYCMD set "PYCMD=python"

echo Using: !PYCMD!
!PYCMD! --version
if errorlevel 1 (
    echo.
    echo [ERROR] Python was not found.
    echo         Install Python 3.12 from
    echo         https://www.python.org/downloads/release/python-3129/
    echo         and tick "Add python.exe to PATH" during setup.
    pause
    exit /b 1
)

echo.
echo === 2/6  Virtual environment =====================================
REM Is the chosen Python one that pywin32 works on?
set "PYOK=0"
%PYCMD% -c "import sys; sys.exit(0 if sys.version_info < (3, 13) else 1)" >nul 2>&1
if not errorlevel 1 set "PYOK=1"

REM Is the existing .venv on such a Python?
set "VENVOK=0"
.venv\Scripts\python.exe -c "import sys; sys.exit(0 if sys.version_info < (3, 13) else 1)" >nul 2>&1
if not errorlevel 1 set "VENVOK=1"
if not exist .venv set "VENVOK=0"

if /i "%~1"=="fresh" if exist .venv echo Deleting the old .venv (you asked for a fresh one) ...
if /i "%~1"=="fresh" if exist .venv rmdir /s /q .venv

REM A .venv built on a too-new Python can never work, so replace it rather
REM than reusing it and failing later with "DLL load failed".
if exist .venv if "%VENVOK%"=="0" if "%PYOK%"=="1" echo The existing .venv runs a Python that pywin32 cannot work on.
if exist .venv if "%VENVOK%"=="0" if "%PYOK%"=="1" echo Rebuilding it with !PYCMD! ...
if exist .venv if "%VENVOK%"=="0" if "%PYOK%"=="1" rmdir /s /q .venv

if not exist .venv (
    echo Creating .venv ...
    !PYCMD! -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Could not create the virtual environment.
        pause
        exit /b 1
    )
) else (
    echo Reusing the existing .venv
)

.venv\Scripts\python.exe -c "import sys; print('Virtual environment runs Python', sys.version.split()[0]); sys.exit(1 if sys.version_info >= (3, 13) else 0)"
if errorlevel 1 (
    echo.
    echo [WARNING] This Python is too new for pywin32, and "import win32ui"
    echo           will fail with "DLL load failed".
    echo.
    echo           Install Python 3.12 from
    echo           https://www.python.org/downloads/release/python-3129/
    echo           or run:  py install 3.12
    echo           then run this script again - it will rebuild automatically.
    echo.
)

echo.
echo === 3/6  Installing packages ======================================
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
echo === 4/6  Registering pywin32's DLLs ==============================
REM pip installs pywin32's Python files but not its DLLs.
if exist .venv\Scripts\pywin32_postinstall.py (
    .venv\Scripts\python.exe .venv\Scripts\pywin32_postinstall.py -install -silent >nul 2>&1
    echo Done.
) else (
    echo Nothing to do.
)

echo.
echo === 5/6  Your settings ============================================
if not exist "%USERCFGDIR%" mkdir "%USERCFGDIR%"
if not exist "%USERCFG%" (
    copy config\config.example.json "%USERCFG%" >nul
    echo Created: %USERCFG%
    echo Set your reports folder with:  scripts\set_report_folder.bat
) else (
    echo Using: %USERCFG%
)
if exist config\config.json (
    echo NOTE: config\config.json would override the settings above and would
    echo       be lost on the next update - renamed to config\config.json.old
    move /y config\config.json config\config.json.old >nul
)

echo.
echo === 6/6  Checking what is ready ===================================
.venv\Scripts\python.exe -m ns_retail_automation --check

echo.
echo ==================================================================
echo  Setup finished. Copy EVERYTHING printed above and send it back.
echo ==================================================================
pause
