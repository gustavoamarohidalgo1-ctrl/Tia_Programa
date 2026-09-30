; Instalador de Windows (64 bits) de la Agencia de Empleos.  Lo compila crear_instalador_windows.sh (NSIS).
; Se instala solo para el usuario actual (no pide permisos de administrador) e incluye su propio Python.
; Los datos de la agencia viven aparte, en %LOCALAPPDATA%\Agencia de Empleos: actualizar o desinstalar
; el programa no los borra (el desinstalador pregunta y, por defecto, los conserva).

Unicode true
SetCompressor /SOLID lzma
ManifestSupportedOS all    ; que Windows 8.1, 10 y 11 se reconozcan por su versión real
ManifestDPIAware true      ; texto nítido en pantallas con escala 125 % o 150 %

!define NOMBRE "Agencia de Empleos"
!define CLAVE_DESINSTALAR "Software\Microsoft\Windows\CurrentVersion\Uninstall\AgenciaDeEmpleos"
!define DATOS "$LOCALAPPDATA\${NOMBRE}"
!define COMANDO_ARGUMENTOS '"$INSTDIR\app\iniciar.pyw" --datos "${DATOS}"'

Name "${NOMBRE}"
OutFile "${SALIDA}"
RequestExecutionLevel user
InstallDir "$LOCALAPPDATA\Programs\${NOMBRE}"
InstallDirRegKey HKCU "Software\${NOMBRE}" "Carpeta"
BrandingText "${NOMBRE} ${VERSION}"

VIProductVersion "${VERSION}.0"
VIAddVersionKey /LANG=1034 "ProductName" "${NOMBRE}"
VIAddVersionKey /LANG=1034 "FileDescription" "Instalador de ${NOMBRE}"
VIAddVersionKey /LANG=1034 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=1034 "ProductVersion" "${VERSION}"
VIAddVersionKey /LANG=1034 "LegalCopyright" "${NOMBRE}"

!include "MUI2.nsh"
!include "${RAIZ}\instaladores\construccion\archivos_en_uso.nsh"
!define MUI_ICON "${ICONO}"
!define MUI_UNICON "${ICONO}"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "Instalar ${NOMBRE}"
!define MUI_WELCOMEPAGE_TEXT "Este asistente instalará ${NOMBRE} en su computadora.$\r$\n$\r$\nNo necesita instalar nada más: el programa trae todo lo que usa.$\r$\n$\r$\nSus datos (clientes, trabajadoras, contratos) se guardan aparte y no se pierden al actualizar o desinstalar.$\r$\n$\r$\nHaga clic en Siguiente para continuar."
!define MUI_FINISHPAGE_RUN ""
!define MUI_FINISHPAGE_RUN_FUNCTION AbrirPrograma
!define MUI_FINISHPAGE_RUN_TEXT "Abrir ${NOMBRE} ahora"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Spanish"

Function AbrirPrograma
  SetOutPath "$INSTDIR\app"
  Exec '"$INSTDIR\runtime\pythonw.exe" ${COMANDO_ARGUMENTOS}'
FunctionEnd

Section "Instalar"
  Call ComprobarArchivosEnUso
  Call ComprobarDatosHeredados
  StrCpy $RuntimeAnterior 0
  StrCpy $AppAnterior 0
  StrCpy $DesinstaladorAnterior 0
  StrCpy $RuntimePublicado 0
  StrCpy $AppPublicado 0
  StrCpy $DesinstaladorPublicado 0
  ClearErrors
  CreateDirectory "$INSTDIR"
  GetTempFileName $Actualizacion "$INSTDIR"
  IfErrors fallo_preparacion
  Delete "$Actualizacion"
  CreateDirectory "$Actualizacion"
  SetOutPath "$Actualizacion\runtime"
  File /r "${RUNTIME}\*"
  IfErrors fallo_preparacion
  SetOutPath "$Actualizacion\app"
  File /r "${APLICACION}\*"
  IfErrors fallo_preparacion
  WriteUninstaller "$Actualizacion\Desinstalar.exe"
  IfErrors fallo_preparacion
  SetOutPath "$INSTDIR"
  Call ComprobarArchivosEnUso
  Call ComprobarDatosHeredados

  ; Mantener la instalación anterior hasta publicar las tres piezas completas.
  IfFileExists "$INSTDIR\runtime\*.*" 0 mover_app
    ClearErrors
    Rename "$INSTDIR\runtime" "$Actualizacion\runtime-anterior"
    IfErrors recuperar_anterior
    StrCpy $RuntimeAnterior 1
  mover_app:
  IfFileExists "$INSTDIR\app\*.*" 0 mover_desinstalador
    ClearErrors
    Rename "$INSTDIR\app" "$Actualizacion\app-anterior"
    IfErrors recuperar_anterior
    StrCpy $AppAnterior 1
  mover_desinstalador:
  IfFileExists "$INSTDIR\Desinstalar.exe" 0 publicar_runtime
    ClearErrors
    Rename "$INSTDIR\Desinstalar.exe" "$Actualizacion\Desinstalar-anterior.exe"
    IfErrors recuperar_anterior
    StrCpy $DesinstaladorAnterior 1
  publicar_runtime:
  ClearErrors
  Rename "$Actualizacion\runtime" "$INSTDIR\runtime"
  IfErrors recuperar_anterior
  StrCpy $RuntimePublicado 1
  Rename "$Actualizacion\app" "$INSTDIR\app"
  IfErrors recuperar_anterior
  StrCpy $AppPublicado 1
  Rename "$Actualizacion\Desinstalar.exe" "$INSTDIR\Desinstalar.exe"
  IfErrors recuperar_anterior
  StrCpy $DesinstaladorPublicado 1

  CreateDirectory "${DATOS}"
  SetOutPath "$INSTDIR\app"
  CreateDirectory "$SMPROGRAMS\${NOMBRE}"
  CreateShortcut "$SMPROGRAMS\${NOMBRE}\${NOMBRE}.lnk" "$INSTDIR\runtime\pythonw.exe" '${COMANDO_ARGUMENTOS}' "$INSTDIR\app\icono.ico" 0
  CreateShortcut "$SMPROGRAMS\${NOMBRE}\Datos de la agencia.lnk" "${DATOS}"
  CreateShortcut "$SMPROGRAMS\${NOMBRE}\Desinstalar.lnk" "$INSTDIR\Desinstalar.exe"
  CreateShortcut "$DESKTOP\${NOMBRE}.lnk" "$INSTDIR\runtime\pythonw.exe" '${COMANDO_ARGUMENTOS}' "$INSTDIR\app\icono.ico" 0

  WriteRegStr HKCU "Software\${NOMBRE}" "Carpeta" "$INSTDIR"
  WriteRegStr HKCU "${CLAVE_DESINSTALAR}" "DisplayName" "${NOMBRE}"
  WriteRegStr HKCU "${CLAVE_DESINSTALAR}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${CLAVE_DESINSTALAR}" "Publisher" "${NOMBRE}"
  WriteRegStr HKCU "${CLAVE_DESINSTALAR}" "DisplayIcon" "$INSTDIR\app\icono.ico"
  WriteRegStr HKCU "${CLAVE_DESINSTALAR}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${CLAVE_DESINSTALAR}" "UninstallString" '"$INSTDIR\Desinstalar.exe"'
  WriteRegDWORD HKCU "${CLAVE_DESINSTALAR}" "NoModify" 1
  WriteRegDWORD HKCU "${CLAVE_DESINSTALAR}" "NoRepair" 1
  Goto instalacion_terminada

  recuperar_anterior:
    SetOutPath "$INSTDIR"
    ClearErrors
    StrCmp $RuntimePublicado 1 0 +2
      Rename "$INSTDIR\runtime" "$Actualizacion\runtime"
    StrCmp $AppPublicado 1 0 +2
      Rename "$INSTDIR\app" "$Actualizacion\app"
    StrCmp $DesinstaladorPublicado 1 0 +2
      Rename "$INSTDIR\Desinstalar.exe" "$Actualizacion\Desinstalar.exe"
    StrCmp $RuntimeAnterior 1 0 +2
      Rename "$Actualizacion\runtime-anterior" "$INSTDIR\runtime"
    StrCmp $AppAnterior 1 0 +2
      Rename "$Actualizacion\app-anterior" "$INSTDIR\app"
    StrCmp $DesinstaladorAnterior 1 0 +2
      Rename "$Actualizacion\Desinstalar-anterior.exe" "$INSTDIR\Desinstalar.exe"
    IfErrors recuperacion_incompleta
    MessageBox MB_OK|MB_ICONSTOP "No se pudo actualizar ${NOMBRE}. La instalacion anterior se recupero y sus datos se conservaron." /SD IDOK
    RMDir /r "$Actualizacion"
    SetErrorLevel 3
    Abort
  recuperacion_incompleta:
    MessageBox MB_OK|MB_ICONSTOP "La actualizacion fallo y Windows no permitio recuperar todos los archivos. Sus datos permanecen aparte.$\r$\n$\r$\nSe conserva la instalacion anterior en:$\r$\n$Actualizacion" /SD IDOK
    SetErrorLevel 3
    Abort
  fallo_preparacion:
    SetOutPath "$INSTDIR"
    StrCmp $Actualizacion "" +2
      RMDir /r "$Actualizacion"
    MessageBox MB_OK|MB_ICONSTOP "No se pudieron preparar los archivos nuevos. La instalacion anterior y sus datos se conservaron." /SD IDOK
    SetErrorLevel 3
    Abort
  instalacion_terminada:
    SetOutPath "$INSTDIR"
    RMDir /r "$Actualizacion"
SectionEnd

Section "Uninstall"
  Call un.ComprobarArchivosEnUso
  Call un.ComprobarDatosHeredados
  MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON2 "¿Desea borrar también los DATOS de la agencia (clientes, trabajadoras, contratos y respaldos)?$\r$\n$\r$\nEsta acción NO se puede deshacer.$\r$\n$\r$\nSi solo quiere reinstalar o actualizar el programa, elija No." /SD IDNO IDNO conservar_datos
    Call un.ComprobarArchivosEnUso
    RMDir /r "${DATOS}"
  conservar_datos:
  Call un.ComprobarArchivosEnUso

  ; solo lo que instaló este programa; nunca se borra una carpeta entera que el usuario haya elegido
  RMDir /r "$INSTDIR\runtime"
  RMDir /r "$INSTDIR\app"
  Delete "$INSTDIR\Desinstalar.exe"
  RMDir "$INSTDIR"

  Delete "$SMPROGRAMS\${NOMBRE}\${NOMBRE}.lnk"
  Delete "$SMPROGRAMS\${NOMBRE}\Datos de la agencia.lnk"
  Delete "$SMPROGRAMS\${NOMBRE}\Desinstalar.lnk"
  RMDir "$SMPROGRAMS\${NOMBRE}"
  Delete "$DESKTOP\${NOMBRE}.lnk"
  DeleteRegKey HKCU "${CLAVE_DESINSTALAR}"
  DeleteRegKey HKCU "Software\${NOMBRE}"
SectionEnd
