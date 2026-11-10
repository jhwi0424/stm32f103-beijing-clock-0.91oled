@echo off
if exist "%LOCALAPPDATA%\STM32BeijingClock\BeijingClockSync.exe" (
    start "" "%LOCALAPPDATA%\STM32BeijingClock\BeijingClockSync.exe"
    exit /b 0
)
call "%~dp0install_usb_autosync.cmd"
