"""Launcher script (used by run_windows.bat and the PyInstaller build)."""
import sys

from forensic_viz.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
