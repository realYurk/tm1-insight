@echo off
REM ============================================================
REM  TM1 Insight one-click launcher
REM  Double-click to start the Web UI. No manual commands needed.
REM  First run auto-installs dependencies (1-2 min, needs internet).
REM ============================================================
setlocal
chcp 65001 >nul

cd /d "%~dp0"

echo.
echo  [TM1 Insight] Checking Python environment...

REM ---- 1. Locate a REAL Python interpreter ----
REM Priority: known installs first (most reliable), then PATH, then py launcher.
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
    if not errorlevel 1 (
        set "PY=py"
        set "PYARGS=-3"
    )
)

if not defined PY (
    echo  [ERROR] No usable Python found. Please install Python 3.9+ and check "Add to PATH".
    echo          Download: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo  [TM1 Insight] Using Python: %PY%

REM ---- 2. Report actual Python version and gate on unsupported versions ----
REM    显示真实版本，避免静默使用另一台电脑上的全局 Python；
REM    低于 3.9 时提前退出并给出清晰中文错误，而非内部堆栈。
set "PYVER="
for /f "tokens=2 delims= " %%v in ('"%PY%" %PYARGS% -c "import sys;print(sys.version.split()[0])" 2^>nul') do set "PYVER=%%v"
if not defined PYVER (
    echo  [ERROR] 无法确定 Python 版本：%PY%
    echo          可能是 WindowsApps 占位程序或损坏的安装。
    echo          请安装官方 Python 3.9+ 并勾选 "Add to PATH"。
    pause
    exit /b 1
)
echo  [TM1 Insight] Python version: %PYVER%

REM    校验主版本号：提取第一个 "." 前的数字，判断是否 >= 3.9
for /f "tokens=1 delims=." %%a in ("%PYVER%") do set "PYMAJOR=%%a"
for /f "tokens=2 delims=." %%b in ("%PYVER%") do set "PYMINOR=%%b"
if not defined PYMINOR set "PYMINOR=0"

REM    仅当主版本 < 3 时才必然不满足；主版本 == 3 需比较次版本
set "OKPY=0"
if %PYMAJOR% GTR 3 set "OKPY=1"
if %PYMAJOR% EQU 3 if %PYMINOR% GEQ 9 set "OKPY=1"

if "%OKPY%"=="0" (
    echo.
    echo  [ERROR] 检测到 Python %PYVER%，低于最低支持版本 3.9。
    echo          TM1 Insight 源码运行要求 Python 3.9 或更高版本。
    echo          请安装 Python 3.9+ 后重试：https://www.python.org/downloads/
    echo          项目不会自动升级或修改你的系统 Python，请自行安装。
    echo.
    pause
    exit /b 1
)

REM ---- 3. Check dependencies ----
REM NOTE: the package is named TM1py (capital T). Importing lowercase tm1py
REM always raises ModuleNotFoundError, which would wrongly trigger reinstall.
"%PY%" %PYARGS% -c "import fastapi, uvicorn, duckdb, TM1py, jinja2" >nul 2>nul
if errorlevel 1 goto install_deps
goto start_web

:install_deps
echo.
echo  [TM1 Insight] First run: installing dependencies (may take 2-5 min)...
echo  [TM1 Insight] Trying aliyun mirror first, falling back to tsinghua mirror.
echo.
"%PY%" %PYARGS% -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple --timeout 60
if errorlevel 1 goto install_deps_tsinghua
goto start_web

:install_deps_tsinghua
echo  [TM1 Insight] Aliyun mirror failed, retrying tsinghua mirror...
"%PY%" %PYARGS% -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout 60
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
echo  [TM1 Insight] Starting Web UI. Browser opens once after the selected port is ready.
echo  [TM1 Insight] Close this window to stop the service.
echo.

REM Point PYTHONPATH at src (tm1_insight lives under src, no pip install -e needed)
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
"%PY%" %PYARGS% -m tm1_insight.cli web

REM If we reach here the web command exited unexpectedly; keep window open.
echo.
echo  [ERROR] Web service failed to start. See error messages above.
pause
