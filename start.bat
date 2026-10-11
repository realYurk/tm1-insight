@echo off
REM ============================================================
REM  tm1-suite 一键启动器
REM  双击本文件即可启动 Web UI，无需手动敲命令。
REM  首次运行会自动安装依赖 (约 2-5 分钟，需联网)，装好后永久复用。
REM  若本地无数据，会自动生成一套演示数据，方便先看效果。
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
REM 注意: TM1py 的 import 名是 TM1py (大写 T)，写错大小写会误判。
%PY% -c "import fastapi, uvicorn, duckdb, TM1py, jinja2, typer, pydantic" >nul 2>nul
if errorlevel 1 (
    echo.
    echo  [tm1-suite] 首次运行，正在安装依赖 (约 2-5 分钟，请耐心等待) ...
    echo  [tm1-suite] 优先使用阿里云镜像，失败会自动回退清华镜像。

    REM 先试阿里云镜像
    %PY% -m pip install -r requirements.txt -i http://mirrors.aliyun.com/pypi/simple --trusted-host mirrors.aliyun.com --timeout 60
    if errorlevel 1 (
        echo  [tm1-suite] 阿里云镜像失败，回退清华镜像重试...
        %PY% -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout 60
    )

    REM 依赖装完后，再以可编辑模式安装本包
    %PY% -m pip install -e . -i http://mirrors.aliyun.com/pypi/simple --trusted-host mirrors.aliyun.com --timeout 60
    if errorlevel 1 (
        %PY% -m pip install -e . -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout 60
    )

    REM 最终校验: 关键依赖是否真的装上了
    %PY% -c "import fastapi, uvicorn, duckdb, TM1py, jinja2, typer, pydantic" >nul 2>nul
    if errorlevel 1 (
        echo.
        echo  [错误] 依赖安装失败。常见原因:
        echo   1. 网络无法访问镜像站 (公司内网或防火墙限制)
        echo   2. 代理设置问题 (如有代理，请先关闭或配置好)
        echo   3. 磁盘空间不足或 Python 版本过低 (需 3.9+)
        echo.
        echo  手动排查方式:
        echo   a. 打开命令行，进入本目录后运行:
        echo      %PY% -m pip install -r requirements.txt
        echo   b. 查看报错原文 (例如超时或 403 或找不到包)，对症处理
        echo   c. 也可改用官方源: pip install -r requirements.txt -i https://pypi.org/simple
        echo.
        pause
        exit /b 1
    )
)

REM ---- 3. 若无本地数据，自动生成演示数据 ----
if not exist "data\db\tm1_suite.duckdb" (
    echo.
    echo  [tm1-suite] 未检测到本地数据，正在生成演示数据 (无需连 TM1) ...
    set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
    %PY% -m tm1_suite.seed_demo
    echo  [tm1-suite] 演示数据已就绪，可先体验完整功能。
    echo  [tm1-suite] 之后可配置 .env 连接真实 TM1，运行 tm1-suite ingest 拉取真实数据。
)

REM ---- 4. 启动 Web UI (自动开浏览器) ----
echo.
echo  [tm1-suite] 正在启动，浏览器将自动打开 http://localhost:8000
echo  [tm1-suite] 关闭本窗口即停止服务。
echo.

start "" http://localhost:8000

REM 设置 PYTHONPATH 指向 src，然后启动
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
%PY% -m tm1_suite.cli web

pause
