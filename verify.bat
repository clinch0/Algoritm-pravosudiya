@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Сначала запустите setup.bat.
  exit /b 1
)
".venv\Scripts\python.exe" -m pytest tests -q
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m compileall -q app mcp_server tools
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" tools\verify_data_snapshot.py
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" tools\verify_sanctions.py
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" tools\smoke_mcp.py
if errorlevel 1 exit /b 1
echo Все проверки завершены.
