@echo off
REM ============================================================
REM  TM1 Insight one-click launcher
REM  Double-click to start the Web UI. No manual commands needed.
REM  First run auto-installs dependencies (1-2 min, needs internet).
REM ============================================================
setlocal enabledelayedexpansion
chcp 65001 >nul

cd /d "%~dp0"

echo.
echo  [TM1 Insight] Checking Python environment...

REM ---- 1. Locate a REAL Python interpreter ----
REM Priority: known installs first (most reliable), then PATH, then py launcher.
REM We resolve full paths and reject WindowsApps stubs (which exit code 49 silently).
set "PY="

REM 1a. conda / pyenv / standard installs (absolute, known-good)
if exist "D:\01_Work\01_Env\anaconda\python.exe" set "PY=D:\01_Work\01_Env\anaconda\python.exe"
if not defined PY if exist "D:\01_Work\01_Env\pyenv\data_env\python.exe" set "PY=D:\01_Work\01_Env\pyenv\data_env\python.exe"
if not defined PY if exist "C:\Python313\python.exe" set "PY=C:\Python313\python.exe"
if not defined PY if exist "C:\Python312\python.exe" set "PY=C:\Python312\python.exe"
if not defined PY if exist "C:\Python311\python.exe" set "PY=C:\Python311\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"

REM 1b. resolve "python" on PATH to its full path, reject WindowsApps stub
if not defined PY (
    for /f "delims=" %%i in ('where python 2^>nul') do (
        echo %%i | findstr /i "WindowsApps" >nul
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
    if not errorlevel 1 set "PY=py -3"
)

if not defined PY (
    echo  [ERROR] No usable Python found. Please install Python 3.9+ and check "Add to PATH".
    echo          Download: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo  [TM1 Insight] Using Python: %PY%

REM ---- 2. Check dependencies ----
REM NOTE: the package is named TM1py (capital T). Importing lowercase tm1py
REM always raises ModuleNotFoundError, which would wrongly trigger reinstall.
%PY% -c "import fastapi, uvicorn, duckdb, TM1py, jinja2" >nul 2>nul
if errorlevel 1 goto install_deps
goto start_web

:install_deps
echo.
echo  [TM1 Insight] First run: installing dependencies (may take 2-5 min)...
echo  [TM1 Insight] Trying aliyun mirror first, falling back to tsinghua mirror.
echo.
%PY% -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple --timeout 60
if errorlevel 1 goto install_deps_tsinghua
goto start_web

:install_deps_tsinghua
echo  [TM1 Insight] Aliyun mirror failed, retrying tsinghua mirror...
%PY% -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout 60
if errorlevel 1 goto install_deps_fail
goto start_web

:install_deps_fail
echo.
echo  [ERROR] Dependency install failed. Possible reasons:
echo         1. No access to PyPI mirror (corporate firewall/proxy)
echo         2. Python version too old (need 3.9+) or too new
echo         3. Not enough disk space
echo.
echo  Try manually:  %PY% -m pip install -r requirements.txt
echo.
pause
exit /b 1

:start_web
REM ---- 3. Start Web UI (auto-open browser) ----
echo.
echo  [TM1 Insight] Starting Web UI. Browser will open http://localhost:8000
echo  [TM1 Insight] Close this window to stop the service.
echo.

start "" http://localhost:8000

REM Point PYTHONPATH at src (tm1_insight lives under src, no pip install -e needed)
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
%PY% -m tm1_insight.cli web

REM If we reach here the web command exited unexpectedly; keep window open.
echo.
echo  [ERROR] Web service failed to start. See error messages above.
pause
