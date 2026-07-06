@echo off
REM Build AutoClicker.exe locally on Windows.
REM Requires Python 3.9+ installed and on PATH.

pip install pyinstaller numpy || exit /b 1
python build_assets.py || exit /b 1
pyinstaller --onefile --noconsole --noupx --name AutoClicker ^
  --icon assets/icon.ico --version-file version_info.txt ^
  --add-data "assets/icon.png;assets" autoclicker.py || exit /b 1

echo.
echo Done! The exe is at dist\AutoClicker.exe
pause
