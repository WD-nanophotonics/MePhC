@echo off
setlocal EnableExtensions
if not "%~1"=="" (
  echo MEPHC_CLOSEOUT_ARGUMENTS_FORBIDDEN 1>&2
  exit /b 64
)
call "%~dp0mephc-flow.cmd" closeout
exit /b %ERRORLEVEL%
