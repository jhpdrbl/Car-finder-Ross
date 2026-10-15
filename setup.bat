@echo off
REM One-time setup for the CPO SUV Finder on Windows. Double-click to run.
cd /d "%~dp0"
echo.
echo === CPO SUV Finder: setup ===
echo.
where py >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.13 first ^(see SETUP-WINDOWS.md, step 1^), then run this again.
  pause
  exit /b 1
)
echo Creating a private Python environment in .venv ...
py -3 -m venv .venv || (echo Could not create .venv & pause & exit /b 1)
echo Installing the Python libraries ...
.venv\Scripts\python -m pip install --upgrade pip --quiet
.venv\Scripts\python -m pip install -r requirements.txt --quiet || (echo Library install failed & pause & exit /b 1)
echo.
echo Some dealer websites only work in a real browser. The browser add-on
echo is about 150 MB. Recommended, especially for Audi dealers.
choice /M "Install the browser add-on now"
if errorlevel 2 goto skipbrowser
.venv\Scripts\python -m pip install "playwright>=1.48" --quiet
.venv\Scripts\python -m playwright install chromium
:skipbrowser
echo.
echo Setup finished. Double-click refresh.bat to run the search.
pause
