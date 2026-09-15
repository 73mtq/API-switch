@echo off
cd /d "%~dp0"
python -m PyInstaller --noconsole --onefile --clean --name "API-Switch" app.py
pause
