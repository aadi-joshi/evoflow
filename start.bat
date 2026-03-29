@echo off
cd /d "%~dp0"
echo Starting EvoFlow AI on http://localhost:8000
python -m uvicorn backend.api:app --host 0.0.0.0 --port 8000 --reload
