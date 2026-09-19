@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ==========================================
echo  deadlock-tongyi installer (into .venv)
echo ==========================================
echo.

if exist ".venv\Scripts\python.exe" goto havevenv
echo [1/4] creating virtualenv .venv ...
python -m venv .venv
goto pip

:havevenv
echo [1/4] .venv already exists, skipping

:pip
echo [2/4] upgrading pip ...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet

echo [3/4] installing dependencies (PySide6 / RapidOCR, ~400MB first time) ...
".venv\Scripts\python.exe" -m pip install -e ".[ocr]"
if errorlevel 1 goto failed

echo.
echo [4/4] self test ...
".venv\Scripts\python.exe" -m dlchat --selftest
echo.
echo Done. Start with run.bat
echo Remember: the translation backend must be up (ollama serve, or a cloud key in config.yaml).
pause
exit /b 0

:failed
echo.
echo [ERROR] dependency install failed. Try a mirror:
echo   .venv\Scripts\python.exe -m pip install -e ".[ocr]" -i https://pypi.tuna.tsinghua.edu.cn/simple
pause
exit /b 1
