@echo off
chcp 65001 >nul
rem Restart ONLY the NeuroTrader Pro engine process (-m ntpro.main). The supervisor starts it again in a few seconds.
rem No other program on this server is touched.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Get-CimInstance Win32_Process | Where-Object { ($_.Name -like 'python*.exe') -and ($_.CommandLine -match '-m ntpro\.main') }; if ($p) { $p | ForEach-Object { Write-Host ('Stopping engine PID ' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force }; Write-Host 'Engine will restart automatically in a few seconds.' } else { Write-Host 'Engine process not found.' }"
pause
