@echo off
REM Uploads your latest results to GitHub. GitHub then updates your phone page
REM (Cloudflare) in about 2 minutes. Also lets Claude read your results.
cd /d "%~dp0"
echo Uploading results ...
git pull --no-edit --quiet
git add data output
git commit --quiet -m "Results from laptop run %date% %time%"
git push --quiet
if errorlevel 1 (
  echo Upload failed. Take a screenshot of this window and send it to Claude.
) else (
  echo Uploaded. Your phone page updates in about 2 minutes.
)
if not "%~1"=="nopause" pause
