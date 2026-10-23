@echo off
setlocal
rem One-click launcher for the local LinkedIn supplement collector.
rem
rem   start_agent.bat                     run the agent (uses the default config)
rem   start_agent.bat --list-queries      preview the query matrix, no browser
rem   start_agent.bat --dry-run           collect, write collected-*.json, no upload
rem   start_agent.bat --reset-checkpoint  force a full re-scan
rem   start_agent.bat --config PATH ...   use a specific config file
rem
rem First run: creates an isolated venv in clients\linkedin_local_agent\.venv,
rem installs selenium + httpx there (the server venv is never touched), and
rem seeds %USERPROFILE%\.jobagg\linkedin-collector\config.json from the example.

set "ROOT=%~dp0..\.."
set "AGENT_DIR=%~dp0"
set "VENV_DIR=%AGENT_DIR%.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "REQS=%AGENT_DIR%requirements.txt"
set "CONFIG_DIR=%USERPROFILE%\.jobagg\linkedin-collector"
set "DEFAULT_CONFIG=%CONFIG_DIR%\config.json"

rem Pick a base Python (the "py" launcher first, then "python" on PATH).
set "BASE_PY="
py -3 --version >nul 2>&1 && set "BASE_PY=py -3"
if not defined BASE_PY (
    python --version >nul 2>&1 && set "BASE_PY=python"
)
if not defined BASE_PY (
    echo [agent] ERROR: Python 3 not found. Install Python 3.11+ and retry.
    pause
    exit /b 1
)

if not exist "%VENV_PY%" (
    echo [agent] First run: creating isolated venv at clients\linkedin_local_agent\.venv
    %BASE_PY% -m venv "%VENV_DIR%" || goto :setup_fail
    "%VENV_PY%" -m pip install --upgrade pip -q || goto :setup_fail
    echo [agent] Installing selenium + httpx ...
    "%VENV_PY%" -m pip install -q -r "%REQS%" || goto :setup_fail
)

if not exist "%DEFAULT_CONFIG%" (
    mkdir "%CONFIG_DIR%" 2>nul
    copy /y "%AGENT_DIR%config.example.json" "%DEFAULT_CONFIG%" >nul
    echo [agent] Seeded config at %DEFAULT_CONFIG%
    echo [agent]   The bundled Melbourne, Sydney, and Austin locations are ready.
    echo [agent]   Edit config.json only if you want different locations or roles.
)

if "%JOBAGG_DEVICE_TOKEN%"=="" (
    echo [agent] NOTE: JOBAGG_DEVICE_TOKEN is not set. Uploads need it; get one via
    echo [agent]   POST /api/v1/import/devices with the X-API-Key header, then
    echo [agent]   setx JOBAGG_DEVICE_TOKEN "jagg_..."
    echo [agent] --dry-run and --list-queries work without it.
)

rem Run from the repo root so the clients.* package is importable. If the
rem caller passed their own --config, do not inject the default one.
pushd "%ROOT%"
echo %* | findstr /C:"--config" >nul
if errorlevel 1 (
    "%VENV_PY%" -m clients.linkedin_local_agent.main --config "%DEFAULT_CONFIG%" %*
) else (
    "%VENV_PY%" -m clients.linkedin_local_agent.main %*
)
set "RC=%ERRORLEVEL%"
popd

if not "%RC%"=="0" (
    echo.
    echo [agent] exited with code %RC%
    pause
)
exit /b %RC%

:setup_fail
echo [agent] setup failed - see the messages above.
pause
exit /b 1
