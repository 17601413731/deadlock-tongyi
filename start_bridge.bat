@echo off
rem ============================================================
rem  Tongyi bridge - local translation server for the Deadlock mod
rem  Keep this window open while playing. Closing it = mod offline.
rem  Before start: make sure Ollama is running (ollama serve / tray icon).
rem ============================================================
setlocal
cd /d "%~dp0"

echo ==========================================
echo   Tongyi bridge  (localhost:8791)
echo ==========================================
echo.
echo 1) Ollama must be running (the model is loaded on demand)
echo 2) This window starts the bridge on 127.0.0.1 and ::1 port 8791
echo 3) Then start Deadlock. In-game status line shows "tongyi ready"
echo.

set "PY=python"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import openai" >nul 2>&1
  if not errorlevel 1 set "PY=.venv\Scripts\python.exe"
)

%PY% scripts\run_bridge.py %*

echo.
echo Bridge exited. Press any key to close.
pause
endlocal
