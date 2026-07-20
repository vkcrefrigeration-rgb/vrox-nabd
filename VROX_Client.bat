@echo off
cd /d "%~dp0"
start /min python server.py
timeout /t 3 >nul
start chrome --app=http://127.0.0.1:3000/client.html --window-size=480,800
