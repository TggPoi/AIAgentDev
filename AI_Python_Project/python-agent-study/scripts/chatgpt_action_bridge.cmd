@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0chatgpt_action_bridge.ps1" %*
pause
