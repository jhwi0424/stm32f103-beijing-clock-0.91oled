@echo off
cd /d "%~dp0"
python tools\stlink_clock.py --sync
pause
