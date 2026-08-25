@echo off
setlocal
set "MEPHC_RUNNER_RUNTIME=%LOCALAPPDATA%\MePhCRunner"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%MEPHC_RUNNER_RUNTIME%\mephc-runner.ps1" %*
set "MEPHC_RUNNER_EXIT=%ERRORLEVEL%"
endlocal & exit /b %MEPHC_RUNNER_EXIT%
