@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  call setup.bat
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -c "import uvicorn, fastapi" >nul 2>nul
if errorlevel 1 (
  call setup.bat
  if errorlevel 1 goto failed
)
echo Второе мнение: http://127.0.0.1:8000
echo Откройте этот адрес в браузере. Демо: demo / demo123.
echo Оставьте это окно открытым. Для остановки нажмите Ctrl+C.
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
if errorlevel 1 goto failed
exit /b 0
:failed
echo Не удалось запустить приложение. Сохраните текст ошибки из этого окна.
echo Если порт 8000 занят, закройте ранее запущенное окно сервера.
pause
exit /b 1
