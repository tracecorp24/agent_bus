@echo off
setlocal
set "DIR=%~dp0"

:: Eger parametresiz calistirildiysa yeni bir CMD penceresinde TUI dashboard'u baslat
if "%~1"=="" (
    start "AGENT BUS - Multi-Agent Dashboard" cmd /k "cd /d "%DIR%" && "%DIR%.venv\Scripts\python.exe" -m agentbus.cli tui && exit"
    exit /b 0
)

:: Parametre verilmisse mevcut konsolda calistir
"%DIR%.venv\Scripts\python.exe" -m agentbus.cli %*
