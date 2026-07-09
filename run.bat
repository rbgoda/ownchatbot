@echo off
REM ownchatbot — Windows launcher. Double-click to start.
cd /d "%~dp0"
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt
if not exist .env if exist .env.example copy .env.example .env >nul & echo Created .env (optional: add an LLM key)
echo.
echo   ownchatbot running -^>  http://localhost:8200   (admin)
echo                          http://localhost:8200/demo (test the widget)
echo   Press Ctrl+C to stop.
echo.
python -m uvicorn ownchatbot.server:app --host 127.0.0.1 --port 8200
pause
