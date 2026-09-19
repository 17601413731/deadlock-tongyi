@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem Prefer the project venv when it actually has the dependencies.
rem To see which interpreter is used: run.bat --selftest
set "PY=python"
if not exist ".venv\Scripts\python.exe" goto run
".venv\Scripts\python.exe" -c "import PySide6, rapidocr" >nul 2>&1
if errorlevel 1 goto warn
set "PY=.venv\Scripts\python.exe"
goto run

:warn
echo [note] .venv exists but has no dependencies - using the global python.
echo        Run install.bat if you want to use the venv.

:run
%PY% -m dlchat %*
pause
