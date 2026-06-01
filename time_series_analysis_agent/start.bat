@echo off
REM Startup script for Time Series Analysis Agent (Windows)

echo ========================================
echo Time Series Analysis Agent
echo ========================================
echo.

REM Check if .env exists
if not exist .env (
    echo [ERROR] .env file not found!
    echo Please copy .env.example to .env and configure it.
    pause
    exit /b 1
)

echo [1/3] Starting Backend...
start "Backend API" cmd /k "call .venv\Scripts\activate && python main.py"

timeout /t 3 /nobreak >nul

echo [2/3] Starting Frontend...
start "Frontend Dev Server" cmd /k "npm run dev"

echo.
echo ========================================
echo Services Started!
echo ========================================
echo Backend API: http://localhost:8000
echo Frontend UI: http://localhost:3000
echo.
echo Press any key to exit this window...
pause >nul
