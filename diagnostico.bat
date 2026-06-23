@echo off
setlocal
cd /d "%~dp0"
set "PYEXE=C:\Users\thiba\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

echo =============================================
echo   DIAGNOSTICO DJ TRACKS
echo =============================================
echo Carpeta: %CD%
echo.

echo --- Python ---
if exist "%PYEXE%" (
    "%PYEXE%" -V
) else (
    echo Python del runtime no encontrado en: %PYEXE%
)
echo.

echo --- Archivos clave ---
for %%F in (main.py ui\gui.py core\controller.py core\search_manager.py ^
            core\queue_persistence.py utils\history_manager.py ^
            downloader\audio_downloader.py providers\__init__.py ^
            __version__.py ffmpeg.exe) do (
    if exist "%%F" (echo   [OK]   %%F) else (echo   [MISS] %%F)
)
echo.

echo --- Imports ---
"%PYEXE%" -c "import sys; sys.path.insert(0,'.'); import core.controller, ui.gui, providers, downloader.audio_downloader, utils.history_manager, core.queue_persistence; print('  Todos los modulos importan correctamente')" 2>nul
if errorlevel 1 echo   [FAIL] Errores en imports — ver logs\app.log
echo.

echo --- Dependencias ---
"%PYEXE%" -c "import customtkinter,PIL,yt_dlp,spotipy,mutagen,requests,platformdirs; print('  customtkinter, PIL, yt_dlp, spotipy, mutagen, requests, platformdirs OK')" 2>nul
if errorlevel 1 echo   [FAIL] Falta alguna dependencia — ejecutar: pip install -r requirements.txt
echo.

echo --- Tests (si pytest esta instalado) ---
"%PYEXE%" -m pytest --collect-only -q tests 2>nul | findstr /R "test_"
echo.

echo --- Configuracion ---
if exist "config\settings.json" (echo   [OK]   config\settings.json) else (echo   [MISS] config\settings.json — copia config\settings.example.json)
if exist "config\history.json"  (echo   [OK]   config\history.json) else (echo   [INFO] config\history.json no existe aun ^(normal en primera ejecucion^))
if exist "config\queue.json"    (echo   [INFO] config\queue.json con tareas pendientes) else (echo   [OK]   sin tareas pendientes persistidas)
echo.

echo --- Version ---
"%PYEXE%" -c "import sys; sys.path.insert(0,'.'); from __version__ import __version__; print(f'  DJ Tracks v{__version__}')" 2>nul
echo.

echo =============================================
pause
