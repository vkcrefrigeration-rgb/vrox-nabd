@echo off
cd /d C:\Users\frost\Desktop\VROX_HMI
start /min python server.py
timeout /t 3
ngrok http 3000
