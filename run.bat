@echo off
title Locksmith Ad Killer
cd /d "%~dp0"
echo Starting Locksmith Ad Killer...
python app.py
if %errorlevel% neq 0 (
    echo.
    echo =========================================
    echo  ERROR: The app closed unexpectedly.
    echo  Error code: %errorlevel%
    echo =========================================
    echo.
    pause
)
