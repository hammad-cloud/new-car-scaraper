# Registers the nightly Windows task (10:00 PM, wakes the PC, catches up if missed).
# Run:  powershell -ExecutionPolicy Bypass -File install_task.ps1
# Remove: Unregister-ScheduledTask -TaskName "MiraES Auction Agent" -Confirm:$false
param([string]$At = "22:00")

$name   = "MiraES Auction Agent"
$script = Join-Path $PSScriptRoot "run_nightly.ps1"

$action   = New-ScheduledTaskAction -Execute "powershell.exe" `
              -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`"" `
              -WorkingDirectory $PSScriptRoot
$trigger  = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable `
              -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
              -RunOnlyIfNetworkAvailable -MultipleInstances IgnoreNew `
              -ExecutionTimeLimit (New-TimeSpan -Hours 4)

Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
    -Settings $settings -Description "Nightly Mira e:S auction check -> Telegram at 11 PM" -Force |
    Select-Object TaskName, State

Write-Host "Scheduled daily at $At. Test now with:  Start-ScheduledTask -TaskName `"$name`""
