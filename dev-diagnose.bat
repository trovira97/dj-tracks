@echo off
REM ===========================================================================
REM  DJ Tracks - developer diagnostic
REM  Quick sanity check that everything is in place to run from source.
REM  Useful when something stops working and you don't know why.
REM ===========================================================================
setlocal
cd /d "%~dp0"

REM Resolve Python (same logic as dev-launch.bat).
set "PYEXE="
if defined DJ_TRACKS_PYTHON (
    set "PYEXE=%DJ_TRACKS_PYTHON%"
) else (
    where py >nul 2>&1 && set "PYEXE=py -3"
    if "%PYEXE%"=="" (
        where python >nul 2>&1 && set "PYEXE=python"
    )
)

echo ============================================================
echo   DJ Tracks - source-mode diagnostic
echo ============================================================
echo  Working dir : %CD%
echo  Python      : %PYEXE%
echo.

echo --- Python version ---
if "%PYEXE%"=="" (
    echo   [MISSING] No Python interpreter found.
) else (
    %PYEXE% -V
)
echo.

echo --- Key files ---
for %%F in (main.py ui\gui.py core\controller.py core\search_manager.py ^
            core\queue_persistence.py utils\history_manager.py ^
            utils\donor_gate.py utils\donor_client.py ^
            downloader\audio_downloader.py providers\__init__.py ^
            metadata\beatport.py __version__.py requirements.txt ffmpeg.exe) do (
    if exist "%%F" (echo   [OK]   %%F) else (echo   [MISS] %%F)
)
echo.

if not "%PYEXE%"=="" (
    echo --- Imports ---
    %PYEXE% -c "import sys; sys.path.insert(0,'.'); import core.controller, ui.gui, providers, downloader.audio_downloader, utils.history_manager, utils.donor_gate, core.queue_persistence, metadata.beatport; print('  All modules import correctly')"
    echo.

    echo --- Tests ---
    %PYEXE% -m pytest tests -q --tb=no 2>nul | findstr /R "passed failed error"
    echo.

    echo --- App version ---
    %PYEXE% -c "from __version__ import __version__, __app_name__; print('  %s v%s' % (__app_name__, __version__))" 2>nul
)
echo.

echo ============================================================
echo  If everything above looks OK, run dev-launch.bat to start.
echo  Press any key to close this window.
echo ============================================================
pause >nul
