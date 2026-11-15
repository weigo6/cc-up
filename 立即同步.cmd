@echo off
cd /d "%~dp0"
py -3 cc_up_launcher.py sync
if errorlevel 1 pause
