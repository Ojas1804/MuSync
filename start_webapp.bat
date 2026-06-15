@echo off
:: Find Git Bash and launch start_webapp.sh
set "SCRIPT=%~dp0start_webapp.sh"

:: Common Git Bash locations
set "BASH="
if exist "C:\Program Files\Git\bin\bash.exe" set "BASH=C:\Program Files\Git\bin\bash.exe"
if exist "C:\Program Files (x86)\Git\bin\bash.exe" set "BASH=C:\Program Files (x86)\Git\bin\bash.exe"

:: Fall back to bash on PATH (e.g. if Git is in PATH)
if "%BASH%"=="" (
    where bash >nul 2>&1
    if %errorlevel%==0 set "BASH=bash"
)

if "%BASH%"=="" (
    echo.
    echo  ERROR: Git Bash not found.
    echo  Install Git for Windows from https://git-scm.com/download/win
    echo  and make sure "Git Bash" is included in the installation.
    echo.
    pause
    exit /b 1
)

"%BASH%" "%SCRIPT%"
pause
