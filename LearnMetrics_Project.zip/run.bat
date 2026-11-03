@echo off
cd /d "%~dp0"
if not exist .venv py -m venv .venv
call .venv\Scripts\activate
pip install -r requirements.txt
if not exist .env (
  copy .env.example .env
  echo Edit .env (SECRET_KEY and the MySQL password), then run run.bat again.
  pause
  exit /b 1
)
python run.py
pause
