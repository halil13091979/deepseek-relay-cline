@echo off
set PROFILE=%~dp0chrome-profile
set CHROME="C:\Program Files\Google\Chrome\Application\chrome.exe"

if not exist %CHROME% (
    set CHROME="C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
)

start "" %CHROME% ^
    --remote-debugging-port=9222 ^
    --user-data-dir="%PROFILE%" ^
    --no-first-run ^
    --no-default-browser-check ^
    https://chat.deepseek.com/