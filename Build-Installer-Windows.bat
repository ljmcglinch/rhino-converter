@echo off
setlocal
cd /d "%~dp0"
echo Building the coworker installer...
call :find_nsis
if defined NSIS_COMPILER goto compiler_ready
where winget >nul 2>&1
if errorlevel 1 goto missing_nsis
echo Installing the free NSIS installer builder on this build computer...
winget install --id NSIS.NSIS --exact --source winget --accept-package-agreements --accept-source-agreements
if errorlevel 1 goto missing_nsis
call :find_nsis
if not defined NSIS_COMPILER goto missing_nsis
:compiler_ready
call Build-Windows.bat --no-pause
if errorlevel 1 goto failed
".venv\Scripts\python.exe" installer\generate_manifest.py "dist\RhinoConverter" "build\uninstall-files.nsh"
if errorlevel 1 goto failed
set /p "APP_RELEASE="<VERSION.txt
"%NSIS_COMPILER%" "/DAPP_DIR=%CD%\dist\RhinoConverter" "/DOUT_FILE=%CD%\dist\RhinoConverter-Setup.exe" "/DUNINSTALL_MANIFEST=%CD%\build\uninstall-files.nsh" "/DAPP_VERSION=%APP_RELEASE%" installer\RhinoConverter.nsi
if errorlevel 1 goto failed
if not exist "dist\RhinoConverter-Setup.exe" goto failed
echo.
echo Done. Test dist\RhinoConverter-Setup.exe, then send that ONE file to coworkers.
echo They double-click it, click Install, and use the desktop or Start menu shortcut.
echo No Python, Rhino, terminal commands, or separate folders are needed.
if not "%~1"=="--no-pause" pause
exit /b 0

:find_nsis
set "NSIS_COMPILER="
for /f "delims=" %%I in ('where makensis.exe 2^>nul') do set "NSIS_COMPILER=%%I"
if defined NSIS_COMPILER exit /b 0
if exist "%ProgramFiles(x86)%\NSIS\makensis.exe" set "NSIS_COMPILER=%ProgramFiles(x86)%\NSIS\makensis.exe"
if defined NSIS_COMPILER exit /b 0
if exist "%ProgramFiles%\NSIS\makensis.exe" set "NSIS_COMPILER=%ProgramFiles%\NSIS\makensis.exe"
exit /b 0

:missing_nsis
echo Install NSIS 3 from https://nsis.sourceforge.io/Download and run this script again.
echo Only the build computer needs NSIS; coworkers do not.
if not "%~1"=="--no-pause" pause
exit /b 1

:failed
echo Installer build failed. Read the error above; do not share an older installer.
if not "%~1"=="--no-pause" pause
exit /b 1
