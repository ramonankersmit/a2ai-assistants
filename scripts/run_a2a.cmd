@echo off
setlocal
REM Starts both A2A agents in two terminals
start "A2A Toeslagen Agent" cmd /k "%~dp0run_a2a_toeslagen.cmd"
start "A2A Bezwaar Agent" cmd /k "%~dp0run_a2a_bezwaar.cmd"
