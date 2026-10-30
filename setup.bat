@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3.12 -m venv .venv
  if errorlevel 1 (
    echo Не удалось создать окружение. Требуется установленный Python 3.12 и Python Launcher.
    exit /b 1
  )
)
".venv\Scripts\python.exe" -m pip install -r requirements.lock.txt
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip check
if errorlevel 1 exit /b 1
echo Установка завершена. Запустите run.bat.
