@echo off
setlocal
cd /d "%~dp0"

:: Borrar cache de bytecode
for /d /r "%~dp0" %%d in (__pycache__) do (
    if exist "%%d" rd /s /q "%%d" 2>nul
)

:: -B = no escribir .pyc  /  -u = salida sin buffer
"C:\Users\thiba\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -B -u main.py
pause
