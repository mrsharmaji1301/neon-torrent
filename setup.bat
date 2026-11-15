@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    python -m venv --without-pip .venv
    if errorlevel 1 goto failed
)

python -m pip --python ".venv\Scripts\python.exe" install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" tools\make_runtime.py
if errorlevel 1 goto failed
echo.
echo Setup complete. Start NEON Torrent with run.bat.
exit /b 0

:failed
echo Setup failed. Install 64-bit Python 3.13 and try setup.bat again.
pause
exit /b 1
