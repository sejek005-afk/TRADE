@echo off
chcp 65001 >nul
rem NeuroTrader Pro - backtest (read-only, does not touch the running engine or other programs)
rem Note: do not click inside this window while it runs (Windows pauses it in "Select" mode).
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
set OUT=data\logs\backtest_result.txt
echo Backtest is running (XAUUSD + EURUSD, 90 days). Please wait, this window closes by itself...
echo NeuroTrader Pro backtest - %date% %time% > "%OUT%"
for %%S in (XAUUSD EURUSD) do (
  echo. >> "%OUT%"
  echo ===================== %%S - 90 days ===================== >> "%OUT%"
  start "" /low /wait /b ".venv\Scripts\python.exe" scripts\backtest.py --symbol %%S --days 90 --per-strategy >> "%OUT%" 2>&1
)
echo DONE >> "%OUT%"
