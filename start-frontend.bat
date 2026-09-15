@echo off
cd /d "%~dp0"
echo Starting frontend on http://127.0.0.1:5173
call npm run dev -- --host 127.0.0.1 --port 5173
