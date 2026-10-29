@echo off
REM ============================================================
REM  TM1 Insight one-click launcher
REM  Double-click to start the Web UI. No manual commands needed.
REM  --check validates startup without launching a server or pausing.
REM  --no-browser launches the existing Web command without opening a browser.
REM  No automatic installation or environment changes.
REM ============================================================
setlocal DisableDelayedExpansion
chcp 65001 >nul

cd /d "%~dp0"

echo.
echo  [TM1 Insight] Checking Python environment...

REM ---- 1. Locate a REAL Python interpreter ----
REM Priority: project .venv, known installs, PATH, then py launcher.
REM We resolve full paths and reject WindowsApps stubs (which exit code 49 silently).
set "PY="
set "PYARGS="

REM 1a. conda / pyenv / standard installs (absolute, known-good)
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY if exist "C:\Python313\python.exe" set "PY=C:\Python313\python.exe"
if not defined PY if exist "C:\Python312\python.exe" set "PY=C:\Python312\python.exe"
if not defined PY if exist "C:\Python311\python.exe" set "PY=C:\Python311\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY if defined CONDA_PREFIX if exist "%CONDA_PREFIX%\python.exe" set "PY=%CONDA_PREFIX%\python.exe"

REM 1b. resolve "python" on PATH to its full path, reject WindowsApps stub
if not defined PY (
    for /f "delims=" %%i in ('where python 2^>nul') do (
        echo "%%i" | findstr /i "WindowsApps" >nul
        if not errorlevel 1 (
            REM skip stub
        ) else (
            if not defined PY set "PY=%%i"
        )
    )
)

REM 1c. py launcher
if not defined PY (
    where py >nul 2>nul
    if not errorlevel 1 (
        set "PY=py"
        set "PYARGS=-3"
    )
)

REM A side-by-side source download may not contain a venv. Reuse the adjacent
REM tm1-suite environment only as a last resort; dependency checks still apply.
if not defined PY if exist "%~dp0..\tm1-suite\.venv\Scripts\python.exe" (
    set "PY=%~dp0..\tm1-suite\.venv\Scripts\python.exe"
    echo  [TM1 Insight] Using the adjacent tm1-suite Python environment.
)

if not defined PY (
    echo  [ERROR] No Python interpreter was found in this project, PATH, or known locations.
    echo          Project folder: "%~dp0"
    echo          Use the project with its existing .venv, or make Python available on PATH.
    set "START_EXIT=1"
    goto startup_failed
)

echo  [TM1 Insight] Using Python: "%PY%"

REM ---- 2. Execute Python directly; never parse --version or FOR /F output ----
REM Keep stderr visible. A broken project .venv must not silently fall back to PATH.
"%PY%" %PYARGS% -c "import sys; print('[TM1 Insight] Python version:', sys.version.split()[0]); print('[TM1 Insight] Interpreter:', sys.executable)"
if not "%ERRORLEVEL%"=="0" goto python_unavailable

"%PY%" %PYARGS% -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 2)"
REM Read ERRORLEVEL outside parentheses to avoid expansion of a stale value.
set "PY_CHECK_EXIT=%ERRORLEVEL%"
if "%PY_CHECK_EXIT%"=="2" goto python_too_old
if not "%PY_CHECK_EXIT%"=="0" goto python_unavailable

REM ---- 3. Check dependencies ----
REM TM1py is case-sensitive. Preserve the real import exception; never auto-install.
"%PY%" %PYARGS% -c "import fastapi, uvicorn, duckdb, TM1py, jinja2"
if not "%ERRORLEVEL%"=="0" goto dependencies_failed
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
"%PY%" %PYARGS% -c "import tm1_insight.cli; import tm1_insight.api.app; print('[TM1 Insight] Startup checks passed.')"
if not "%ERRORLEVEL%"=="0" goto entry_failed
if /i "%~1"=="--check" exit /b 0

:start_web
REM ---- 3. Start Web UI (auto-open browser) ----
echo.
echo  [TM1 Insight] Starting Web UI. Browser opens unless --no-browser was selected.
echo  [TM1 Insight] Close this window to stop the service.
echo.

"%PY%" %PYARGS% -m tm1_insight.cli web %*
set "START_EXIT=%ERRORLEVEL%"
if "%START_EXIT%"=="0" exit /b 0

REM If we reach here the web command exited unexpectedly; keep window open.
echo.
echo  [ERROR] Web service failed to start. See error messages above.
goto startup_failed

:python_unavailable
echo  [ERROR] Selected Python could not run the startup probe. See the actual error above.
echo          Selected interpreter: "%PY%"
echo          The project environment was not changed; no fallback interpreter was used.
set "START_EXIT=1"
goto startup_failed

:python_too_old
echo  [ERROR] The selected interpreter runs, but Python 3.9 or newer is required.
echo          No Python installation or virtual environment was changed.
set "START_EXIT=2"
goto startup_failed

:dependencies_failed
echo  [ERROR] Required dependencies could not be imported. See the actual exception above.
echo          No packages were installed. Review requirements.txt in your managed environment.
set "START_EXIT=3"
goto startup_failed

:entry_failed
echo  [ERROR] Project entry import failed. See the actual exception above.
set "START_EXIT=4"

:startup_failed
if /i not "%~1"=="--check" pause
exit /b %START_EXIT%
