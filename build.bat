@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem 桌面版打包脚本（PyInstaller onedir）
rem 产出: dist\deadlock-tongyi\deadlock-tongyi.exe      主程序（无控制台）
rem       dist\deadlock-tongyi\deadlock-tongyi-cli.exe  命令行版（可用 --selftest）

echo ==========================================
echo  deadlock-tongyi desktop build (onedir)
echo ==========================================
echo.

echo [1/4] generating icon ...
python packaging\make_icon.py
if errorlevel 1 goto failed

echo [2/4] cleaning previous build ...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [3/4] running PyInstaller (5-15 min, log goes to build_log.txt) ...
python -m PyInstaller --clean --noconfirm --distpath dist --workpath build packaging\deadlock-tongyi.spec > build_log.txt 2>&1
if errorlevel 1 goto failed

echo [4/4] result:
if not exist "dist\deadlock-tongyi\deadlock-tongyi.exe" goto failed

echo   dist\deadlock-tongyi\deadlock-tongyi.exe       ^<- double click this
echo   dist\deadlock-tongyi\deadlock-tongyi-cli.exe   ^<- console version (--selftest)
echo.
powershell -NoProfile -Command "$mb=[math]::Round((Get-ChildItem dist -Recurse -File ^| Measure-Object Length -Sum).Sum/1MB,0); Write-Host ('  bundle size: ' + $mb + ' MB')"
echo.
echo Verifying the packaged build ...
"dist\deadlock-tongyi\deadlock-tongyi-cli.exe" --selftest
echo.
echo Done.
pause
exit /b 0

:failed
echo.
echo BUILD FAILED - see build_log.txt
pause
exit /b 1
