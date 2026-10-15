@echo off
REM Runs the whole search, opens the dashboard, then offers to publish it to your phone.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Please double-click setup.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python run.py refresh %*
if errorlevel 1 (
  echo.
  echo The search stopped with an error. Take a screenshot of this window and send it to Claude.
  pause
  exit /b 1
)
if exist output\dashboard.html start "" "output\dashboard.html"
echo.
choice /M "Publish these results to your phone page"
if errorlevel 2 goto end
call "%~dp0share-results.bat" nopause
:end
pause
