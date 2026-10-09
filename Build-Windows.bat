@echo off
setlocal
cd /d "%~dp0"
echo Building the portable Rhino Converter for Windows...
echo Run this once on a build computer with Python 3.12 installed.
py -3.12 --version >nul 2>&1
if errorlevel 1 (
  echo Python 3.12 was not found. Install it from https://www.python.org/downloads/windows/
  echo Office users will not need Python after the app is built.
  if not "%~1"=="--no-pause" pause
  exit /b 1
)
py -3.12 -c "import platform, sys; assert sys.maxsize > 2**32 and platform.machine().lower() in ('amd64', 'x86_64'), 'Use 64-bit x86 Python 3.12 for the Windows package'"
if errorlevel 1 goto failed
if not exist ".venv\Scripts\python.exe" py -3.12 -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" install_dependencies.py --build
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m unittest discover -s tests -v
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onedir --windowed --name RhinoConverter --icon "assets\RhinoConverter.ico" --add-data "assets;assets" --add-data "VERSION.txt;." --add-data "update-config.json;." --hidden-import mac_update --collect-all cryptography --paths vendor --collect-all OCP --collect-all rhino3dm --collect-submodules serpentine3d --copy-metadata numpy --copy-metadata cadquery-ocp-novtk --copy-metadata rhino3dm app.py
if errorlevel 1 goto failed
copy README.txt "dist\RhinoConverter\README.txt" >nul
copy THIRD-PARTY-NOTICES.txt "dist\RhinoConverter\THIRD-PARTY-NOTICES.txt" >nul
copy LICENSE.txt "dist\RhinoConverter\LICENSE.txt" >nul
copy vendor\Serpentine3D-LICENSE.txt "dist\RhinoConverter\Serpentine3D-LICENSE.txt" >nul
copy assets\RhinoConverter.ico "dist\RhinoConverter\RhinoConverter.ico" >nul
".venv\Scripts\python.exe" -c "import shutil; shutil.make_archive('dist/RhinoConverter-Windows', 'zip', 'dist', 'RhinoConverter')"
if errorlevel 1 goto failed
echo.
echo Done. Test dist\RhinoConverter\RhinoConverter.exe on this computer.
echo Send the ENTIRE dist\RhinoConverter folder or the Windows ZIP to coworkers.
echo Do not send the EXE by itself: it needs the bundled _internal folder.
if not "%~1"=="--no-pause" pause
exit /b 0
:failed
echo Build failed. Read the error above; no working Windows package is claimed.
if not "%~1"=="--no-pause" pause
exit /b 1
