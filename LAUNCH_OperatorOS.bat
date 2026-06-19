@echo off
title OperatorOS Launcher
cd /d "E:\IMPACT CLIMBING Dropbox\kyle Wilson\2.0\APP\ASPIRE OS new"

echo Starting OperatorOS Proxy...
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
