@echo off
REM ============================================================
REM  TM1 Insight - Portable Build Script
REM  Builds a portable Windows package into release\TM1 Insight\
REM
REM  Product rule: SOFTWARE and DATA are strictly separated.
REM  This script NEVER copies the real data/ directory.
REM ============================================================
setlocal enabledelayedexpansion
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo  [TM1 Insight] Portable build started.

REM ---- 1. Locate a REAL Python (reject WindowsApps stub) ----
set "PY="
if exist "D:\01_Work\01_Env\anaconda\python.exe" set "PY=D:\01_Work\01_Env\anaconda\python.exe"
if not defined PY if exist "D:\01_Work\01_Env\pyenv\data_env\python.exe" set "PY=D:\01_Work\01_Env\pyenv\data_env\python.exe"
if not defined PY (
    for /f "delims=" %%i in ('where python 2^>nul') do (
        echo %%i | findstr /i "WindowsApps" >nul
        if not errorlevel 1 (
            rem skip stub
        ) else (
            if not defined PY set "PY=%%i"
        )
    )
)
if not defined PY (
    echo  [ERROR] No usable Python found. Install Python 3.9+ and check "Add to PATH".
    pause
    exit /b 1
)
echo  [TM1 Insight] Python: %PY%

REM ---- 2. Ensure PyInstaller is installed ----
%PY% -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
    echo  [TM1 Insight] Installing PyInstaller...
    %PY% -m pip install pyinstaller -i https://mirrors.aliyun.com/pypi/simple --timeout 60
    if errorlevel 1 goto build_fail
)

REM ---- 3. Clean previous build output ----
echo  [TM1 Insight] Cleaning previous output...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "release" rmdir /s /q "release"

REM ---- 4. Run PyInstaller ----
echo  [TM1 Insight] Building executable (this may take a few minutes)...
%PY% -m PyInstaller --noconfirm --clean tm1_insight.spec
if errorlevel 1 goto build_fail

REM ---- 5. Assemble release directory ----
echo  [TM1 Insight] Assembling release package...
set "RELEASE=release\TM1 Insight"
if not exist "%RELEASE%" mkdir "%RELEASE%"

REM 5a. copy the onedir build (executable + runtime) into release
xcopy /e /i /q "dist\TM1 Insight\*" "%RELEASE%\" >nul
if errorlevel 1 goto build_fail

REM 5b. copy default config template (NOT the real .env with credentials)
if exist ".env.example" copy /y ".env.example" "%RELEASE%\.env.example" >nul

REM 5c. create an EMPTY user-data structure (no real data copied)
mkdir "%RELEASE%\data" 2>nul

REM 5d. copy user-facing README
if exist "PORTABLE_README.txt" copy /y "PORTABLE_README.txt" "%RELEASE%\README.txt" >nul

REM 5e. strip library test data (pyarrow/numpy bundled test fixtures)
REM     These are NOT TM1 Insight data, but removing them keeps the package clean.
if exist "%RELEASE%\_internal\pyarrow\tests" rmdir /s /q "%RELEASE%\_internal\pyarrow\tests"
if exist "%RELEASE%\_internal\numpy\tests" rmdir /s /q "%RELEASE%\_internal\numpy\tests"

echo.
echo  [TM1 Insight] Build complete.
echo  [TM1 Insight] Output: release\TM1 Insight\
echo  [TM1 Insight] NOTE: real data/ was NOT copied (software/data separated).
echo.
pause
exit /b 0

:build_fail
echo.
echo  [ERROR] Build failed. See messages above.
echo.
pause
exit /b 1
