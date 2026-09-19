@echo off
rem ============================================================
rem  Tongyi (deadlock-tongyi) - one-time setup  (run this ONCE, then just play)
rem
rem  What it does:
rem    1. builds the Steam launch option for THIS folder
rem       (the path differs per machine, so it must be generated here)
rem    2. copies it to the clipboard
rem    3. prints the 3 steps you have to do by hand
rem
rem  KEEP PURE ASCII. cmd.exe parses .bat byte by byte and some
rem  multi-byte characters contain bytes it reads as operators
rem  ( & | < > ), which cuts lines in half. Chinese docs live in
rem  the .txt next to this file.
rem
rem  Escaping rules that bit us before - do not "simplify":
rem    * write %%command%% (a single % is eaten as a variable ref)
rem    * build quoted paths as ^" ... ^" inside set (set "X="%Y%""
rem      truncates the value at the second quote)
rem ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title Tongyi setup

set "LAUNCH=%~dp0tongyi-launch.exe"
if not exist "%LAUNCH%" (
  echo.
  echo [ERROR] tongyi-launch.exe is not next to this file.
  echo         Extract the whole zip first, then run this again.
  echo.
  pause
  exit /b 1
)

set LAUNCH_Q=^"%LAUNCH%^"
set OPTS=%LAUNCH_Q% %%command%%

echo.
echo ============================================================
echo  Tongyi setup  -  one time only
echo ============================================================
echo.
echo STEP 1  Steam launch option (already on your clipboard)
echo.
echo   Paste this line into:
echo      Steam / Library / right-click Deadlock / Properties
echo      / Launch Options
echo.
echo   %OPTS%
echo.
echo   (Path is generated for this folder: %~dp0)
echo.
echo STEP 2  API key
echo.
echo   Start the game once. Then open this page in your browser:
echo      http://localhost:8791/settings
echo   Paste your own DeepSeek API key and save. It is stored on
echo   this PC only and is never shared.
echo   Get a key at: https://platform.deepseek.com
echo.
echo STEP 3  Play
echo.
echo   From now on just press Play in Steam. The translation
echo   bridge starts with the game and closes when you quit.
echo   In game, the dot next to the chat box is green when the
echo   bridge is connected.
echo.
echo ------------------------------------------------------------
echo  Notes
echo    - Nothing here runs in the background or at boot.
echo    - To remove Tongyi later: clear the Steam launch option
echo      and delete this folder.
echo    - Logs: %%APPDATA%%\deadlock-tongyi\logs\launcher.log
echo    - Full guide (Chinese): see the .txt file next to this one.
echo ------------------------------------------------------------
echo.

rem  clip (no /NOXLF: that switch does not exist and makes clip fail outright,
rem  which would silently leave the OLD clipboard content in place - worse than
rem  a trailing newline). Steam trims the trailing newline when you paste.
echo %OPTS%| clip
if errorlevel 1 (
  echo [WARN] could not write the clipboard - copy the line above by hand.
)

echo Copied the launch option to your clipboard. Press any key to
echo close this window.
echo.
pause
endlocal
