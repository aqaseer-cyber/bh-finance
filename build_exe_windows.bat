@echo off
rem Build standalone executables (no Python needed on the target PC):
rem   dist\ForensicStockViz.exe     - GUI app (no console window)
rem   dist\forensic-viz-cli.exe     - command-line version (console output)
rem Run this once on a Windows machine after run_windows.bat has set up .venv.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Run run_windows.bat once first to create the environment.
    pause
    exit /b 1
)
call ".venv\Scripts\activate.bat"
rem reproducible build: pin the exact resolved dependency tree (FIX-9)
python -m pip install --quiet -r requirements.lock || (echo pip install -r requirements.lock failed & pause & exit /b 1)
python -m pip install --quiet pyinstaller || (echo pip install pyinstaller failed & pause & exit /b 1)

pyinstaller --noconfirm --onefile --windowed --name ForensicStockViz --icon assets\app_icon.ico ^
    --add-data "assets;assets" app.py || (
    echo PyInstaller GUI build failed. & pause & exit /b 1
)
pyinstaller --noconfirm --onefile --console --name forensic-viz-cli --icon assets\app_icon.ico ^
    --add-data "assets;assets" app.py || (
    echo PyInstaller CLI build failed. & pause & exit /b 1
)
if not exist "dist\ForensicStockViz.exe" (
    echo Build finished but dist\ForensicStockViz.exe is missing. & pause & exit /b 1
)
echo.
echo Done: dist\ForensicStockViz.exe (GUI) and dist\forensic-viz-cli.exe (CLI)
pause
endlocal
