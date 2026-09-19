@echo off
rem ============================================================
rem  Steam launch option generator for Tongyi (deadlock-tongyi)
rem
rem  Double-click this file. It puts the launch option on the
rem  clipboard; paste it into:
rem      Steam / Library / right-click Deadlock / Properties
rem      / Launch Options
rem
rem  Why copy-paste instead of typing it: the option needs an
rem  ABSOLUTE path, quoted because it contains spaces. One missing
rem  quote and Steam treats the whole thing as game arguments.
rem
rem  KEEP THIS FILE PURE ASCII. cmd.exe parses .bat files byte by
rem  byte; some multi-byte characters contain bytes that cmd reads
rem  as operators ( & | < > ), which cuts the line in half and
rem  produces a pile of "'xxx' is not recognized as an internal or
rem  external command" errors. Chinese comments here did exactly
rem  that - so: English only. (User-facing docs are in docs/.)
rem
rem  Two escaping rules that bit us, keep them:
rem    1) write %%command%% (a single % is eaten as a variable ref)
rem    2) build the quoted path with ^" ... ^" inside set (writing
rem       set "X="%Y%"" truncates the value at the second quote)
rem ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "LAUNCH="
if exist "dist\bridge\tongyi-launch.exe" (
  set "LAUNCH=%CD%\dist\bridge\tongyi-launch.exe"
) else (
  if exist ".venv\Scripts\pythonw.exe" (
    set "LAUNCH=%CD%\.venv\Scripts\pythonw.exe"
  ) else (
    set "LAUNCH=pythonw"
  )
  set "LAUNCH=!LAUNCH! -m dlchat.launcher"
)

set LAUNCH_Q=^"%LAUNCH%^"
set OPTS=%LAUNCH_Q% %%command%%

echo.
echo ============================================================
echo  Tongyi launcher  -  Steam launch option
echo ============================================================
echo.
echo Paste this into Steam [Library - Deadlock - Properties - Launch Options]:
echo.
echo %OPTS%
echo.
echo It is already on your clipboard (Ctrl+V).
echo.
echo After that: the translation bridge starts with the game and
echo shuts down when you quit. No manual start_bridge.bat needed.
echo.
echo If the clipboard copy failed, select the line above manually.
echo.

rem  clip has no /NOXLF switch: passing it makes clip fail outright and the
rem  clipboard keeps the PREVIOUS content - much worse than a trailing newline.
rem  Steam trims the trailing newline on paste.
echo %OPTS%| clip
if errorlevel 1 (
  echo [WARN] could not write the clipboard - copy the line above by hand.
) else (
  echo Copied to clipboard.
)
echo.
pause
endlocal
