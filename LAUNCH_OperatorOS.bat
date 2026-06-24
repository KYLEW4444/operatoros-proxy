@echo off
title OperatorOS Launcher
cd /d "E:\IMPACT CLIMBING Dropbox\kyle Wilson\2.0\APP\ASPIRE OS new"

echo Stopping any existing proxy so fresh code is loaded...

REM 1) Kill ANY python process whose command line runs rgp_proxy.py (most reliable).
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -like '*rgp_proxy.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1

REM 2) Kill the proxy window by title (covers our minimized launch).
taskkill /F /FI "WINDOWTITLE eq OperatorOS Proxy" >nul 2>&1

REM 3) Kill whatever is still LISTENING on port 5001 (covers manual / background starts).
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5001" ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>&1

REM 4) Wait until port 5001 is actually free (up to ~20s) so the fresh proxy can bind.
set _tries=0
:waitfree
netstat -ano | findstr ":5001" | findstr "LISTENING" >nul 2>&1
if not %errorlevel%==0 goto portfree
set /a _tries+=1
if %_tries% geq 20 goto portfree
ping -n 2 127.0.0.1 >nul 2>&1
goto waitfree
:portfree

echo Starting OperatorOS Proxy...
REM PYTHONIOENCODING=utf-8 keeps the proxy's status logging (arrows/checkmarks)
REM from crashing on Windows consoles that default to cp1252.
set PYTHONIOENCODING=utf-8
start "OperatorOS Proxy" /min python rgp_proxy.py

timeout /t 3 /nobreak >nul

echo Opening OperatorOS...
set CHROME=""
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" set CHROME="C:\Program Files\Google\Chrome\Application\chrome.exe"
if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" set CHROME="C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set CHROME="%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"

if %CHROME%=="" (
    start "" "E:\IMPACT CLIMBING Dropbox\kyle Wilson\2.0\APP\ASPIRE OS new\OperatorOS.html"
) else (
    start "" %CHROME% --allow-file-access-from-files "E:\IMPACT CLIMBING Dropbox\kyle Wilson\2.0\APP\ASPIRE OS new\OperatorOS.html"
)
exit
