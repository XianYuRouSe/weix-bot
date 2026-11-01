@echo off
setlocal
set "APP=%~dp0"
set "PYW=C:\Python314\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw.exe"
cd /d "%APP%"
echo 正在启动微信回复机器人...
start "" /min "%PYW%" "%APP%app\bot.py"
exit /b 0
