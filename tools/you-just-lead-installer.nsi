Unicode true
RequestExecutionLevel user
SetCompressor /SOLID lzma

!include "MUI2.nsh"

!cd ".."

!define PRODUCT_NAME "You Just Lead"
!define PRODUCT_VERSION "0.1.0"
!define PRODUCT_PUBLISHER "You Just Lead"
!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\You Just Lead"

Name "${PRODUCT_NAME} ${PRODUCT_VERSION}"
OutFile "frontend\src-tauri\target\release\bundle\nsis\You Just Lead_${PRODUCT_VERSION}_x64-setup.exe"
InstallDir "$LOCALAPPDATA\Programs\You Just Lead"
InstallDirRegKey HKCU "${UNINSTALL_KEY}" "InstallLocation"
Icon "frontend\src-tauri\icons\icon.ico"
UninstallIcon "frontend\src-tauri\icons\icon.ico"
BrandingText "You Just Lead"

VIProductVersion "0.1.0.0"
VIAddVersionKey /LANG=1033 "ProductName" "${PRODUCT_NAME}"
VIAddVersionKey /LANG=1033 "ProductVersion" "${PRODUCT_VERSION}"
VIAddVersionKey /LANG=1033 "FileVersion" "${PRODUCT_VERSION}"
VIAddVersionKey /LANG=1033 "CompanyName" "${PRODUCT_PUBLISHER}"
VIAddVersionKey /LANG=1033 "FileDescription" "Competition training Agent"
VIAddVersionKey /LANG=1033 "LegalCopyright" "Copyright (c) 2026 ${PRODUCT_PUBLISHER}"

!define MUI_ABORTWARNING
!define MUI_ICON "frontend\src-tauri\icons\icon.ico"
!define MUI_UNICON "frontend\src-tauri\icons\icon.ico"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "SimpChinese"

Function .onInit
  SetShellVarContext current
FunctionEnd

Function un.onInit
  SetShellVarContext current
FunctionEnd

Section "Install ${PRODUCT_NAME}" SEC_MAIN
  SetOutPath "$INSTDIR"
  File /oname=you-just-lead-desktop.exe "frontend\src-tauri\target\release\you-just-lead-desktop.exe"
  File /oname=competition-agent-api.exe "frontend\src-tauri\binaries\competition-agent-api-x86_64-pc-windows-msvc.exe"

  CreateDirectory "$SMPROGRAMS\You Just Lead"
  CreateShortcut "$SMPROGRAMS\You Just Lead\You Just Lead.lnk" "$INSTDIR\you-just-lead-desktop.exe"
  CreateShortcut "$DESKTOP\You Just Lead.lnk" "$INSTDIR\you-just-lead-desktop.exe"

  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayName" "${PRODUCT_NAME}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayVersion" "${PRODUCT_VERSION}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "Publisher" "${PRODUCT_PUBLISHER}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayIcon" "$INSTDIR\you-just-lead-desktop.exe"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "UninstallString" "$INSTDIR\Uninstall.exe"
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoRepair" 1
  WriteUninstaller "$INSTDIR\Uninstall.exe"
SectionEnd

Section "Uninstall"
  Delete "$DESKTOP\You Just Lead.lnk"
  Delete "$SMPROGRAMS\You Just Lead\You Just Lead.lnk"
  RMDir "$SMPROGRAMS\You Just Lead"
  Delete "$INSTDIR\competition-agent-api.exe"
  Delete "$INSTDIR\you-just-lead-desktop.exe"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "${UNINSTALL_KEY}"
SectionEnd
