@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run Build-Windows.bat once to create the build environment first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" install_dependencies.py
if errorlevel 1 goto failed
".venv\Scripts\python.exe" release_tools.py configure
if errorlevel 1 goto failed
echo.
echo Next, rebuild the installer and commit the source with update-config.json.
echo The private key stays outside the source folder and is not in the app.
pause
exit /b 0
:failed
echo Update configuration failed. Read the error above.
pause
exit /b 1
