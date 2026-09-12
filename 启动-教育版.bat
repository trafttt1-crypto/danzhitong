@echo off
chcp 936 >nul
cd /d "%~dp0"
set DZT_EDITION=edu
set PYTHONIOENCODING=utf-8
rem 优先用 Python 3.11 的常见安装位置；找不到就退回 PATH 里的 python。
rem 这里不要写死某个用户名下的绝对路径，否则别人克隆下来直接跑不起来。
set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not exist "%PY%" set "PY=python"
echo.
echo  ============================================
echo   单智通 - 教育版（实训）
echo   启动后请访问 http://127.0.0.1:5000
echo   关闭此窗口即停止服务
echo  ============================================
echo.
"%PY%" app.py
pause
