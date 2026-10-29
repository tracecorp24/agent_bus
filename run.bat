@echo off
setlocal
set "DIR=%~dp0"
"%DIR%.venv\Scripts\python.exe" -m agentbus.cli %*
