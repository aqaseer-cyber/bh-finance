@echo off
rem Build a standalone ForensicStockViz.exe (no Python needed on the target PC).
rem Run this once on a Windows machine; output lands in dist\ForensicStockViz.exe
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Run run_windows.bat once first to create the environment.
    pause
    exit /b 1
)
call ".venv\Scripts\activate.bat"
python -m pip install --quiet pyinstaller || (echo pip install pyinstaller failed & pause & exit /b 1)
pyinstaller --noconfirm --onefile --windowed --name ForensicStockViz app.py
echo.
echo Done: dist\ForensicStockViz.exe
pause
endlocal
