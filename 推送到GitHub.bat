@echo off
setlocal
set "APP=%~dp0"
set "GIT=D:\Git\cmd\git.exe"
if not exist "%GIT%" set "GIT=git"
cd /d "%APP%"

if exist ".git" goto :have
"%GIT%" init -b main
:have

set "URL="
set /p URL=请输入你的 GitHub 仓库地址（https://github.com/用户名/仓库名.git）: 
if "%URL%"=="" goto :nourl

"%GIT%" remote remove origin >nul 2>&1
"%GIT%" remote add origin "%URL%"
"%GIT%" branch -M main
"%GIT%" tag v0.1.1 >nul 2>&1
echo.
echo 正在推送...
"%GIT%" push -u origin main
if errorlevel 1 goto :fail
"%GIT%" push origin --tags
if errorlevel 1 goto :fail
echo.
echo 推送完成。打开仓库看看：%URL%
exit /b 0

:fail
echo.
echo 推送失败，多半是没登录。两种办法：
echo   1) 用 Personal Access Token 当密码：提示输入用户名时填 GitHub 用户名，密码填 token
echo      token 在这里生成：https://github.com/settings/tokens  勾选 repo 权限
echo   2) 装 GitHub CLI 后执行：gh auth login
echo.
pause
exit /b 1

:nourl
echo 没输入地址，已退出。
pause
exit /b 0
