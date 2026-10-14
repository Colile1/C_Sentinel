@echo off
setlocal
rem ============================================================================
rem  console.bat - open the Sentinel-IR operator console in the browser.
rem
rem    console.bat              start the console on http://127.0.0.1:8010
rem                             and open it in the default browser
rem
rem  The console needs only the .venv from setup.bat. With the stack down it
rem  still serves the screens that read the committed attack capture; run
rem  start.bat first to use the business, graph and GraphRAG screens.
rem  Press Ctrl+C in this window to stop it.
rem
rem  Author: Colile
rem ============================================================================

cd /d "%~dp0"

set "PY=.venv\Scripts\python.exe"
"%PY%" -c "import fastapi, uvicorn, common" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] .venv missing or incomplete. Run setup.bat first.
    exit /b 1
)

rem Open the browser about three seconds from now, once uvicorn is listening.
rem `ping` is the wait for the same reason as in start.bat.
start "" /b cmd /c "ping -n 4 127.0.0.1 >nul & start "" http://127.0.0.1:8010"
"%PY%" -m console.main
