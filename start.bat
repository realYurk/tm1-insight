@echo off
REM ============================================================
REM  tm1-suite 一键启动器
REM  双击本文件即可启动 Web UI，无需手动敲命令。
REM  首次运行会自动安装依赖（约 1-2 分钟，需联网）。
REM ============================================================
setlocal enabledelayedexpansion
chcp 65001 >nul

cd /d "%~dp0"

echo.
echo  [tm1-suite] 正在检查 Python 环境...

REM ---- 1. 定位 Python ----
set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY ( where py >nul 2>nul && set "PY=py -3" )
if not defined PY (
    echo  [错误] 未找到 Python。请先安装 Python 3.9+ 并勾选 "Add to PATH"。
    echo         下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

REM ---- 2. 检查依赖是否已装 ----
%PY% -c "import fastapi, uvicorn, duckdb, tm1py, jinja2" >nul 2>nul
if errorlevel 1 (
    echo.
    echo  [tm1-suite] 首次运行，正在安装依赖（可能需 2-5 分钟，请耐心等待）...
    echo  [tm1-suite] 优先使用阿里云镜像，失败会自动回退清华镜像再试。
    echo.

    REM 先试阿里云镜像
    %PY% -m pip install -r requirements.txt -i http://mirrors.aliyun.com/pypi/simple --trusted-host mirrors.aliyun.com --timeout 60
    if errorlevel 1 (
        echo  [tm1-suite] 阿里云镜像安装失败，回退清华镜像重试...
        %PY% -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout 60
        if errorlevel 1 (
            echo.
            echo  [错误] 依赖安装失败。以下是可能的原因：
            echo         1. 网络无法访问 PyPI 镜像（公司内网防火墙/代理拦截）
            echo         2. Python 版本过旧（需 3.9+）或过新（个别依赖暂不支持）
            echo         3. 磁盘空间不足
            echo.
            echo  请尝试手动执行以下命令查看详细错误：
            echo         %PY% -m pip install -r requirements.txt
            echo.
            pause
            exit /b 1
        )
    )

    REM 依赖装好后，安装本包（可编辑模式）
    %PY% -m pip install -e . --timeout 60
    if errorlevel 1 (
        echo  [警告] 依赖已装，但本包安装失败。仍尝试启动...
    )
)

REM ---- 3. 启动 Web UI（自动开浏览器） ----
echo.
echo  [tm1-suite] 正在启动，浏览器将自动打开 http://localhost:8000
echo  [tm1-suite] 关闭本窗口即停止服务。
echo.

start "" http://localhost:8000

REM 设置 PYTHONPATH 指向 src，然后启动
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
%PY% -m tm1_suite.cli web

pause
