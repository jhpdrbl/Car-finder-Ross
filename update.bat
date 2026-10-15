@echo off
REM Downloads the latest version of the tool from GitHub.
cd /d "%~dp0"
git pull
if exist .venv\Scripts\python.exe .venv\Scripts\python -m pip install -r requirements.txt --quiet
echo Updated.
pause
