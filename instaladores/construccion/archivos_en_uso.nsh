; Protecciones nativas antes de tocar archivos de una instalación.
; Restart Manager: https://learn.microsoft.com/windows/win32/api/restartmanager/nf-restartmanager-rmgetlist
; Sólo consulta procesos; nunca los cierra ni programa borrados tras reiniciar.
; (Este archivo se lee sin marca UTF-8: los textos que ve la persona van sin tildes.)
!include "LogicLib.nsh"
!include "x64.nsh"
!include "WinVer.nsh"

Var CerrojoInstalador
Var RuntimeAnterior
Var AppAnterior
Var DesinstaladorAnterior
Var Extrayendo
Var Origen
Var Destino
Var Movido

!define ANTERIOR "$INSTDIR\_version_anterior"   ; la versión instalada, apartada mientras se escribe la nueva
!define FALLIDA "$INSTDIR\_version_fallida"      ; restos de una extracción que no terminó

!macro CERROJO_INSTALADOR PREFIJO
Function ${PREFIJO}.onInit
  !if "${PREFIJO}" == ""
  ; El Python incluido es de 64 bits y necesita Windows 8.1 o posterior: avisar claro en vez de instalar algo
  ; que despues no abre. Windows 11 en ARM ejecuta programas x64, asi que tambien se admite.
  ${IfNot} ${RunningX64}
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
  ; Evita que dos actualizadores/desinstaladores de la misma marca publiquen a la vez.
  System::Call 'kernel32::CreateMutexW(p 0, i 0, w "Local\Instalador.${NOMBRE}") p .r0 ?e'
  Pop $1
  StrCpy $CerrojoInstalador $0
  StrCmp $0 0 bloqueo_error
  StrCmp $1 183 bloqueo_ocupado
  Return
  bloqueo_ocupado:
    MessageBox MB_OK|MB_ICONEXCLAMATION "Ya hay un instalador o desinstalador de ${NOMBRE} abierto. Cierrelo antes de continuar." /SD IDOK
    SetErrorLevel 2
    Abort
  bloqueo_error:
    MessageBox MB_OK|MB_ICONSTOP "No se pudo comprobar otra instalacion en curso. No se modificaron los archivos." /SD IDOK
    SetErrorLevel 2
    Abort
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
Function ${PREFIJO}ComprobarArchivosEnUso
  System::Store "s"
  StrCpy $R9 0
  IfFileExists "$INSTDIR\runtime\pythonw.exe" comprobar
  IfFileExists "$INSTDIR\runtime\python.exe" comprobar
  IfFileExists "$INSTDIR\runtime\python312.dll" comprobar finalizar
  comprobar:
    StrCpy $R9 2
    System::Call 'rstrtmgr::RmStartSession(*i .r0, i 0, w .r1) i .r5'
    StrCmp $5 0 0 finalizar
    System::Call '*(&w${NSIS_MAX_STRLEN} "$INSTDIR\runtime\pythonw.exe") p .r1'
    System::Call '*(&w${NSIS_MAX_STRLEN} "$INSTDIR\runtime\python.exe") p .r2'
    System::Call '*(&w${NSIS_MAX_STRLEN} "$INSTDIR\runtime\python312.dll") p .r3'
    System::Call '*(p r1, p r2, p r3) p .r4'
    StrCmp $1 0 liberar
    StrCmp $2 0 liberar
    StrCmp $3 0 liberar
    StrCmp $4 0 liberar
    System::Call 'rstrtmgr::RmRegisterResources(i r0, i 3, p r4, i 0, p 0, i 0, p 0) i .r5'
    StrCmp $5 0 0 liberar
    ; Array nulo y capacidad cero: 234 indica procesos; 0 y cantidad cero indica libre.
    System::Call 'rstrtmgr::RmGetList(i r0, *i .r6, *i 0, p 0, *i .r8) i .r5'
    StrCmp $5 234 ocupado
    StrCmp $5 0 0 liberar
    StrCmp $6 0 0 ocupado
    StrCpy $R9 0
    Goto liberar
  ocupado:
    StrCpy $R9 1
  liberar:
    System::Free $4
    System::Free $3
    System::Free $2
    System::Free $1
    System::Call 'rstrtmgr::RmEndSession(i r0)'
  finalizar:
    Push $R9
    System::Store "l"
    Pop $0
    StrCmp $0 0 libre
    StrCmp $0 1 0 no_comprobado
    MessageBox MB_OK|MB_ICONEXCLAMATION "Hay una instancia de ${NOMBRE} usando los archivos de esta instalacion. Guarde su trabajo y cierrela antes de actualizar o desinstalar.$\r$\n$\r$\nNo se modificaron el programa ni sus datos." /SD IDOK
    SetErrorLevel 2
    Abort
  no_comprobado:
    !if "${PREFIJO}" == ""
    ; Al instalar, un fallo de Restart Manager no bloquea: si el programa estuviera abierto, Windows no deja
    ; apartar su carpeta y la instalacion se detiene sin tocar nada (ver la seccion Instalar).
    DetailPrint "No se pudo consultar Restart Manager; se continua con la proteccion al mover carpetas."
    Goto libre
    !else
    MessageBox MB_OK|MB_ICONSTOP "Windows no pudo comprobar si los archivos de ${NOMBRE} estan en uso. Cierre el programa y vuelva a intentar.$\r$\n$\r$\nNo se modificaron el programa ni sus datos." /SD IDOK
    SetErrorLevel 2
    Abort
    !endif
  libre:
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
