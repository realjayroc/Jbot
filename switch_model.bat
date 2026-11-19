@echo off
setlocal
cd /d "%~dp0"
python model_switcher.py
if errorlevel 1 pause
endlocal
