@echo off
setlocal EnableExtensions
"%LOCALAPPDATA%\Programs\Python\Python312\python.exe" "%~dp0tools\mephc-flow\mephc_flow.py" %*
exit /b %ERRORLEVEL%
