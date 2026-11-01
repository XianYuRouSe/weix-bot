@echo off
setlocal
set "LOCK=%~dp0logs\bot.lock"
echo 正在停止机器人...
if not exist "%LOCK%" goto :nobot
set "BOTPID="
set /p BOTPID=<"%LOCK%"
if not defined BOTPID goto :nobot
powershell -NoProfile -Command "$p = Get-Process -Id %BOTPID% -ErrorAction SilentlyContinue; if ($p -and ($p.ProcessName -eq 'python' -or $p.ProcessName -eq 'pythonw')) { Stop-Process -Id %BOTPID% -Force; exit 0 } else { exit 1 }"
if errorlevel 1 goto :mismatch
echo 已停止
goto :cleanup
:mismatch
echo 锁文件里的 PID %BOTPID% 不是机器人进程，已跳过（没有动其它 Python 程序）
goto :cleanup
:nobot
echo 没有发现正在运行的机器人
:cleanup
del /q "%LOCK%" >nul 2>&1
ping -n 2 127.0.0.1 >nul
exit /b 0
