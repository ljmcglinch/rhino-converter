Unicode true
RequestExecutionLevel user
ManifestDPIAware true
SetCompressor /SOLID lzma
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"
!include "WinVer.nsh"

!ifndef APP_DIR
  !error "APP_DIR must point to the complete Windows PyInstaller app folder."
!endif
!ifndef OUT_FILE
  !error "OUT_FILE must specify the installer output path."
!endif
!ifndef UNINSTALL_MANIFEST
  !error "Generate and supply UNINSTALL_MANIFEST before compiling."
!endif
!ifndef APP_VERSION
  !error "APP_VERSION must match VERSION.txt."
!endif

!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\RhinoConverter"
Name "Rhino Converter"
OutFile "${OUT_FILE}"
InstallDir "$LOCALAPPDATA\Programs\RhinoConverter"
InstallDirRegKey HKCU "${UNINSTALL_KEY}" "InstallLocation"
BrandingText "Rhino Converter"
ShowInstDetails nevershow
ShowUninstDetails nevershow
VIProductVersion "${APP_VERSION}.0"
VIAddVersionKey "ProductName" "Rhino Converter"
VIAddVersionKey "FileDescription" "Rhino Converter Installer"
VIAddVersionKey "FileVersion" "${APP_VERSION}"
VIAddVersionKey "LegalCopyright" "Copyright 2026 Liam McGlinchey"

!define MUI_ABORTWARNING
!define MUI_ICON "..\assets\RhinoConverter.ico"
!define MUI_UNICON "..\assets\RhinoConverter.ico"
!define MUI_WELCOMEPAGE_TEXT "Install Rhino Converter on this computer.$\r$\n$\r$\nConvert Rhino files locally, without installing Rhino or Python.$\r$\n$\r$\nClose Rhino Converter before installing an update."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\RhinoConverter.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Open Rhino Converter"
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Function .onInit
  SetShellVarContext current
  ${IfNot} ${AtLeastWin10}
    MessageBox MB_OK|MB_ICONSTOP "Rhino Converter requires Windows 10 or newer."
    Abort
  ${EndIf}
  ${IfNot} ${RunningX64}
    MessageBox MB_OK|MB_ICONSTOP "This package requires 64-bit Windows."
    Abort
  ${EndIf}
  SetRegView 64
  ReadRegStr $1 HKCU "${UNINSTALL_KEY}" "InstallLocation"
  ${If} $1 != ""
    StrCpy $INSTDIR $1
  ${EndIf}
  check_running:
  FindWindow $0 "" "Rhino Converter"
  ${If} $0 != 0
    MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "Close Rhino Converter, then click Retry." IDRETRY check_running
    Abort
  ${EndIf}
FunctionEnd

Section "Rhino Converter"
  SetShellVarContext current
  SetRegView 64
  SetOutPath "$INSTDIR"
  File /r "${APP_DIR}\*"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateDirectory "$SMPROGRAMS\Rhino Converter"
  CreateShortcut "$SMPROGRAMS\Rhino Converter\Rhino Converter.lnk" "$INSTDIR\RhinoConverter.exe" "" "$INSTDIR\RhinoConverter.ico" 0
  CreateShortcut "$SMPROGRAMS\Rhino Converter\Uninstall.lnk" "$INSTDIR\Uninstall.exe"
  CreateShortcut "$DESKTOP\Rhino Converter.lnk" "$INSTDIR\RhinoConverter.exe" "" "$INSTDIR\RhinoConverter.ico" 0
  nsExec::ExecToLog '"$INSTDIR\RhinoConverter.exe" --register-shortcuts "$DESKTOP\Rhino Converter.lnk" "$SMPROGRAMS\Rhino Converter\Rhino Converter.lnk"'
  Pop $0
  ${If} $0 != 0
    SetErrorLevel 1
    Abort "Could not register the Rhino Converter taskbar shortcuts."
  ${EndIf}
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayName" "Rhino Converter"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "Publisher" "Liam McGlinchey"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayIcon" "$INSTDIR\RhinoConverter.ico"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
  WriteRegStr HKCU "${UNINSTALL_KEY}" "QuietUninstallString" '$\"$INSTDIR\Uninstall.exe$\" /S'
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoRepair" 1
SectionEnd

Function un.onInit
  SetShellVarContext current
  SetRegView 64
  check_running:
  FindWindow $0 "" "Rhino Converter"
  ${If} $0 != 0
    MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "Close Rhino Converter, then click Retry." IDRETRY check_running
    Abort
  ${EndIf}
FunctionEnd

Section "Uninstall"
  SetShellVarContext current
  ; Delete only the exact packaged files. Preserve unrelated files and exports.
  !include "${UNINSTALL_MANIFEST}"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  Delete "$DESKTOP\Rhino Converter.lnk"
  Delete "$SMPROGRAMS\Rhino Converter\Rhino Converter.lnk"
  Delete "$SMPROGRAMS\Rhino Converter\Uninstall.lnk"
  RMDir "$SMPROGRAMS\Rhino Converter"
  DeleteRegKey HKCU "${UNINSTALL_KEY}"
SectionEnd
