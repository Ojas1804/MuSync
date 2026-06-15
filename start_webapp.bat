@echo off
setlocal

set "SCRIPT_DIR=%~dp0"

:: Locate Git Bash
set "BASH="
if exist "C:\Program Files\Git\bin\bash.exe"       set "BASH=C:\Program Files\Git\bin\bash.exe"
if exist "C:\Program Files (x86)\Git\bin\bash.exe" set "BASH=C:\Program Files (x86)\Git\bin\bash.exe"
if "%BASH%"=="" (
    where bash >nul 2>&1
    if not errorlevel 1 set "BASH=bash"
)

if "%BASH%"=="" (
    echo.
    echo  ERROR: Git Bash not found.
    echo  Install from https://git-scm.com/download/win
    echo.
    pause
    exit /b 1
)

:: --login ensures Python is on PATH inside Git Bash
"%BASH%" --login "%SCRIPT_DIR%start_webapp.sh"
pause
