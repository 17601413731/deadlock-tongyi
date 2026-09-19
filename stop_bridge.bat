@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem 停止本地翻译桥（按端口找进程，不需要记 PID）

echo 正在查找占用 8791 端口的进程...
set "FOUND="
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8791" ^| findstr "LISTENING"') do (
  set "FOUND=1"
  echo   结束 PID %%p
  taskkill /F /PID %%p >nul 2>&1
  if errorlevel 1 echo   [失败] PID %%p 结束不了，可能权限不足；请用任务管理器结束 python.exe
)

if not defined FOUND echo   没有进程在监听 8791（桥本来就没跑）
echo.
echo 完成。按任意键关闭。
pause
