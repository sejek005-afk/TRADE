# نصب NeuroTrader Pro روی VPS ویندوزی — بدون دست زدن به برنامه‌ی دیگری که روی سرور اجرا می‌شود.
# اجرا (PowerShell به‌عنوان Administrator):
#   Set-ExecutionPolicy -Scope Process Bypass; .\install.ps1
$ErrorActionPreference = "Stop"
$EngineDir = Split-Path -Parent $PSScriptRoot
$Port = 8810

Write-Host "== NeuroTrader Pro installer ==" -ForegroundColor Cyan
Write-Host "Engine folder: $EngineDir"

# ۱) پایتون (از همان python.org؛ محیط مجازی جدا ساخته می‌شود تا پکیج‌های برنامه‌ی دیگر تغییر نکنند)
$py = (Get-Command py -ErrorAction SilentlyContinue)
if ($py) { $PyExe = "py"; $PyArgs = @("-3.12") } else { $PyExe = "python"; $PyArgs = @() }
try { & $PyExe @PyArgs --version } catch {
    Write-Host "Python 3.11/3.12 نصب نیست. از python.org نصب کنید (تیک Add to PATH) و دوباره اجرا کنید." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path "$EngineDir\.venv")) {
    & $PyExe @PyArgs -m venv "$EngineDir\.venv"
}
& "$EngineDir\.venv\Scripts\python.exe" -m pip install --upgrade pip
& "$EngineDir\.venv\Scripts\python.exe" -m pip install -r "$EngineDir\requirements.txt"

# ۲) پوشه‌ی داده (جدا از برنامه‌ی دیگر)
$Data = "$EngineDir\data"
New-Item -ItemType Directory -Force -Path $Data | Out-Null

# ۳) پورت: نباید 8765 (برنامه‌ی دیگر) باشد و باید آزاد باشد
$busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    Write-Host "پورت $Port اشغال است (PID $($busy.OwningProcess)). در data\config.json پورت دیگری بگذارید." -ForegroundColor Yellow
}

# ۴) فایروال: فقط یک قانون جدید با نام خودمان اضافه می‌شود؛ قوانین دیگر دست نمی‌خورند
$ruleName = "NeuroTraderPro API $Port"
if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow | Out-Null
    Write-Host "Firewall rule added: $ruleName"
}

# ۵) تست سریع
Push-Location $EngineDir
& "$EngineDir\.venv\Scripts\python.exe" -m pytest -q tests
Pop-Location

Write-Host ""
Write-Host "نصب تمام شد." -ForegroundColor Green
Write-Host "قدم بعد: متاتریدر جداگانه (portable) را در C:\NeuroTraderPro\MT5 آماده کنید (README)،"
Write-Host "سپس scripts\install_service.ps1 را اجرا کنید."
