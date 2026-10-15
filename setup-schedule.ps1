# Sets up the automatic daily search on this laptop (Windows Task Scheduler).
#   powershell -ExecutionPolicy Bypass -File setup-schedule.ps1                 # every day at 6:30 am
#   powershell -ExecutionPolicy Bypass -File setup-schedule.ps1 -Time 07:15     # another time
#   powershell -ExecutionPolicy Bypass -File setup-schedule.ps1 -Remove         # turn it all off
# The task wakes the laptop if it's asleep (needs "Allow wake timers" in Power Options, plugged in),
# runs when you're signed in (a locked screen is fine), and catches up if the laptop was off at that time.
param(
  [string]$Time = "06:30",
  [switch]$Remove
)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$daily = "CPO SUV Finder - daily search"

if ($Remove) {
  Unregister-ScheduledTask -TaskName $daily -Confirm:$false -ErrorAction SilentlyContinue
  Write-Host "Removed the scheduled search."
  exit 0
}

if (-not (Test-Path (Join-Path $here ".venv\Scripts\python.exe"))) {
  throw "Set up the project first (.venv is missing). See CLAUDE.md, 'First time on this laptop'."
}

$user = "$env:USERDOMAIN\$env:USERNAME"
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive
$settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -RunOnlyIfNetworkAvailable `
  -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
  -MultipleInstances IgnoreNew
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$here\scheduled-refresh.bat`"" -WorkingDirectory $here
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
Register-ScheduledTask -TaskName $daily -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
  -Description "Runs the CPO SUV search and publishes it to the phone page. Logs: $here\logs" -Force | Out-Null
Write-Host "Daily search scheduled at $Time (task '$daily'). Logs go to $here\logs."

