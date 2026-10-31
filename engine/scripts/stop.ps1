# توقف فقط فرایندهای پایتون همین موتور (خط فرمانشان شامل ntpro است). برنامه‌ی دیگر روی سرور دست نمی‌خورد.
$procs = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -like "python*.exe") -and ($_.CommandLine -match "-m ntpro\.(main|supervisor)")
}
foreach ($p in $procs) {
    Write-Host "Stopping PID $($p.ProcessId): $($p.CommandLine)"
    Stop-Process -Id $p.ProcessId -Force
}
if (-not $procs) { Write-Host "هیچ فرایندی از NeuroTrader Pro در حال اجرا نیست." }
