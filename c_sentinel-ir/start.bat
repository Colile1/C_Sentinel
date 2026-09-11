@echo off
setlocal
rem ============================================================================
rem  start.bat - build and launch the Sentinel-IR stack, then verify it.
rem
rem  Assumes setup.bat has already been run (.venv and deploy\.env exist).
rem
rem    start.bat            build if needed, start, wait for health, verify
rem    start.bat --seed     also load demo data and run the demo workflow
rem    start.bat --fresh    rebuild images from scratch before starting
rem
rem  Author: Colile
rem ============================================================================

cd /d "%~dp0"

set "COMPOSE=docker compose --env-file deploy\.env -f deploy\docker-compose.yml"
set "PY=.venv\Scripts\python.exe"
set "SEED=0"
set "BUILDARG=--build"

:parse
if "%~1"=="" goto checks
if /i "%~1"=="--seed"  set "SEED=1"
if /i "%~1"=="--fresh" set "BUILDARG=--build --no-cache"
shift
goto parse

:checks
if not exist "deploy\.env" (
    echo [ERROR] deploy\.env missing. Run setup.bat first.
    exit /b 1
)
if not exist "%PY%" (
    echo [ERROR] .venv missing. Run setup.bat first.
    exit /b 1
)
docker info >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker is not running. Start Docker Desktop and re-run.
    exit /b 1
)

echo.
echo === Starting Sentinel-IR ===
%COMPOSE% up %BUILDARG% -d
if errorlevel 1 (
    echo [ERROR] docker compose up failed.
    exit /b 1
)

echo.
echo [..] Waiting for containers to report healthy ...
%PY% scripts\verify_stack.py
if errorlevel 1 (
    echo.
    echo [warn] verify_stack.py reported a problem. Containers may still be
    echo        starting - re-run  %PY% scripts\verify_stack.py  in a minute.
)

if "%SEED%"=="1" (
    echo.
    echo === Seeding demo data ===
    %PY% scripts\seed_data.py
    echo.
    echo === Running demo workflow ===
    %PY% client\demo_workflow.py
)

echo.
echo === Sentinel-IR is up ===
echo   Gateway    http://localhost:8000/api/v1
echo   Consul     http://localhost:8500
echo   Grafana    http://localhost:3901
echo   Prometheus http://localhost:9090
echo   Neo4j      http://localhost:7474
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
