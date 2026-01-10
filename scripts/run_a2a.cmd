@echo off
setlocal
REM Starts all A2A agents in separate terminals

start "A2A Toeslagen Agent" cmd /k "%~dp0run_a2a_toeslagen.cmd"
start "A2A Bezwaar Agent"   cmd /k "%~dp0run_a2a_bezwaar.cmd"
start "A2A GenUI Agent"     cmd /k "%~dp0run_a2a_genui.cmd"
