@echo off
rem ============================================================
rem  DeepSeek Harness Web launcher (local install)
rem  Uses the dsh installed in this folder's node_modules.
rem  No npx, no network, no package resolution wait.
rem  Browser: http://127.0.0.1:3080
rem  Keep this window open while using the GUI; closing it
rem  stops the server. Session data is saved automatically.
rem  To update dsh later: npm install @deepseek-ai/dsh@latest
rem ============================================================
title DeepSeek Harness Web

rem Switch to this script's folder so the local node_modules is found.
cd /d "%~dp0"

echo ============================================
echo   DeepSeek Harness Web GUI
echo   URL : http://127.0.0.1:3080
echo   Keep this window open; closing it stops the server.
echo ============================================
echo.

node "node_modules\@deepseek-ai\dsh\lib\bin.js" web

echo.
echo Server exited.
pause