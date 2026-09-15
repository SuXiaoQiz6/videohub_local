@echo off
cd /d "%~dp0.."
".venv\Scripts\uvicorn.exe" backend.main:app --reload --host 127.0.0.1 --port 8000
