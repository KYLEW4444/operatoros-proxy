@echo off
title OperatorOS Watcher
cd /d "E:\IMPACT CLIMBING Dropbox\kyle Wilson\2.0\APP\operatoros-proxy"

echo ============================================================
echo  OperatorOS Proxy Watcher
echo  Auto-restarts the proxy whenever rgp_proxy.py or
echo  OperatorOS.html changes. Keep this window open.
echo  Close it (or press Ctrl+C) to stop the proxy.
echo ============================================================

REM Make sure nothing else is already holding port 5001 first.
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -like '*rgp_proxy.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5001" ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1

set PYTHONIOENCODING=utf-8
python watch_proxy.py
pause
