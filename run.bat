@echo off
setlocal
set "BASE=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%BASE%tools\start_gui_admin.ps1"
if errorlevel 1 pause
endlocal
