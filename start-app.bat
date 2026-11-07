@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM ---------------------------------------------------------------------------
REM Lead Gen Automation Engine. Double-click to start.
REM
REM Two processes, one window:
REM   - the engine (Python) on 127.0.0.1:8771 - the sheet, the finders, the ledger
REM   - the screens (Next.js) on 127.0.0.1:3200 - what you look at
REM The browser only ever talks to 3200; Next passes /api through to 8771, so
REM nothing in the browser knows the engine's address. Close this window to
REM stop both.
REM
REM   start-app.bat           build the screens once if needed, then start
REM   start-app.bat rebuild   rebuild the screens first (after editing web\)
REM
REM The V1 interface is still at http://127.0.0.1:3200/legacy.
REM ---------------------------------------------------------------------------
REM Next.js deps stay on C: (C:\ClaudeDeps is a junction to D:, and Next cannot build across drives).
set "DEPS=C:\ClaudeDepsLocal\leadgen-web"
set "URL=http://127.0.0.1:3200/"

where node >nul 2>&1
if errorlevel 1 (
  echo.
  echo   Node.js was not found. Install Node.js 18+ from https://nodejs.org and run this again.
  echo.
  pause
  exit /b 1
)

REM ---- the engine -------------------------------------------------------------
REM Find a Python that actually RUNS.
REM `if exist` is not a test: a venv built on a different Windows profile leaves
REM Scripts\python.exe in place, but starting it fails with "No Python at ..."
REM because it points at an interpreter under the other profile. Launch it and
REM see, rather than trusting the file to be there.
set "PY="
call :try "C:\ClaudeDeps\leadgen-venv\Scripts\python.exe"
call :try "C:\ClaudeDeps\docpipeline-venv\Scripts\python.exe"
call :try "python"
call :try "py"

if not defined PY (
  echo.
  echo   Could not find a working Python. Install Python 3.11+ and run this again.
  echo.
  pause
  exit /b 1
)

"%PY%" -c "import fastapi, uvicorn, multipart" 2>nul || "%PY%" -m pip install -r requirements.txt

curl -s -o nul http://127.0.0.1:8771/api/config
if errorlevel 1 (
  echo Starting the engine ...
  REM /b keeps it in this window, so closing the window stops it too.
  start "" /b "%PY%" -m uvicorn webapp.server:app --host 127.0.0.1 --port 8771 --log-level warning
) else (
  echo The engine is already running on 8771 - using it.
)

REM ---- the screens ------------------------------------------------------------
cd web
REM npm install DELETES the node_modules junction and rebuilds a real folder inside the Drive
REM backup, so it is followed every time by moving it back out and relinking.
node -e "require.resolve('next/package.json')" >nul 2>&1
if errorlevel 1 (
  echo Installing the screen packages, first start on this profile ...
  call npm install --no-audit --no-fund || goto :failed
  call :relocate || goto :failed
)
REM The build output is regenerable too, so it lives outside the backup as well.
if not exist ".next" (
  if not exist "%DEPS%\next-build" mkdir "%DEPS%\next-build"
  mklink /J ".next" "%DEPS%\next-build" >nul || goto :failed
)
if /i "%~1"=="rebuild" if exist ".next\BUILD_ID" del ".next\BUILD_ID"
if not exist ".next\BUILD_ID" (
  echo Building the screens, about 30 seconds ...
  call npm run build || goto :failed
)

echo.
echo   Lead Gen Automation Engine
echo   Python: %PY%
echo   opening %URL%
echo   (close this window to stop the app)
echo.

start "" /min cmd /c "timeout /t 4 /nobreak >nul & start %URL%"
call npm run start
exit /b 0

:relocate
REM Heavy, regenerable folders must not sit in the Google Drive backup. Drive skips junctions.
REM The target MUST itself be called node_modules: Node follows the junction to the real path
REM and then walks UP looking for a folder named node_modules, so any other name breaks every
REM import with ERR_MODULE_NOT_FOUND.
REM robocopy, not move: Google Drive holds a lock on files it is still syncing, and `move`
REM fails with "Access denied" on a fresh install. robocopy exit codes below 8 are success.
if exist "%DEPS%\node_modules" rmdir /s /q "%DEPS%\node_modules"
robocopy "node_modules" "%DEPS%\node_modules" /E /MOVE /NFL /NDL /NJH /NJS /NP /R:2 /W:2 >nul
if errorlevel 8 exit /b 1
if exist "node_modules" rmdir /s /q "node_modules"
mklink /J "node_modules" "%DEPS%\node_modules" >nul || exit /b 1
exit /b 0

:failed
echo.
echo   The screens could not be started. The message above says why.
echo   The engine's own page is at http://127.0.0.1:8771/legacy
pause
exit /b 1

:try
if defined PY goto :eof
%~1 -c "import sys" >nul 2>&1
if errorlevel 1 goto :eof
set "PY=%~1"
goto :eof
