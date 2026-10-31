# ثبت اجرای خودکار NeuroTrader Pro (تسک ویندوز با نام جدا «NeuroTraderPro»).
# ناظر (supervisor) موتور را اجرا می‌کند و در صورت کرش یا قطع Heartbeat، دوباره راه‌اندازی می‌کند.
# تسک برنامه‌ی دیگر (مثلاً «NeuroTrader») دست نمی‌خورد.
# اجرا: PowerShell به‌عنوان Administrator
$ErrorActionPreference = "Stop"
$EngineDir = Split-Path -Parent $PSScriptRoot
$TaskName = "NeuroTraderPro"
$Pyw = "$EngineDir\.venv\Scripts\pythonw.exe"
if (-not (Test-Path $Pyw)) { Write-Host "ابتدا install.ps1 را اجرا کنید" -ForegroundColor Red; exit 1 }
if ($TaskName -eq "NeuroTrader") { throw "نام تسک نباید با برنامه‌ی قبلی یکی باشد" }

$action = New-ScheduledTaskAction -Execute $Pyw -Argument "-m ntpro.supervisor" -WorkingDirectory $EngineDir
# بعد از ورود کاربر (MT5 به نشست کاربری نیاز دارد؛ ورود خودکار ویندوز را با netplwiz فعال کنید)
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host "تسک $TaskName ثبت و اجرا شد." -ForegroundColor Green
Write-Host "لاگ: $EngineDir\data\logs\engine.log"
Write-Host "کد راه‌اندازی اولین ورود: $EngineDir\data\SETUP_CODE.txt (چند ثانیه بعد ساخته می‌شود)"
