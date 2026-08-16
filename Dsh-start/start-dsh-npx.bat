@echo off
rem ============================================================
rem  DeepSeek Harness Web 启动器（npx 最新版）
rem  每次启动都用 npx 拉取 @deepseek-ai/dsh@latest，
rem  保证你运行的始终是最新发布的版本。
rem  浏览器地址：http://127.0.0.1:3080
rem  请保持本窗口开启；关闭窗口即停止服务。
rem  会话数据与本地启动器共享（使用同一个 DSH_HOME）。
rem ============================================================
title DeepSeek Harness Web (npx @latest)

echo ============================================
echo   DeepSeek Harness Web GUI  (npx @latest)
echo   URL : http://127.0.0.1:3080
echo   正在用 npx 解析最新版本...
echo   （首次启动需下载，之后会复用缓存，速度很快）
echo   请保持本窗口开启；关闭窗口即停止服务。
echo ============================================
echo.

call npx --yes @deepseek-ai/dsh@latest web

echo.
echo 服务已退出。
pause
