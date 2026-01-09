@echo off
setlocal
REM Run from repo root. This opens 4 terminals.
start "MCP Tools" cmd /k "%~dp0run_mcp.cmd"
start "A2A Agents" cmd /k "%~dp0run_a2a.cmd"
start "Orchestrator" cmd /k "%~dp0run_orchestrator.cmd"
start "Web Shell" cmd /k "%~dp0run_web.cmd"
