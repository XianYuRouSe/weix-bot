@echo off
setlocal
set "APP=%~dp0"
set "PY=C:\Python314\python.exe"
if not exist "%PY%" set "PY=python.exe"
cd /d "%APP%"
echo ============================================
echo  微信回复机器人 - 首次配置
echo ============================================
echo.
"%PY%" "%APP%app\setup.py" %*
echo.
pause
exit /b 0
