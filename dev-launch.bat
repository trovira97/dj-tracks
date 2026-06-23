@echo off
REM ===========================================================================
REM  DJ Tracks - developer launcher
REM  Runs main.py with a visible console window for tracebacks and live logs.
REM  End users should run the packaged "DJ Tracks.exe" instead — this script
REM  is for source-mode development only.
REM ===========================================================================
setlocal
cd /d "%~dp0"

REM Wipe stale bytecode caches before launch (avoids stale-import surprises).
for /d /r "%~dp0" %%d in (__pycache__) do (
    if exist "%%d" rd /s /q "%%d" 2>nul
)

REM Locate a Python interpreter portably:
REM   1) "py -3" (Windows launcher, recommended)
REM   2) "python" on PATH
REM   3) DJ_TRACKS_PYTHON env var (manual override)
set "PYEXE="
if defined DJ_TRACKS_PYTHON (
    set "PYEXE=%DJ_TRACKS_PYTHON%"
) else (
    where py >nul 2>&1 && set "PYEXE=py -3"
    if "%PYEXE%"=="" (
        where python >nul 2>&1 && set "PYEXE=python"
    )
)
if "%PYEXE%"=="" (
    echo [DJ Tracks] No Python 3 interpreter found on PATH.
    echo   Install Python 3.10+ from https://www.python.org/downloads/
    echo   or set DJ_TRACKS_PYTHON to your interpreter path.
    pause
    exit /b 1
)

REM -B = don't write .pyc  /  -u = unbuffered stdout/stderr
%PYEXE% -B -u main.py
pause
