@echo off
REM Opens your settings file in Notepad. It lives in your user profile, so it
REM survives downloading a new ZIP of the project.
setlocal
set "USERCFG=%USERPROFILE%\.ns_retail_automation\config.json"
if not exist "%USERCFG%" (
    echo [ERROR] No settings file yet. Run scripts\setup_windows.bat first.
    pause
    exit /b 1
)
echo Opening %USERCFG%
notepad "%USERCFG%"
