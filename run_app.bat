@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3 is required. Install Python and enable the "Add python.exe to PATH" option.
  pause
  exit /b 1
)
python jbot_commander.py interactive
if errorlevel 1 pause
endlocal
