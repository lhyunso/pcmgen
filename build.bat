@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

echo ==================================================
echo   PCM Channel Config Generator - Windows Build
echo   (c) 2025 Danam Systems
echo ==================================================
echo.

REM ── Try to find Python ──
set "PYTHON="

REM 1) py launcher (comes with Python installer)
where py >nul 2>&1
if not errorlevel 1 (
    set "PYTHON=py -3"
    goto :found
)

REM 2) python command
where python >nul 2>&1
if not errorlevel 1 (
    python --version 2>&1 | findstr /i "Python 3" >nul
    if not errorlevel 1 (
        set "PYTHON=python"
        goto :found
    )
)

REM 3) python3 command
where python3 >nul 2>&1
if not errorlevel 1 (
    set "PYTHON=python3"
    goto :found
)

REM 4) Common install paths
for %%P in (
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python39\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
    "C:\Python310\python.exe"
    "C:\Python39\python.exe"
) do (
    if exist %%P (
        set "PYTHON=%%~P"
        goto :found
    )
)

REM ── Python not found ──
echo [ERROR] Python 3.9+ 를 찾을 수 없습니다.
echo.
echo   설치 방법:
echo     1. https://www.python.org/downloads/ 에서 다운로드
echo     2. 설치 시 "Add Python to PATH" 체크 필수!
echo     3. 설치 후 이 파일을 다시 실행하세요.
echo.
pause
exit /b 1

:found
echo [OK] Python: %PYTHON%
%PYTHON% --version
echo.

REM ── Install pip if needed ──
%PYTHON% -m pip --version >nul 2>&1
if errorlevel 1 (
    echo [INFO] pip 설치 중...
    %PYTHON% -m ensurepip --upgrade
)

REM ── Run build ──
echo [BUILD] 빌드를 시작합니다...
echo.
%PYTHON% build.py
if errorlevel 1 (
    echo.
    echo ==================================================
    echo   BUILD FAILED - 오류 발생
    echo ==================================================
    echo.
    pause
    exit /b 1
)

echo.
echo ==================================================
echo   BUILD SUCCESS
echo   결과: dist\PCM_Generator.exe
echo   이 파일을 복사하여 배포하세요.
echo ==================================================
echo.
pause
