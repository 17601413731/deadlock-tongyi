@echo off
rem ============================================================
rem  dlchat mod - build, pack and install into Deadlock addons
rem  Close Deadlock first (the game locks addons\pak01_dir.vpk).
rem ============================================================
setlocal
cd /d "%~dp0"

echo.
echo [1/3] checking game process...
tasklist /FI "IMAGENAME eq deadlock.exe" 2>nul | find /I "deadlock.exe" >nul
if not errorlevel 1 goto GAME_RUNNING

echo [2/3] compiling + packing + installing...
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
"%PY%" scripts\stage_compile.py --install
if errorlevel 1 goto FAILED

echo.
echo [3/3] done. Installed to:
echo   D:\software\steam\steamapps\common\Deadlock\game\citadel\addons\pak01_dir.vpk
echo (previous file backed up as pak01_dir.vpk.bak)
echo.
echo Next: start the bridge (start_bridge.bat) if it is not running, then start the game.
goto END

:GAME_RUNNING
echo.
echo Deadlock is running. Close it completely, then run this script again.
echo.

:FAILED
echo.
echo Build failed - read the messages above.
echo.

:END
pause
endlocal
