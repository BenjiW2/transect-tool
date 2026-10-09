@echo off
rem Double-click on Windows to start the transect tool.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo First run: setting up ^(needs internet, takes a minute^)...
  py -3 -m venv .venv || python -m venv .venv || (echo Python 3 is needed: https://www.python.org/downloads/ & pause & exit /b 1)
  .venv\Scripts\python -m pip install -q --upgrade pip
  .venv\Scripts\python -m pip install -q -r requirements.txt || (echo Install failed & pause & exit /b 1)
)
.venv\Scripts\python app.py
pause
