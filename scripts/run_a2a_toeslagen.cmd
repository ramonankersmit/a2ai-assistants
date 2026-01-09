@echo off
setlocal
cd /d %~dp0\..\services\a2a_toeslagen_agent
python -m uvicorn server:app --host 127.0.0.1 --port 8010
