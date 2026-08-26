@echo off
setlocal
cd /d "%LOCALAPPDATA%\MePhCRunner"
"%SystemRoot%\System32\wsl.exe" -d Ubuntu -- /home/icy/miniconda3/envs/mp/bin/python /opt/mephc-runner/current/mcp_server.py
endlocal
