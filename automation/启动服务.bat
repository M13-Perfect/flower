@echo off
chcp 65001 >nul
cd /d "%~dp0inbox-service"

set "PORT=8770"

echo ============================================================
echo  Flower inbox-service  -^>  http://127.0.0.1:%PORT%
echo  Keep this window OPEN. Close it to stop the service.
echo ============================================================

rem ---- Free the port first: kill any leftover instance on PORT ----
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%PORT% " ^| findstr LISTENING') do (
    echo Port %PORT% is busy ^(PID %%P^). Stopping the old instance...
    taskkill /F /PID %%P >nul 2>&1
)

".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port %PORT%

echo.
echo Service stopped. Press any key to close.
pause >nul
