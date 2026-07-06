@echo off
REM Build AutoClicker.exe locally on Windows.
REM Requires Python 3.9+ installed and on PATH.

pip install pyinstaller || exit /b 1
pyinstaller --onefile --noconsole --name AutoClicker autoclicker.py || exit /b 1

echo.
echo Done! The exe is at dist\AutoClicker.exe
pause
