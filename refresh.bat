@echo off
REM Runs the whole search, then opens the dashboard. Double-click to run.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Please double-click setup.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python run.py refresh %*
if exist output\dashboard.html start "" "output\dashboard.html"
pause
