@echo off
setlocal enabledelayedexpansion
rem ============================================================================
rem  setup.bat - one-time setup for Sentinel-IR.
rem
rem  Run this once after cloning:
rem    1. checks Docker and Python are present;
rem    2. creates the .venv virtual environment and installs requirements.txt;
rem    3. creates deploy\.env from deploy\.env.example, filling every
rem       CHANGE_ME placeholder with a freshly generated random secret.
rem
rem  After this finishes, use start.bat to bring the stack up.
rem  Author: Colile
rem ============================================================================

cd /d "%~dp0"
echo.
echo === Sentinel-IR setup ===
echo.

rem --- 1. prerequisites ------------------------------------------------------
where docker >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker not found on PATH. Install Docker Desktop and re-run.
    exit /b 1
)
docker info >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker is installed but not running. Start Docker Desktop and re-run.
    exit /b 1
)
echo [ok] Docker is running.

set "PY=py -3.11"
%PY% --version >nul 2>&1
if errorlevel 1 (
    set "PY=python"
    !PY! --version >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Python 3.11 not found. Install it and re-run.
        exit /b 1
    )
)
echo [ok] Python found (%PY%).

rem --- 2. virtual environment --------------------------------------------------
if exist ".venv\Scripts\python.exe" (
    echo [ok] .venv already exists - reusing it.
) else (
    echo [..] Creating .venv ...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create .venv.
        exit /b 1
    )
)

echo [..] Upgrading pip and installing requirements.txt (this can take a few minutes) ...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Dependency install failed.
    exit /b 1
)
echo [ok] Python dependencies installed.

rem --- 3. deploy\.env --------------------------------------------------------
if exist "deploy\.env" (
    echo [ok] deploy\.env already exists - leaving it untouched.
    goto :done
)

echo [..] Creating deploy\.env from deploy\.env.example with generated secrets ...
".venv\Scripts\python.exe" -c "import secrets,pathlib; src=pathlib.Path('deploy/.env.example').read_text(); lines=[]; [lines.append(l.split('=',1)[0] + '=' + (secrets.token_hex(32) if l.split('=',1)[0]=='JWT_SECRET' else secrets.token_hex(16)) if ('=' in l and l.split('=',1)[1].strip().startswith('CHANGE_ME')) else l) for l in src.splitlines()]; pathlib.Path('deploy/.env').write_text('\n'.join(lines) + '\n')"
if errorlevel 1 (
    echo [ERROR] Failed to write deploy\.env.
    exit /b 1
)
echo [ok] deploy\.env created. Secrets are random; edit it if you want your own.

:done
rem --- 4. show the credentials this install will use --------------------------
echo.
echo === Login for this install (from deploy\.env) ===
for /f "tokens=2 delims==" %%A in ('findstr /b "BOOTSTRAP_ADMIN_USERNAME=" deploy\.env') do echo   Admin username    %%A
for /f "tokens=2 delims==" %%A in ('findstr /b "BOOTSTRAP_ADMIN_PASSWORD=" deploy\.env') do echo   Admin password    %%A
for /f "tokens=2 delims==" %%A in ('findstr /b "GRAFANA_ADMIN_PASSWORD=" deploy\.env') do echo   Grafana password  %%A ^(user: admin^)
for /f "tokens=2 delims==" %%A in ('findstr /b "NEO4J_PASSWORD=" deploy\.env') do echo   Neo4j password    %%A ^(user: neo4j^)
echo   These are also in deploy\.env at any time.
echo.
echo === Setup complete ===
echo Next: run  start.bat  to build and launch the stack.
echo.
endlocal
