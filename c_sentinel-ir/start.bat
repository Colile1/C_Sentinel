@echo off
setlocal
rem ============================================================================
rem  start.bat - build and launch Sentinel-IR and leave it ready to demonstrate.
rem
rem  Assumes setup.bat has already been run (.venv and deploy\.env exist).
rem
rem    start.bat              build if needed, start, verify, seed the demo
rem                           data and load the Neo4j knowledge graph
rem    start.bat --workflow   also run the Phase 1 business workflow once
rem                           (--seed is accepted as the old name for this)
rem    start.bat --fresh      rebuild images from scratch before starting
rem
rem  Seeding and the graph load are both idempotent, so running start.bat
rem  again on a running stack is safe. The scripts read deploy\.env
rem  themselves (libs/common/deploy_env.py), so they also work when run by hand
rem  from any terminal.
rem
rem  Author: Colile
rem ============================================================================

cd /d "%~dp0"

set "COMPOSE=docker compose --env-file deploy\.env -f deploy\docker-compose.yml"
set "PY=.venv\Scripts\python.exe"
set "WORKFLOW=0"
set "BUILDARG=--build"
set "PROBLEMS=0"

:parse
if "%~1"=="" goto checks
if /i "%~1"=="--workflow" set "WORKFLOW=1"
if /i "%~1"=="--seed"     set "WORKFLOW=1"
if /i "%~1"=="--fresh"    set "BUILDARG=--build --no-cache"
shift
goto parse

:checks
if not exist "deploy\.env" (
    echo [ERROR] deploy\.env missing. Run setup.bat first.
    exit /b 1
)
"%PY%" -c "import common.deploy_env, neo4j" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] .venv missing or incomplete. Run setup.bat first.
    exit /b 1
)
where docker >nul 2>&1
if errorlevel 1 (
    if exist "%ProgramFiles%\Docker\Docker\resources\bin\docker.exe" set "PATH=%ProgramFiles%\Docker\Docker\resources\bin;%PATH%"
)
docker info >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker is not running. Start Docker Desktop and re-run.
    exit /b 1
)

echo.
echo === 1/4 Starting Sentinel-IR ===
%COMPOSE% up %BUILDARG% -d
if errorlevel 1 (
    echo [ERROR] docker compose up failed.
    exit /b 1
)

echo.
echo === 2/4 Waiting for containers to report healthy ===
rem Kong, Neo4j and Grafana take up to a minute or two after `up` returns, so
rem poll rather than check once. `ping` is the wait because `timeout` refuses
rem to run when output is redirected.
set "ATTEMPT=0"
:wait_healthy
set /a ATTEMPT+=1
"%PY%" scripts\verify_stack.py >nul 2>&1
if not errorlevel 1 goto healthy
if %ATTEMPT% geq 18 (
    "%PY%" scripts\verify_stack.py
    echo [ERROR] The stack did not come up healthy within 3 minutes. See: %COMPOSE% ps
    exit /b 1
)
echo [..] not ready yet ^(check %ATTEMPT% of 18^) - waiting 10 seconds ...
ping -n 11 127.0.0.1 >nul
goto wait_healthy
:healthy
"%PY%" scripts\verify_stack.py

echo.
echo === 3/4 Seeding demo users and assets ===
"%PY%" scripts\seed_data.py
if errorlevel 1 (
    echo [warn] Seeding failed - check BOOTSTRAP_ADMIN_* in deploy\.env.
    set "PROBLEMS=1"
)

echo.
echo === 4/4 Loading the Neo4j knowledge graph ===
rem The graph is entirely derived - the loader rebuilds every node - so it is
rem cleared first. Otherwise alerts from earlier workflow runs linger and the
rem demo answers "4 alerts affect auth-service" where the report shows 2.
for /f "tokens=1,* delims==" %%A in ('findstr /b "NEO4J_PASSWORD=" deploy\.env') do set "NEO4J_PW=%%B"
%COMPOSE% exec -T neo4j cypher-shell -u neo4j -p "%NEO4J_PW%" "MATCH (n) DETACH DELETE n" >nul 2>&1
if errorlevel 1 echo [warn] Could not clear the old graph; loading over it.
rem The committed attack capture, so the graph matches the report's evidence.
"%PY%" -m kg.loader.main --file docs\evidence\step15-attack-events.jsonl
if errorlevel 1 (
    echo [warn] Graph load failed; retrying in 20 seconds ...
    ping -n 21 127.0.0.1 >nul
    "%PY%" -m kg.loader.main --file docs\evidence\step15-attack-events.jsonl
    if errorlevel 1 (
        echo [warn] Graph load failed - check NEO4J_* in deploy\.env.
        set "PROBLEMS=1"
    )
)

if "%WORKFLOW%"=="1" (
    echo.
    echo === Running the Phase 1 business workflow ===
    "%PY%" client\demo_workflow.py
    if errorlevel 1 set "PROBLEMS=1"
)

echo.
if "%PROBLEMS%"=="0" (
    echo === Sentinel-IR is up and ready to demonstrate ===
) else (
    echo === Sentinel-IR is up, but a step above reported a problem ===
)
echo   Gateway    http://localhost:8000/api/v1
echo   Consul     http://localhost:8500
echo   Grafana    http://localhost:3901
echo   Prometheus http://localhost:9090
echo   Neo4j      http://localhost:7474
echo.
echo   Phase 2 workflow   %PY% scripts\run_security_workflow.py --skip-capture
echo   Ask the graph      %PY% -m rag.generation.main "Which alerts affect auth-service?"
echo.
echo === Login for this install (from deploy\.env) ===
for /f "tokens=2 delims==" %%A in ('findstr /b "BOOTSTRAP_ADMIN_USERNAME=" deploy\.env') do echo   Admin username    %%A
for /f "tokens=2 delims==" %%A in ('findstr /b "BOOTSTRAP_ADMIN_PASSWORD=" deploy\.env') do echo   Admin password    %%A
for /f "tokens=2 delims==" %%A in ('findstr /b "GRAFANA_ADMIN_PASSWORD=" deploy\.env') do echo   Grafana password  %%A ^(user: admin^)
for /f "tokens=2 delims==" %%A in ('findstr /b "NEO4J_PASSWORD=" deploy\.env') do echo   Neo4j password    %%A ^(user: neo4j^)
echo.
echo   Stop with  stop.bat
echo.
endlocal
exit /b %PROBLEMS%
