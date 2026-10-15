@echo off
REM Uploads your latest results (data and output folders) to GitHub so Claude can see them.
cd /d "%~dp0"
git add data output
git commit -m "Results from home run %date%"
git push
echo Shared.
pause
