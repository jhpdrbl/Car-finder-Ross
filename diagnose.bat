@echo off
REM Checks how dealer websites look from your home connection and writes a report
REM to output\diagnose_<date>.md to send to Claude. Default: Audi dealers.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Please double-click setup.bat first.
  pause
  exit /b 1
)
if "%~1"=="" (
  .venv\Scripts\python run.py diagnose --brand Audi
) else (
  .venv\Scripts\python run.py diagnose %*
)
pause
