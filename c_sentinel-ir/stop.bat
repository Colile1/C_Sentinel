@echo off
setlocal
rem ============================================================================
rem  stop.bat - stop the Sentinel-IR stack.
rem
rem    stop.bat           stop and remove containers, keep the data volumes
rem    stop.bat --wipe    also delete the Postgres / Neo4j / Grafana volumes
rem                       (start.bat re-seeds and reloads the graph)
rem
rem  Author: Colile
rem ============================================================================

cd /d "%~dp0"

where docker >nul 2>&1
if errorlevel 1 (
    if exist "%ProgramFiles%\Docker\Docker\resources\bin\docker.exe" set "PATH=%ProgramFiles%\Docker\Docker\resources\bin;%PATH%"
)

set "COMPOSE=docker compose --env-file deploy\.env -f deploy\docker-compose.yml"

if /i "%~1"=="--wipe" (
    echo === Stopping Sentinel-IR and deleting data volumes ===
    %COMPOSE% down -v
) else (
    echo === Stopping Sentinel-IR (data volumes kept) ===
    %COMPOSE% down
)

echo.
echo Done.
endlocal
