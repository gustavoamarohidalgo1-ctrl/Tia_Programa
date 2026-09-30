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
; -E y -s: el Python incluido ignora variables PYTHON* y paquetes de usuario que otros programas hayan dejado.
; (No usar -I: quitaría la carpeta de iniciar.pyw de sys.path.)
!define COMANDO_ARGUMENTOS '-E -s "$INSTDIR\app\iniciar.pyw" --datos "${DATOS}"'

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

!include "Win\COM.nsh"
!include "Win\Propkey.nsh"
!define AUMID "ServicioExclusivo.AgenciaDeEmpleos"   ; el mismo que fija agencia.main() para su ventana

; Pone al acceso directo $R0 la identidad de la ventana del programa (AppUserModelID). Así, al anclar el programa
; abierto a la barra de tareas, Windows ancla este acceso (con iniciar.pyw y --datos) y no un pythonw.exe suelto
; que no abriría nada, y la ventana se agrupa con el ícono anclado. Si algo falla, el acceso queda como estaba.
Function PonerIdentidadAlAcceso
  System::Store "s"
  !insertmacro ComHlpr_CreateInProcInstance ${CLSID_ShellLink} ${IID_IShellLink} r0 ""
  ${If} $0 P<> 0
    ${IUnknown::QueryInterface} $0 '("${IID_IPersistFile}",.r1)'
    ${If} $1 P<> 0
      ${IPersistFile::Load} $1 '("$R0",${STGM_READWRITE}).r2'
      ${If} $2 = 0
        ${IUnknown::QueryInterface} $0 '("${IID_IPropertyStore}",.r3)'
        ${If} $3 P<> 0
          System::Call '*(&w128 "${AUMID}")p.r4'
          System::Call '*${SYSSTRUCT_PROPERTYKEY}(${PKEY_AppUserModel_ID})p.r5'
          System::Call '*(&i2 ${VT_LPWSTR}, &i6 0, p r4, &i4 0)p.r6'   ; PROPVARIANT de 16 bytes (instalador de 32 bits)
          ${IPropertyStore::SetValue} $3 '($5,$6).r2'
          ${If} $2 = 0
            ${IPropertyStore::Commit} $3 '.r2'
          ${EndIf}
          System::Free $6
          System::Free $5
          System::Free $4
          ${IUnknown::Release} $3 ""
          ${If} $2 = 0
            ${IPersistFile::Save} $1 '("$R0",1).r2'
          ${EndIf}
        ${EndIf}
      ${EndIf}
      ${IUnknown::Release} $1 ""
    ${EndIf}
    ${IUnknown::Release} $0 ""
  ${EndIf}
  System::Store "l"
FunctionEnd

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
  StrCpy $Extrayendo 0
  SetOutPath "$INSTDIR"
  Call RecuperarInstalacionInterrumpida

  ; 1) Apartar la versión instalada. Son archivos que no se acaban de escribir, así que el antivirus rara vez
  ;    los retiene; aun así se reintenta. La versión nueva NO se mueve después de escribirla: se extrae
  ;    directamente en su lugar (mover archivos recién escritos es lo que el antivirus suele impedir).
  CreateDirectory "${ANTERIOR}"
  ${If} ${FileExists} "$INSTDIR\runtime\*.*"
    StrCpy $Origen "$INSTDIR\runtime"
    StrCpy $Destino "${ANTERIOR}\runtime"
    Call MoverConReintentos
    StrCmp $Movido 1 0 no_se_pudo_apartar
    StrCpy $RuntimeAnterior 1
  ${EndIf}
  ${If} ${FileExists} "$INSTDIR\app\*.*"
    StrCpy $Origen "$INSTDIR\app"
    StrCpy $Destino "${ANTERIOR}\app"
    Call MoverConReintentos
    StrCmp $Movido 1 0 no_se_pudo_apartar
    StrCpy $AppAnterior 1
  ${EndIf}
  ${If} ${FileExists} "$INSTDIR\Desinstalar.exe"
    StrCpy $Origen "$INSTDIR\Desinstalar.exe"
    StrCpy $Destino "${ANTERIOR}\Desinstalar.exe"
    Call MoverConReintentos
    StrCpy $DesinstaladorAnterior $Movido
  ${EndIf}

  ; 2) Escribir la versión nueva en su lugar. Si algo falla aquí, .onInstFailed o el bloque de abajo
  ;    devuelven la versión anterior.
  StrCpy $Extrayendo 1
  SetOutPath "$INSTDIR\runtime"
  File /r "${RUNTIME}\*"
  SetOutPath "$INSTDIR\app"
  File /r "${APLICACION}\*"
  SetOutPath "$INSTDIR"
  ${IfNot} ${FileExists} "$INSTDIR\runtime\pythonw.exe"
  ${OrIfNot} ${FileExists} "$INSTDIR\runtime\python312.dll"
  ${OrIfNot} ${FileExists} "$INSTDIR\runtime\DLLs\_tkinter.pyd"
  ${OrIfNot} ${FileExists} "$INSTDIR\app\agencia.py"
  ${OrIfNot} ${FileExists} "$INSTDIR\app\iniciar.pyw"
    Goto extraccion_incompleta
  ${EndIf}
  StrCpy $Extrayendo 0

  ; 3) Desinstalador: si Windows no deja escribirlo, se conserva el anterior y la instalación sigue.
  ClearErrors
  WriteUninstaller "$INSTDIR\Desinstalar.exe"
  ${If} ${Errors}
    DetailPrint "No se pudo escribir el desinstalador nuevo; se conserva el anterior."
    ${If} $DesinstaladorAnterior == 1
      CopyFiles /SILENT "${ANTERIOR}\Desinstalar.exe" "$INSTDIR\Desinstalar.exe"
    ${EndIf}
  ${EndIf}

  CreateDirectory "${DATOS}"
  SetOutPath "$INSTDIR\app"
  CreateDirectory "$SMPROGRAMS\${NOMBRE}"
  CreateShortcut "$SMPROGRAMS\${NOMBRE}\${NOMBRE}.lnk" "$INSTDIR\runtime\pythonw.exe" '${COMANDO_ARGUMENTOS}' "$INSTDIR\app\icono.ico" 0
  CreateShortcut "$SMPROGRAMS\${NOMBRE}\Datos de la agencia.lnk" "${DATOS}"
  CreateShortcut "$SMPROGRAMS\${NOMBRE}\Desinstalar.lnk" "$INSTDIR\Desinstalar.exe"
  CreateShortcut "$DESKTOP\${NOMBRE}.lnk" "$INSTDIR\runtime\pythonw.exe" '${COMANDO_ARGUMENTOS}' "$INSTDIR\app\icono.ico" 0
  StrCpy $R0 "$SMPROGRAMS\${NOMBRE}\${NOMBRE}.lnk"
  Call PonerIdentidadAlAcceso
  StrCpy $R0 "$DESKTOP\${NOMBRE}.lnk"
  Call PonerIdentidadAlAcceso

  WriteRegStr HKCU "Software\${NOMBRE}" "Carpeta" "$INSTDIR"
  WriteRegStr HKCU "${CLAVE_DESINSTALAR}" "DisplayName" "${NOMBRE}"
  WriteRegStr HKCU "${CLAVE_DESINSTALAR}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${CLAVE_DESINSTALAR}" "Publisher" "${NOMBRE}"
  WriteRegStr HKCU "${CLAVE_DESINSTALAR}" "DisplayIcon" "$INSTDIR\app\icono.ico"
  WriteRegStr HKCU "${CLAVE_DESINSTALAR}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${CLAVE_DESINSTALAR}" "UninstallString" '"$INSTDIR\Desinstalar.exe"'
  WriteRegDWORD HKCU "${CLAVE_DESINSTALAR}" "NoModify" 1
  WriteRegDWORD HKCU "${CLAVE_DESINSTALAR}" "NoRepair" 1
  SetOutPath "$INSTDIR"
  RMDir /r "${ANTERIOR}"     ; si algo queda retenido, la próxima instalación lo limpia
  Goto instalacion_terminada

  no_se_pudo_apartar:
    ; Nada nuevo se escribió todavía: devolver lo que alcanzó a moverse.
    StrCpy $Extrayendo 0
    Call RestaurarVersionAnterior
    MessageBox MB_OK|MB_ICONEXCLAMATION "Windows no permitió reemplazar los archivos de la versión instalada de ${NOMBRE}. Puede que el programa siga abierto o que el antivirus los esté revisando.$\r$\n$\r$\nCierre el programa, espere un minuto y vuelva a abrir el instalador. No se modificó nada y sus datos están a salvo." /SD IDOK
    SetErrorLevel 3
    Abort
  extraccion_incompleta:
    Call RestaurarVersionAnterior
    StrCpy $Extrayendo 0
    MessageBox MB_OK|MB_ICONSTOP "No se pudieron escribir todos los archivos de ${NOMBRE} (¿disco lleno o antivirus?). Se dejó la instalación como estaba y sus datos están a salvo.$\r$\n$\r$\nVuelva a intentarlo en unos minutos." /SD IDOK
    SetErrorLevel 3
    Abort
  instalacion_terminada:
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
  RMDir /r "${ANTERIOR}"
  RMDir /r "${FALLIDA}"
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
