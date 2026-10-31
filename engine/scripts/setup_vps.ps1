# NeuroTrader Pro - one-click setup for the Windows VPS.
# Safe next to the existing program: own folder (C:\NeuroTraderPro), own venv, port 8810,
# magic 31102026, own scheduled task "NeuroTraderPro". Uses the MetaTrader terminal that is
# already running, without logging in (the account of that terminal is never changed).
$ErrorActionPreference = "Stop"
$Root = "C:\NeuroTraderPro"
$Engine = "$Root\engine"
$Port = 8810
$TaskName = "NeuroTraderPro"
$Info = "$([Environment]::GetFolderPath('Desktop'))\NeuroTraderPro-INFO.txt"

# ---- self-elevate ----
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -NoExit -File `"$PSCommandPath`""
    exit
}
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$ProgressPreference = "SilentlyContinue"
function Step($t) { Write-Host ""; Write-Host "==> $t" -ForegroundColor Cyan }

# ---- 1) download code ----
Step "Downloading NeuroTrader Pro from GitHub"
New-Item -ItemType Directory -Force -Path $Root | Out-Null
$zip = "$env:TEMP\ntpro_main.zip"
Invoke-WebRequest -UseBasicParsing "https://github.com/sejek005-afk/TRADE/archive/refs/heads/main.zip" -OutFile $zip
$tmp = "$env:TEMP\ntpro_extract"
if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
Expand-Archive $zip -DestinationPath $tmp -Force
$src = Get-ChildItem $tmp | Select-Object -First 1
# stop only our own processes before updating files
Get-CimInstance Win32_Process | Where-Object { ($_.Name -like "python*.exe") -and ($_.CommandLine -match "-m ntpro\.(main|supervisor)") } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
New-Item -ItemType Directory -Force -Path $Engine | Out-Null
# copy everything except data/ and .venv (keep existing data on updates)
robocopy "$($src.FullName)\engine" $Engine /E /XD data .venv __pycache__ /NFL /NDL /NJH /NJS /NP | Out-Null
New-Item -ItemType Directory -Force -Path "$Engine\data" | Out-Null
Write-Host "Code in $Engine"

# ---- 2) python ----
Step "Finding Python 3.11-3.13"
$PyExe = $null
foreach ($v in @("3.12", "3.11", "3.13")) {
    try { $p = (& py "-$v" -c "import sys;print(sys.executable)" 2>$null); if ($LASTEXITCODE -eq 0 -and $p) { $PyExe = $p.Trim(); break } } catch {}
}
if (-not $PyExe) {
    try { $p = (& python -c "import sys;print(sys.executable) if (3,11)<=sys.version_info[:2]<=(3,13) else None" 2>$null); if ($p -and $p -ne "None") { $PyExe = $p.Trim() } } catch {}
}
if (-not $PyExe) {
    Write-Host "Installing Python 3.12 (all users)..."
    $inst = "$env:TEMP\python-3.12.10-amd64.exe"
    Invoke-WebRequest -UseBasicParsing "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe" -OutFile $inst
    Start-Process $inst -Wait -ArgumentList "/quiet InstallAllUsers=1 PrependPath=0 Include_launcher=1 Include_test=0"
    $PyExe = "C:\Program Files\Python312\python.exe"
}
Write-Host "Python: $PyExe"

# ---- 3) venv + packages (separate from the other program) ----
Step "Creating virtual environment and installing packages (a few minutes)"
if (-not (Test-Path "$Engine\.venv\Scripts\python.exe")) { & $PyExe -m venv "$Engine\.venv" }
$VPy = "$Engine\.venv\Scripts\python.exe"
& $VPy -m pip install --upgrade pip --quiet
& $VPy -m pip install -r "$Engine\requirements.txt" --quiet
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

# ---- 4) MetaTrader: use the terminal that is already running ----
Step "Looking for the running MetaTrader 5 terminal"
$terms = @(Get-CimInstance Win32_Process -Filter "Name='terminal64.exe'" | Select-Object -ExpandProperty ExecutablePath -Unique)
$mt5Path = ""
if ($terms.Count -ge 1) {
    $mt5Path = $terms[0]
    Write-Host "Using running terminal: $mt5Path"
    if ($terms.Count -gt 1) { Write-Host "Note: several terminals are running; using the first. Change it in the app if needed." -ForegroundColor Yellow }
} else {
    Write-Host "No running MetaTrader 5 found. The engine will attach to the default terminal when it starts." -ForegroundColor Yellow
}

# ---- 5) initial config (only if none exists) ----
$cfgPath = "$Engine\data\config.json"
if (-not (Test-Path $cfgPath)) {
    $cfg = @{
        mode = "demo"; allow_live = $false; bot_enabled = $true
        symbols = @("XAUUSD", "EURUSD")
        mt5 = @{ shared_terminal = $true; path = $mt5Path; login = 0 }
    }
    $json = $cfg | ConvertTo-Json -Depth 5
    [IO.File]::WriteAllText($cfgPath, $json, (New-Object Text.UTF8Encoding($false)))
    Write-Host "Config written (demo mode, bot ON, XAUUSD + EURUSD)."
} else {
    Write-Host "Existing config kept."
}

# ---- 6) firewall (one new rule with our own name) ----
Step "Firewall rule for port $Port"
$ruleName = "NeuroTraderPro API $Port"
if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow | Out-Null
}
$busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($busy) { Write-Host "WARNING: port $Port is already in use by PID $($busy.OwningProcess)" -ForegroundColor Yellow }

# ---- 7) scheduled task (separate name) + start ----
Step "Registering auto-start task '$TaskName' and starting the engine"
$Pyw = "$Engine\.venv\Scripts\pythonw.exe"
$user = "$env:USERDOMAIN\$env:USERNAME"
$action = New-ScheduledTaskAction -Execute $Pyw -Argument "-m ntpro.supervisor" -WorkingDirectory $Engine
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false }
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
Start-ScheduledTask -TaskName $TaskName

# ---- 8) wait for engine and show connection info ----
Step "Waiting for the engine to start"
$fp = "$Engine\data\FINGERPRINT.txt"; $sc = "$Engine\data\SETUP_CODE.txt"
for ($i = 0; $i -lt 90 -and -not (Test-Path $fp); $i++) { Start-Sleep 2 }
$ip = ""
try { $ip = (Invoke-RestMethod -UseBasicParsing "https://api.ipify.org" -TimeoutSec 10) } catch {}
$lines = @(
    "NeuroTrader Pro is running.",
    "",
    "App server address : $ip`:$Port",
    "Certificate fingerprint : $(if (Test-Path $fp) { Get-Content $fp } else { '(not ready - see logs)' })",
    "Setup code (first login): $(if (Test-Path $sc) { Get-Content $sc } else { '(already set up)' })",
    "",
    "MetaTrader terminal : $(if ($mt5Path) { $mt5Path } else { 'default' })",
    "Mode: demo | Symbols: XAUUSD, EURUSD | Magic 31102026 | Port $Port",
    "Logs: $Engine\data\logs\engine.log",
    "",
    "Make sure 'Algo Trading' is ON in MetaTrader.",
    "Enable automatic Windows logon (netplwiz) so it restarts after a VPS reboot."
)
$lines | Set-Content -Encoding UTF8 $Info
Write-Host ""
$lines | ForEach-Object { Write-Host $_ -ForegroundColor Green }
Write-Host ""
Write-Host "Saved to $Info"
if (Test-Path "$Engine\data\logs\engine.log") {
    Write-Host ""; Write-Host "Last log lines:" -ForegroundColor Cyan
    Get-Content "$Engine\data\logs\engine.log" -Tail 15
}
