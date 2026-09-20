@echo off
rem ============================================================
rem  Build the ONE artifact you send to players: build\tongyi-players.zip
rem
rem  Layout inside the zip:
rem      tongyi_launch\       the bridge + launcher (START_HERE.bat first)
rem      mod\                  the game mod (pak) + its own readme
rem
rem  Why two folders: the bridge is installed by running START_HERE.bat,
rem  the mod is imported through Deadlock Mod Manager. Different install
rem  paths, different update paths - mixing them in one folder confuses
rem  players and makes updates messy.
rem
rem  Everything this script touches lives under build\ : the zip goes to
rem  build\ top level, the staging tree under build\.work\. Nothing is
rem  written to the project root.
rem
rem  KEEP PURE ASCII (cmd parses .bat byte by byte; multi-byte characters
rem  can contain bytes it reads as operators and the line gets cut in half).
rem ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0.."

set "SRC=build\.work\bridge"
set "STAGE=build\.work\stage"
set "PLAYER=packaging\player"
set "MODVPK=build\tongyi-pak01_dir.vpk"
set "OUT=build\tongyi-players.zip"

if not exist "%SRC%\tongyi-launch.exe" (
  echo.
  echo [ERROR] %SRC%\tongyi-launch.exe not found.
  echo         Build it first:
  echo           python -m PyInstaller --clean --noconfirm --distpath build/.work --workpath build/.work/pyinstaller packaging\bridge.spec
  echo.
  pause
  exit /b 1
)
if not exist "%MODVPK%" (
  echo.
  echo [ERROR] mod pak not found: %MODVPK%
  echo         Build it first ^(close Deadlock first^):
  echo           python scripts\stage_compile.py --pack
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
  echo         Close any running tongyi-launch window, then run this again.
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
rem  The pak is a single FILE now (build\tongyi-pak01_dir.vpk), imported in DMM
rem  by picking that file. We used to emit two copies (a folder-based import
rem  path), which silently diverged - one stale copy meant "I changed it but the
rem  game shows the old behaviour" with no error at all.
rem  The zip keeps a tongyi- prefix: clearer than pak01_dir.vpk, and the mod
rem  readme explains the rename if DMM insists on the pakNN_dir.vpk pattern.
copy /y "%MODVPK%" "%STAGE%\mod\tongyi-pak01_dir.vpk" >nul || goto failed
copy /y "%PLAYER%\MOD-README-zh.txt" "%STAGE%\mod\README-zh.txt" >nul || goto failed
if exist "%STAGE%\tongyi_launch\_internal\__pycache__" rd /s /q "%STAGE%\tongyi_launch\_internal\__pycache__"

echo [4/4] zipping -> %OUT% ...
if exist "%OUT%" del /q "%OUT%"
if not exist build mkdir build
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; Compress-Archive -Path 'build\.work\stage\*' -DestinationPath '%OUT%' -CompressionLevel Optimal"
if errorlevel 1 (
  echo [WARN] Compress-Archive failed, trying .NET ZipFile ...
  powershell -NoProfile -Command "$ErrorActionPreference='Stop'; Add-Type -AssemblyName System.IO.Compression.FileSystem; if (Test-Path '%OUT%') { Remove-Item '%OUT%' }; [System.IO.Compression.ZipFile]::CreateFromDirectory((Resolve-Path 'build\.work\stage').Path, (Join-Path (Get-Location) '%OUT%'))"
  if errorlevel 1 goto failed
)

rem  The staging tree is a pure intermediate: drop it so build\.work stays small
rem  and the next run starts from a clean copy anyway.
rd /s /q "%STAGE%" >nul 2>&1

rem  Promote the bridge out of .work so the handy folder holds deliverables only:
rem  build\tongyi-launch\ is what Steam launch options and make_launch_option.bat
rem  point at. .work\bridge is the PyInstaller output (keeping it there means two
rem  48MB copies, so the folder is MOVED, not copied).
echo [extra] promoting the bridge -> build\tongyi-launch\ ...
if exist "build\tongyi-launch" rd /s /q "build\tongyi-launch"
move "build\.work\bridge" "build\tongyi-launch" >nul

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
