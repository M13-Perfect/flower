@echo off
chcp 65001 >nul
cd /d "%~dp0inbox-service"
echo ============================================================
echo  Flower inbox-service  ->  http://127.0.0.1:8770
echo  Keep this window OPEN. Close it to stop the service.
echo ============================================================
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8770
echo.
echo Service stopped. Press any key to close.
pause >nul
