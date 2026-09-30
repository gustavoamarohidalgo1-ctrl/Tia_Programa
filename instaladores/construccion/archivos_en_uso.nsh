; Protecciones antes de tocar archivos de una instalación: una sola instalación a la vez, programa cerrado,
; datos fuera de las carpetas del programa y cambio de versión que se puede deshacer.
; (Este archivo se lee sin marca UTF-8: los textos que ve la persona van sin tildes.)
!include "LogicLib.nsh"
!include "WinVer.nsh"

Var CerrojoInstalador
Var RuntimeAnterior
Var AppAnterior
Var DesinstaladorAnterior
Var Extrayendo
Var Origen
Var Destino
Var Movido
Var EnUso

!define ANTERIOR "$INSTDIR\_version_anterior"   ; la versión instalada, apartada mientras se escribe la nueva
!define FALLIDA "$INSTDIR\_version_fallida"      ; restos de una extracción que no terminó

!macro CERROJO_INSTALADOR PREFIJO
Function ${PREFIJO}.onInit
  ; Sin plugins antes de la primera ventana: nada se extrae a TEMP ni se carga hasta que se ve el asistente.
  !if "${PREFIJO}" == ""
  ; Un instalador de 32 bits en Windows de 64 bits ve PROCESSOR_ARCHITEW6432 (AMD64 o ARM64).
  ReadEnvStr $0 PROCESSOR_ARCHITEW6432
  ReadEnvStr $1 PROCESSOR_ARCHITECTURE
  ${If} $0 == ""
  ${AndIf} $1 == "x86"
    MessageBox MB_OK|MB_ICONSTOP "Este instalador es para Windows de 64 bits y este equipo tiene Windows de 32 bits.$\r$\n$\r$\nNo se modifico nada." /SD IDOK
    SetErrorLevel 5
    Abort
  ${EndIf}
  ${IfNot} ${AtLeastWin8.1}
    MessageBox MB_OK|MB_ICONSTOP "${NOMBRE} necesita Windows 10 u 11 (o Windows 8.1). Este equipo tiene una version anterior de Windows.$\r$\n$\r$\nNo se modifico nada." /SD IDOK
    SetErrorLevel 5
    Abort
  ${EndIf}
  !endif
  ; Cerrojo sin plugins: FileOpen comparte el archivo solo para lectura; otro instalador o desinstalador no
  ; puede abrirlo para escribir mientras este siga abierto. Windows lo suelta al cerrarse el proceso.
  ClearErrors
  FileOpen $CerrojoInstalador "$TEMP\Instalador.${NOMBRE}.lock" a
  ${If} ${Errors}
    MessageBox MB_OK|MB_ICONEXCLAMATION "Ya hay un instalador o desinstalador de ${NOMBRE} abierto. Cierrelo antes de continuar." /SD IDOK
    SetErrorLevel 2
    Abort
  ${EndIf}
FunctionEnd
!macroend

!insertmacro CERROJO_INSTALADOR ""
!insertmacro CERROJO_INSTALADOR "un"

!macro MOVER_CON_REINTENTOS PREFIJO
; Mueve $Origen a $Destino. El antivirus o el indexador de Windows abren los archivos unos instantes y en ese
; momento Windows rechaza el cambio de nombre: se reintenta durante unos 20 segundos. $Movido = 1 si se logro.
Function ${PREFIJO}MoverConReintentos
  Push $R8
  StrCpy $Movido 0
  StrCpy $R8 0
  reintentar:
    ClearErrors
    Rename "$Origen" "$Destino"
    IfErrors 0 movido
    IntOp $R8 $R8 + 1
    IntCmp $R8 80 terminar 0 terminar
    Sleep 250
    Goto reintentar
  movido:
    StrCpy $Movido 1
  terminar:
  Pop $R8
FunctionEnd
!macroend

!insertmacro MOVER_CON_REINTENTOS ""

!macro ARCHIVOS_EN_USO PREFIJO
; Si el programa esta abierto, Windows no deja abrir para escritura su pythonw.exe, python.exe ni python312.dll
; (estan cargados en memoria). Se prueba abrirlos sin cambiar nada. No se usa Restart Manager: los antivirus
; asocian esa API con programas daninos y podian bloquear el instalador sin mostrar nada.
Function ${PREFIJO}ProbarArchivo
  IfFileExists "$Origen" 0 fin
  ClearErrors
  FileOpen $R7 "$Origen" a
  IfErrors ocupado
  FileClose $R7
  Goto fin
  ocupado:
    StrCpy $EnUso 1
  fin:
FunctionEnd

Function ${PREFIJO}ComprobarArchivosEnUso
  Push $R6
  Push $R7
  Push $Origen
  StrCpy $R6 0
  intentar:
    StrCpy $EnUso 0
    StrCpy $Origen "$INSTDIR\runtime\pythonw.exe"
    Call ${PREFIJO}ProbarArchivo
    StrCpy $Origen "$INSTDIR\runtime\python.exe"
    Call ${PREFIJO}ProbarArchivo
    StrCpy $Origen "$INSTDIR\runtime\python312.dll"
    Call ${PREFIJO}ProbarArchivo
    StrCmp $EnUso 0 libre
    ; El antivirus tambien puede tenerlos abiertos un instante: se reintenta unos segundos.
    IntOp $R6 $R6 + 1
    IntCmp $R6 8 abierto 0 abierto
    Sleep 500
    Goto intentar
  abierto:
    Pop $Origen
    Pop $R7
    Pop $R6
    MessageBox MB_OK|MB_ICONEXCLAMATION "${NOMBRE} esta abierto. Guarde su trabajo, cierre el programa y vuelva a abrir este archivo.$\r$\n$\r$\nNo se modificaron el programa ni sus datos." /SD IDOK
    SetErrorLevel 2
    Abort
  libre:
  Pop $Origen
  Pop $R7
  Pop $R6
FunctionEnd
!macroend

!insertmacro ARCHIVOS_EN_USO ""
!insertmacro ARCHIVOS_EN_USO "un."

!macro DATOS_HEREDADOS PREFIJO
Function ${PREFIJO}ComprobarDatosHeredados
  IfFileExists "$INSTDIR\app\agencia.db" datos_dentro
  IfFileExists "$INSTDIR\runtime\agencia.db" datos_dentro
  IfFileExists "$INSTDIR\app\contratos\*.*" datos_dentro
  IfFileExists "$INSTDIR\runtime\contratos\*.*" datos_dentro
  IfFileExists "$INSTDIR\app\respaldos\*.*" datos_dentro
  IfFileExists "$INSTDIR\runtime\respaldos\*.*" datos_dentro
  IfFileExists "$INSTDIR\app\configuracion.json" datos_dentro
  IfFileExists "$INSTDIR\runtime\configuracion.json" datos_dentro
  IfFileExists "$INSTDIR\app\borradores.json" datos_dentro
  IfFileExists "$INSTDIR\runtime\borradores.json" datos_dentro
  IfFileExists "$INSTDIR\app\errores.log" datos_dentro
  IfFileExists "$INSTDIR\runtime\errores.log" datos_dentro
  Return
  datos_dentro:
    MessageBox MB_OK|MB_ICONEXCLAMATION "Esta instalacion contiene datos dentro de app o runtime (base, contratos, respaldos o archivos personales). No se reemplazaron ni borraron.$\r$\n$\r$\nCopie esa carpeta a un lugar seguro, abra el programa desde ella para hacer un respaldo y restaurelo en la instalacion nueva:$\r$\n$INSTDIR" /SD IDOK
    SetErrorLevel 4
    Abort
FunctionEnd
!macroend

!insertmacro DATOS_HEREDADOS ""
!insertmacro DATOS_HEREDADOS "un."

; Devuelve a su lugar la version apartada en ${ANTERIOR}: primero aparta lo nuevo que haya quedado a medias.
; $0 = 1 si todo quedo como antes.
Function RestaurarVersionAnterior
  StrCpy $0 1
  SetOutPath "$INSTDIR"
  RMDir /r "${FALLIDA}"
  CreateDirectory "${FALLIDA}"
  ${If} $RuntimeAnterior == 1
    ${If} ${FileExists} "$INSTDIR\runtime\*.*"
      StrCpy $Origen "$INSTDIR\runtime"
      StrCpy $Destino "${FALLIDA}\runtime"
      Call MoverConReintentos
    ${EndIf}
    StrCpy $Origen "${ANTERIOR}\runtime"
    StrCpy $Destino "$INSTDIR\runtime"
    Call MoverConReintentos
    ${If} $Movido != 1
      StrCpy $0 0
    ${EndIf}
  ${EndIf}
  ${If} $AppAnterior == 1
    ${If} ${FileExists} "$INSTDIR\app\*.*"
      StrCpy $Origen "$INSTDIR\app"
      StrCpy $Destino "${FALLIDA}\app"
      Call MoverConReintentos
    ${EndIf}
    StrCpy $Origen "${ANTERIOR}\app"
    StrCpy $Destino "$INSTDIR\app"
    Call MoverConReintentos
    ${If} $Movido != 1
      StrCpy $0 0
    ${EndIf}
  ${EndIf}
  ${If} $DesinstaladorAnterior == 1
    Delete "$INSTDIR\Desinstalar.exe"
    StrCpy $Origen "${ANTERIOR}\Desinstalar.exe"
    StrCpy $Destino "$INSTDIR\Desinstalar.exe"
    Call MoverConReintentos
  ${EndIf}
  RMDir /r "${FALLIDA}"
  ${If} $0 == 1
    RMDir /r "${ANTERIOR}"
  ${EndIf}
FunctionEnd

; Una actualizacion anterior interrumpida (corte de luz, equipo apagado...) puede haber dejado la version previa
; apartada. Si falta la pieza en su lugar se devuelve; lo que sobre se limpia. Tambien limpia las carpetas
; temporales nsXXXX.tmp que dejaba la version 1.7.1.
Function RecuperarInstalacionInterrumpida
  SetOutPath "$INSTDIR"
  ${If} ${FileExists} "${ANTERIOR}\runtime\*.*"
  ${AndIfNot} ${FileExists} "$INSTDIR\runtime\pythonw.exe"
    RMDir /r "$INSTDIR\runtime"
    StrCpy $Origen "${ANTERIOR}\runtime"
    StrCpy $Destino "$INSTDIR\runtime"
    Call MoverConReintentos
  ${EndIf}
  ${If} ${FileExists} "${ANTERIOR}\app\*.*"
  ${AndIfNot} ${FileExists} "$INSTDIR\app\agencia.py"
    RMDir /r "$INSTDIR\app"
    StrCpy $Origen "${ANTERIOR}\app"
    StrCpy $Destino "$INSTDIR\app"
    Call MoverConReintentos
  ${EndIf}
  RMDir /r "${ANTERIOR}"
  RMDir /r "${FALLIDA}"
  FindFirst $R0 $R1 "$INSTDIR\ns*.tmp"
  ${DoWhile} $R1 != ""
    ${If} ${FileExists} "$INSTDIR\$R1\*.*"
      ${If} ${FileExists} "$INSTDIR\$R1\runtime-anterior\*.*"
      ${AndIfNot} ${FileExists} "$INSTDIR\runtime\pythonw.exe"
        RMDir /r "$INSTDIR\runtime"
        StrCpy $Origen "$INSTDIR\$R1\runtime-anterior"
        StrCpy $Destino "$INSTDIR\runtime"
        Call MoverConReintentos
      ${EndIf}
      ${If} ${FileExists} "$INSTDIR\$R1\app-anterior\*.*"
      ${AndIfNot} ${FileExists} "$INSTDIR\app\agencia.py"
        RMDir /r "$INSTDIR\app"
        StrCpy $Origen "$INSTDIR\$R1\app-anterior"
        StrCpy $Destino "$INSTDIR\app"
        Call MoverConReintentos
      ${EndIf}
      RMDir /r "$INSTDIR\$R1"
    ${EndIf}
    FindNext $R0 $R1
  ${Loop}
  FindClose $R0
FunctionEnd

Function .onInstFailed
  ; La instalacion se detuvo mientras escribia la version nueva: volver a dejar la anterior como estaba.
  ${If} $Extrayendo == 1
    Call RestaurarVersionAnterior
  ${EndIf}
FunctionEnd
