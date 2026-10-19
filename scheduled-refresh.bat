@echo off
REM Runs the whole search and publishes it with no questions asked. Windows Task Scheduler
REM runs this every morning (set up by setup-schedule.ps1). You can also double-click it.
REM A log of each run is written to logs\refresh_<date>.log.
cd /d "%~dp0"
if not exist logs mkdir logs
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HHmm"') do set STAMP=%%i
set LOG=logs\refresh_%STAMP%.log

REM Another search already running (a scheduled one, or one Claude started)? Then skip this one.
REM A marker older than 3 hours is left over from a crash or power cut, so it's ignored.
powershell -NoProfile -Command "if ((Test-Path 'logs\running.lock') -and ((Get-Date) - (Get-Item 'logs\running.lock').LastWriteTime).TotalHours -lt 3) { exit 1 } else { exit 0 }"
if errorlevel 1 (
  echo %date% %time% another search is running; skipped >> "%LOG%"
  exit /b 0
)
echo %date% %time% > logs\running.lock
set PY=python
if exist .venv\Scripts\python.exe set PY=.venv\Scripts\python

REM No git copy (set up as in LAPTOP.md): search.py gets the latest version, searches and uploads.
REM Kept on one line so cmd doesn't read the rest of this file while search.py may update it.
if exist .git goto gitflow
echo === %date% %time% get the latest version, search, upload (search.py) === >> "%LOG%"
"%PY%" search.py >> "%LOG%" 2>&1 & goto ipaddone

:gitflow

echo === %date% %time% get the latest version === >> "%LOG%"
git pull --no-edit >> "%LOG%" 2>&1
"%PY%" -m pip install -q -r requirements.txt >> "%LOG%" 2>&1

echo === %date% %time% search === >> "%LOG%"
"%PY%" run.py refresh >> "%LOG%" 2>&1
set RESULT=%errorlevel%

if "%RESULT%"=="0" (
  echo === %date% %time% publish === >> "%LOG%"
  REM If the cloud changed results while this ran, this run's results win (-X ours).
  git pull --no-edit -X ours >> "%LOG%" 2>&1
  git add data output >> "%LOG%" 2>&1
  git commit -m "Scheduled results from laptop %STAMP%" >> "%LOG%" 2>&1
  git push >> "%LOG%" 2>&1
  if errorlevel 1 (echo PUBLISH FAILED >> "%LOG%") else (echo published >> "%LOG%")
) else (
  echo SEARCH FAILED with code %RESULT%; nothing published >> "%LOG%"
)
del logs\running.lock
exit /b %RESULT%

:ipaddone
set RESULT=%errorlevel%
if "%RESULT%"=="0" (echo done >> "%LOG%") else (echo SEARCH OR UPLOAD FAILED with code %RESULT% >> "%LOG%")
del logs\running.lock
exit /b %RESULT%
