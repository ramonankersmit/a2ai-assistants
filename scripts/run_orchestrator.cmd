@echo off
setlocal
cd /d %~dp0\..\apps\orchestrator
python -m uvicorn main:app --host 127.0.0.1 --port 10002
