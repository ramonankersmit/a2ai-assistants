@echo off
setlocal
cd /d %~dp0\..\services\mcp_tools
python -m uvicorn server:app --host 127.0.0.1 --port 8000
