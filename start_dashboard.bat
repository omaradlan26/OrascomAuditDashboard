@echo off
cd /d "%~dp0"
set FLASK_APP=app.py
python -m flask run
