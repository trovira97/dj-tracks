@echo off
cd /d "%~dp0"
echo =============================================
echo DIAGNOSTICO DJ TRACKS
echo =============================================
echo Carpeta actual: %CD%
echo.
echo Primera linea de ui\gui.py:
"C:\Users\thiba\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -c "f=open('ui/gui.py',encoding='utf-8');print(f.readline().strip());f.close()"
echo.
echo Linea 5 de ui\gui.py (debe decir '4 temas visuales'):
"C:\Users\thiba\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -c "lines=open('ui/gui.py',encoding='utf-8').readlines();print(lines[4].strip())"
echo.
echo Existe history_manager.py:
if exist "utils\history_manager.py" (echo SI) else (echo NO - FALTA ESTE ARCHIVO)
echo.
echo =============================================
pause
