@echo off
chcp 65001 >nul
rem اجرای دستی موتور در پنجره (برای تست). برای اجرای دائمی از install_service.ps1 استفاده کنید.
cd /d "%~dp0.."
".venv\Scripts\python.exe" -m ntpro.main
pause
