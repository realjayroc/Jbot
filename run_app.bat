@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  python -m venv .venv
  if errorlevel 1 (echo Failed to create virtual environment.& pause & exit /b 1)
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
if exist requirements.txt pip install -r requirements.txt
python model_switcher.py
endlocal
