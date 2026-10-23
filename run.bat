@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" call setup.bat
if errorlevel 1 exit /b 1
if not exist "runtime\NeonTorrent.exe" ".venv\Scripts\python.exe" tools\make_runtime.py
if errorlevel 1 exit /b 1
rem NeonTorrent.exe is the app's own copy of pythonw (no console window), so Windows, the firewall and the
rem antivirus see it separately from python.exe. Startup errors go to %APPDATA%\NeonTorrent\error.log
start "" "runtime\NeonTorrent.exe" "src\neon_torrent.py" %*
exit /b 0
