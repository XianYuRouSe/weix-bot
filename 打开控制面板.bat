@echo off
setlocal
set "APP=%~dp0"
set "PYW=C:\Python314\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw.exe"
cd /d "%APP%"
start "" "%PYW%" "%APP%app\panel.py"
exit /b 0
