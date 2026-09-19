@echo off
rem ============================================================
rem  Build the zip you send to players.
rem
rem  Output layout (inside dist\deadlock-tongyi-players.zip):
rem      tongyi_launch\       the bridge + launcher (START_HERE.bat first)
rem      mod\                  the game mod (pak) + its own readme
rem
rem  Why two folders: the bridge is installed by running START_HERE.bat,
rem  the mod is imported through Deadlock Mod Manager. Different install
rem  paths, different update paths - mixing them in one folder confuses
rem  players and makes updates messy.
rem
rem  KEEP PURE ASCII (cmd parses .bat byte by byte; multi-byte characters
rem  can contain bytes it reads as operators and the line gets cut in half).
rem ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0.."

set "SRC=dist\bridge"
set "STAGE=dist\package"
set "PLAYER=packaging\player"
set "MODVPK=dist_mod\dlchat_local\pak01_dir.vpk"
set "OUT=dist\deadlock-tongyi-players.zip"

if not exist "%SRC%\tongyi-launch.exe" (
  echo.
  echo [ERROR] %SRC%\tongyi-launch.exe not found.
  echo         Build it first:
  echo           python -m PyInstaller --clean --noconfirm --distpath dist --workpath build_pkgs packaging\bridge.spec
  echo.
  pause
  exit /b 1
)
if not exist "%MODVPK%" (
  echo.
  echo [ERROR] mod pak not found: %MODVPK%
  echo         Build it first:
  echo           python scripts\build_mod.py
  echo.
  pause
  exit /b 1
)

rem  Warn (do not fail) if the mod sources are newer than the pak: shipping a
rem  stale mod is the kind of mistake nobody notices until a player reports it.
rem  (Doing the timestamp comparison in PowerShell: cmd has no sane way to
rem  compare file times.)
for /f %%F in ('powershell -NoProfile -Command "(Get-ChildItem -Path mod\panorama -Recurse -File -Include *.js,*.css,*.xml | Where-Object { $_.LastWriteTime -gt (Get-Item '%MODVPK%').LastWriteTime } | Measure-Object).Count"') do set "STALE=%%F"
if not "%STALE%"=="0" (
  echo.
  echo [WARN] %STALE% mod source file^(s^) are NEWER than the pak.
  echo        The zip would ship an outdated mod. Rebuild it with:
  echo          python scripts\stage_compile.py --pack
  echo.
)

echo [1/4] staging a clean copy ...
rem  A leftover tongyi-launch.exe (from testing --stay, or a game that was killed)
rem  keeps the old staging folder locked. Kill it, otherwise xcopy fails with
rem  "Access is denied" on every dll and the error is hard to read.
taskkill /IM tongyi-launch.exe /F >nul 2>&1
taskkill /IM tongyi-launch-cli.exe /F >nul 2>&1
if exist "%STAGE%" rd /s /q "%STAGE%"
if exist "%STAGE%" (
  echo.
  echo [ERROR] cannot clear %STAGE% - something still holds a file in it.
  echo         Close any running dlchat window, then run this again.
  echo.
  pause
  exit /b 1
)
mkdir "%STAGE%\tongyi_launch" || goto failed
mkdir "%STAGE%\mod" || goto failed
xcopy /e /i /q /y "%SRC%\*" "%STAGE%\tongyi_launch\" >nul || goto failed

echo [2/4] adding player files ...
rem  The Chinese guide goes to the zip root (so it is the first thing a player
rem  sees) AND into tongyi_launch\ (so it is still there after they move on to
rem  the launcher folder). Same file, two copies.
copy /y "%PLAYER%\README-zh.txt" "%STAGE%\README-zh.txt" >nul || goto failed
copy /y "%PLAYER%\START_HERE.bat" "%STAGE%\tongyi_launch\" >nul || goto failed
rem  Keep every filename ASCII: a Chinese filename inside an ASCII .bat is the
rem  same byte-parsing trap we hit before (and it also breaks some unzip tools).
copy /y "%PLAYER%\README-zh.txt" "%STAGE%\tongyi_launch\" >nul || goto failed
rem  PyInstaller drops config.yaml into _internal\ (datas collapse there), so the
rem  folder the player opens has no visible config. Copy it up next to the exe:
rem  that is where paths.default_config_path() looks first, and it is what the
rem  readme tells them to edit. Same content, so nothing breaks either way.
if exist "%STAGE%\tongyi_launch\_internal\config.yaml" copy /y "%STAGE%\tongyi_launch\_internal\config.yaml" "%STAGE%\tongyi_launch\config.yaml" >nul

echo [3/4] adding the mod ...
rem  The pak gets an ascii name with a tongyi- prefix here: it is clearer than
rem  pak01_dir.vpk, and the mod readme explains the rename if DMM insists on
rem  the pakNN_dir.vpk pattern.
copy /y "%MODVPK%" "%STAGE%\mod\tongyi-pak01_dir.vpk" >nul || goto failed
copy /y "%PLAYER%\MOD-README-zh.txt" "%STAGE%\mod\README-zh.txt" >nul || goto failed
if exist "%STAGE%\tongyi_launch\_internal\__pycache__" rd /s /q "%STAGE%\tongyi_launch\_internal\__pycache__"

echo [4/4] zipping -> %OUT% ...
if exist "%OUT%" del /q "%OUT%"
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; Compress-Archive -Path 'dist\package\*' -DestinationPath '%OUT%' -CompressionLevel Optimal"
if errorlevel 1 (
  echo [WARN] Compress-Archive failed, trying .NET ZipFile ...
  powershell -NoProfile -Command "$ErrorActionPreference='Stop'; Add-Type -AssemblyName System.IO.Compression.FileSystem; if (Test-Path '%OUT%') { Remove-Item '%OUT%' }; [System.IO.Compression.ZipFile]::CreateFromDirectory((Resolve-Path 'dist\package').Path, (Join-Path (Get-Location) '%OUT%'))"
  if errorlevel 1 goto failed
)

for %%F in ("%OUT%") do set "MB=%%~zF"
set /a MB=%MB%/1048576
echo.
echo Done: %OUT%  (about %MB% MB)
echo Contents: tongyi_launch\  (bridge)   +   mod\  (game mod)
echo Players: extract, run tongyi_launch\START_HERE.bat, then import mod\ in DMM.
echo.
pause
exit /b 0

:failed
echo.
echo [ERROR] building the zip failed - see the messages above.
echo.
pause
exit /b 1
