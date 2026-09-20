@echo off
rem ============================================================
rem  Launch Deadlock with console logging (debug build of the mod)
rem  Steam must be running.
rem
rem  Why: the mod runs inside Panorama, where we cannot see errors.
rem  -condebug / -con_logfile makes the engine write its console to a
rem  file, which captures Panorama script errors and HTML panel
rem  navigation failures. Open that file and search for "panorama".
rem
rem  NOTE: scripts\read_console_log.py was removed together with the
rem  desktop version -- it belonged to the old "read chat from the
rem  game console log" source, which the mod方案 replaced.
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
echo.
echo Open that log and search for "panorama" to see mod script errors.
echo.
pause
endlocal
