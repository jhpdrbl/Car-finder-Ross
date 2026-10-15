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

echo === %date% %time% get the latest version === >> "%LOG%"
git pull --no-edit >> "%LOG%" 2>&1
".venv\Scripts\python" -m pip install -q -r requirements.txt >> "%LOG%" 2>&1

echo === %date% %time% search === >> "%LOG%"
".venv\Scripts\python" run.py refresh >> "%LOG%" 2>&1
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
