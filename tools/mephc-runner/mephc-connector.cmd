@echo off
setlocal
cd /d "%LOCALAPPDATA%\MePhCRunner"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%LOCALAPPDATA%\MePhCRunner\mephc-connector.ps1"
exit /b %ERRORLEVEL%
