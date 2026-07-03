@echo off
rem ============================================================
rem  Forensic Stock Viz - one-click launcher for Windows
rem  First run creates a local .venv and installs dependencies.
rem  Double-click to open the GUI, or run from a terminal:
rem      run_windows.bat AAPL --csv
rem ============================================================
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    set "PYTHON=py -3"
) else (
    where python >nul 2>nul || (
        echo Python 3.10+ was not found. Install it from https://www.python.org/downloads/
        echo and tick "Add python.exe to PATH" during setup.
        pause
        exit /b 1
    )
    set "PYTHON=python"
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    %PYTHON% -m venv .venv || (echo Failed to create .venv & pause & exit /b 1)
)

call ".venv\Scripts\activate.bat"
python -m pip install --quiet --disable-pip-version-check -r requirements.txt || (
    echo Dependency installation failed. Check your internet connection.
    pause
    exit /b 1
)

python app.py %*
if errorlevel 1 pause
endlocal
