@echo off
rem Double-click to start the image generator and the Cloudflare tunnel (see start.ps1).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
pause
