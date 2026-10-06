# What Task Scheduler runs every night. Logs go to logs\run_YYYY-MM-DD.log
Set-Location $PSScriptRoot
New-Item -ItemType Directory -Force "logs" | Out-Null
$log = "logs\run_$(Get-Date -Format yyyy-MM-dd).log"

"=== start $(Get-Date -Format s) ===" | Out-File $log -Append -Encoding utf8
$env:PYTHONIOENCODING = "utf-8"
& "venv\Scripts\python.exe" graph.py *>> $log
"=== end $(Get-Date -Format s), exit $LASTEXITCODE ===" | Out-File $log -Append -Encoding utf8

# Keep 30 days of logs
Get-ChildItem "logs\run_*.log" | Where-Object LastWriteTime -lt (Get-Date).AddDays(-30) | Remove-Item -Force
exit $LASTEXITCODE
