@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "BUILD_PY=%~dp0.build-venv\Scripts\python.exe"
if not exist "%BUILD_PY%" (
  echo [TM1 Insight] Create an isolated build environment first:
  echo python -m venv .build-venv
  echo .build-venv\Scripts\python.exe -m pip install -r requirements-build.lock
  pause
  exit /b 1
)
"%BUILD_PY%" scripts\build_portable.py
if errorlevel 1 (
  echo [ERROR] Build failed. Previous releases were preserved.
  pause
  exit /b 1
)
echo [TM1 Insight] Build location is saved in release\latest-build.txt.
pause
