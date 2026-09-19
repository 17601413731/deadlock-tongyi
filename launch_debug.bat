@echo off
rem ============================================================
rem  Launch Deadlock with console logging (debug build of the mod)
rem  Steam must be running.
rem
rem  Why: the mod runs inside Panorama, where we cannot see errors.
rem  -condebug / -con_logfile makes the engine write its console to a
rem  file, which captures Panorama script errors and HTML panel
rem  navigation failures. We then read that file from Python.
rem ============================================================
setlocal

set "STEAM=D:\software\steam\steam.exe"
set "LOGNAME=dlchat_console.log"

echo Launching Deadlock with console log: %LOGNAME%
echo (Steam launch options are not touched; this passes args directly.)
echo.

"%STEAM%" -applaunch 1422450 -condebug -con_logfile %LOGNAME% -dev

echo.
echo Game launched. Console log will appear as %LOGNAME% somewhere under:
echo   D:\software\steam\steamapps\common\Deadlock\game\
echo Then run:  python scripts\read_console_log.py
echo.
pause
endlocal
