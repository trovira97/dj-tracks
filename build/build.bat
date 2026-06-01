@echo off
setlocal
cd /d "%~dp0\.."
set "PYEXE=C:\Users\thiba\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"

echo =====================================================
echo   DJ Tracks  -  Build pipeline
echo =====================================================
echo.

if not exist "%PYEXE%" (
    echo [ERROR] No se encuentra Python en: %PYEXE%
    echo         Edita esta linea en build\build.bat con la ruta correcta.
    pause
    exit /b 1
)

echo --- Paso 1: Instalar PyInstaller si falta ---
"%PYEXE%" -m pip install --quiet pyinstaller >nul
if errorlevel 1 (
    echo [ERROR] No se pudo instalar PyInstaller
    pause
    exit /b 1
)
echo   OK
echo.

echo --- Paso 2: Limpiar builds previos ---
if exist "dist\DJ Tracks"   rmdir /s /q "dist\DJ Tracks"
if exist "dist\installer"   rmdir /s /q "dist\installer"
if exist "build_temp"       rmdir /s /q "build_temp"
echo   OK
echo.

echo --- Paso 3: Empaquetar con PyInstaller ---
"%PYEXE%" -m PyInstaller --noconfirm --clean ^
    --distpath dist ^
    --workpath build_temp ^
    build\dj_tracks.spec
if errorlevel 1 (
    echo [ERROR] PyInstaller fallo
    pause
    exit /b 1
)
echo.
echo   .exe portable generado en:  dist\DJ Tracks\DJ Tracks.exe
echo.

echo --- Paso 4: Construir instalador con Inno Setup ---
if not exist "%ISCC%" (
    echo.
    echo [AVISO] Inno Setup no esta instalado.
    echo         Descargalo gratis en:  https://jrsoftware.org/isdl.php
    echo         Despues vuelve a ejecutar este script.
    echo.
    echo         Mientras tanto puedes distribuir la carpeta:
    echo            dist\DJ Tracks\
    echo         comprimida en ZIP — funciona como app portable.
    echo.
    pause
    exit /b 0
)
"%ISCC%" build\installer.iss
if errorlevel 1 (
    echo [ERROR] Inno Setup fallo
    pause
    exit /b 1
)
echo.

echo =====================================================
echo   LISTO
echo   Instalador:  dist\installer\DJTracks-Setup-*.exe
echo =====================================================
pause
