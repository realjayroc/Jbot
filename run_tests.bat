@echo off
setlocal
cd /d "%~dp0"
python -m unittest discover -s tests -p "test_*.py" -v
if errorlevel 1 (
  echo FAIL: test suite reported failures.
  pause
  exit /b 1
)
echo PASS: all tests completed successfully.
pause
endlocal
