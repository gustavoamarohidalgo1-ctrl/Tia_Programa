# Prueba completa del instalador en Windows x64: instala (con sus ventanas o en silencio), revisa archivos y
# accesos directos, abre el programa desde el acceso directo, recorre la aplicación con datos reales en la
# carpeta de datos, comprueba que la actualización se niega con el programa abierto y que funciona con el
# programa cerrado sin tocar los datos, y opcionalmente desinstala conservando los datos.
param(
  [Parameter(Mandatory)][string]$Instalador,
  [string]$Salida = "$env:RUNNER_TEMP\resultados",
  [switch]$ConVentanas,
  [switch]$SinDesinstalar
)
$ErrorActionPreference = 'Continue'
New-Item -ItemType Directory -Force $Salida | Out-Null
$aqui = $PSScriptRoot
$fallos = New-Object System.Collections.Generic.List[string]
function Fallo($t) { Write-Host "::error::$t"; $fallos.Add($t) }
function Paso($t) { Write-Host ""; Write-Host "==================== $t ====================" }
$Instalador = (Resolve-Path $Instalador).Path
$Instdir = Join-Path $env:LOCALAPPDATA 'Programs\Agencia de Empleos'
$Datos = Join-Path $env:LOCALAPPDATA 'Agencia de Empleos'
$Menu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Agencia de Empleos'
$Escritorio = [Environment]::GetFolderPath('Desktop')
$Acceso = Join-Path $Menu 'Agencia de Empleos.lnk'

function Instalar($nombre) {
  $p = Start-Process -FilePath $Instalador -ArgumentList '/S' -Wait -PassThru
  Write-Host "$nombre -> código de salida $($p.ExitCode)"
  return $p.ExitCode
}
function Arranque($nombre) {
  # El programa real (iniciar.pyw -> agencia.main) con los argumentos del acceso directo; se cierra con su X.
  $s = (New-Object -ComObject WScript.Shell).CreateShortcut($Acceso)
  $partes = [regex]::Matches($s.Arguments, '"([^"]*)"|(\S+)') | ForEach-Object { if ($_.Groups[1].Success) { $_.Groups[1].Value } else { $_.Groups[2].Value } }
  $partes = @($partes | Select-Object -Skip ([array]::FindIndex([string[]]$partes, [Predicate[string]]{ param($x) $x -like '*.pyw' })))
  $json = Join-Path $Salida "$nombre.json"
  & "$Instdir\runtime\python.exe" -E -s "$aqui\arranque.py" $json @partes 2>&1 | Out-File (Join-Path $Salida "$nombre.txt") -Encoding utf8
  $codigo = $LASTEXITCODE
  $r = Get-Content $json -Raw -Encoding utf8 | ConvertFrom-Json
  Write-Host "$nombre -> código $codigo; ventana: $($r.ventana | ConvertTo-Json -Compress); avisos: $(@($r.avisos).Count)"
  foreach ($a in @($r.avisos)) { Write-Host "   aviso $($a.tipo): $($a.titulo) - $($a.mensaje)" }
  if ($codigo -ne 0) { Fallo "$nombre falló: $(Get-Content $json -Raw -Encoding utf8)" }
  return $r
}

Paso 'Sistema'
Write-Host "Windows: $([Environment]::OSVersion.VersionString)  64 bits: $([Environment]::Is64BitOperatingSystem)"
Write-Host "Usuario: $env:USERNAME  LOCALAPPDATA: $env:LOCALAPPDATA"
Get-FileHash $Instalador -Algorithm SHA256 | Format-List | Out-String | Write-Host
(Get-Item $Instalador).VersionInfo | Format-List ProductName, ProductVersion, FileVersion | Out-String | Write-Host
Remove-Item -Recurse -Force $Instdir, $Datos, $Menu -ErrorAction SilentlyContinue

if ($ConVentanas) {
  Paso 'Instalación con ventanas, como una persona (equipo nuevo)'
  & "$aqui\instalar_con_ventanas.ps1" -Instalador $Instalador -Salida $Salida
  if ($LASTEXITCODE -ne 0) { Fallo 'La instalación con ventanas falló' }
} else {
  Paso 'Instalación silenciosa (equipo nuevo)'
  $codigo = Instalar 'Instalación'
  if ($codigo -ne 0) { Fallo "El instalador terminó con código $codigo" }
}
foreach ($f in 'runtime\python.exe', 'runtime\pythonw.exe', 'runtime\python312.dll', 'runtime\DLLs\_tkinter.pyd',
               'runtime\DLLs\tcl86t.dll', 'runtime\DLLs\tk86t.dll', 'runtime\DLLs\_sqlite3.pyd', 'runtime\tcl\tcl8.6\init.tcl',
               'runtime\tcl\tk8.6\tk.tcl', 'app\agencia.py', 'app\iniciar.pyw', 'app\logo.png', 'app\icono.ico', 'Desinstalar.exe') {
  if (-not (Test-Path (Join-Path $Instdir $f))) { Fallo "Falta $f en la instalación" }
}
Get-ChildItem $Instdir -Force | Format-Table Mode, Length, Name -AutoSize | Out-String | Write-Host
Get-ChildItem $Instdir -Directory -Force | Where-Object Name -notin 'runtime', 'app' |
  ForEach-Object { Fallo "Quedó una carpeta temporal en la instalación: $($_.Name)" }
$reg = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\AgenciaDeEmpleos' -ErrorAction SilentlyContinue
if (-not $reg) { Fallo 'No se registró en Aplicaciones instaladas' } else { Write-Host "Registrado: $($reg.DisplayName) $($reg.DisplayVersion)" }

Paso 'Python incluido'
& "$Instdir\runtime\python.exe" -c "import sys, tkinter, sqlite3, ctypes, json, html, decimal, csv, uuid, queue, webbrowser, msvcrt; print(sys.version); print('Tk', tkinter.TkVersion, 'SQLite', sqlite3.sqlite_version); r = tkinter.Tk(); print('patchlevel', r.tk.call('info', 'patchlevel')); r.destroy()"
if ($LASTEXITCODE -ne 0) { Fallo "El Python incluido no puede cargar tkinter/sqlite3 (código $LASTEXITCODE)" }

Paso 'Accesos directos'
$sh = New-Object -ComObject WScript.Shell
foreach ($lnk in @($Acceso, (Join-Path $Escritorio 'Agencia de Empleos.lnk'), (Join-Path $Menu 'Desinstalar.lnk'), (Join-Path $Menu 'Datos de la agencia.lnk'))) {
  if (Test-Path $lnk) {
    $s = $sh.CreateShortcut($lnk)
    Write-Host "$lnk`n   destino: $($s.TargetPath)`n   argumentos: $($s.Arguments)`n   carpeta: $($s.WorkingDirectory)`n   icono: $($s.IconLocation)"
    if (-not (Test-Path $s.TargetPath)) { Fallo "El acceso $lnk apunta a algo que no existe: $($s.TargetPath)" }
  } else { Fallo "No existe el acceso directo $lnk" }
}

Paso 'Abrir desde el acceso directo del menú Inicio'
& "$aqui\abrir_programa.ps1" -Archivo $Acceso -Proceso pythonw -Datos $Datos -Nombre 'acceso-menu-inicio' -Salida $Salida
if ($LASTEXITCODE -ne 0) { Fallo 'El programa no abrió o no cerró bien desde el acceso directo' }

Paso 'Arranque real con los argumentos del acceso directo (sin datos)'
$r = Arranque 'arranque-sin-datos'

Paso 'Recorrido completo sobre la carpeta de datos real (humo.py)'
& "$Instdir\runtime\python.exe" "$aqui\humo.py" "$Instdir\app" $Datos 2>&1 | Tee-Object -FilePath (Join-Path $Salida 'humo.txt') | Write-Host
if ($LASTEXITCODE -ne 0) { Fallo "humo.py falló (código $LASTEXITCODE)" }

Paso 'Abrir con datos desde el acceso directo y cerrar con la X'
& "$aqui\abrir_programa.ps1" -Archivo $Acceso -Proceso pythonw -Datos $Datos -Nombre 'con-datos' -Salida $Salida
if ($LASTEXITCODE -ne 0) { Fallo 'El arranque con datos falló' }
$r = Arranque 'arranque-con-datos'
if (@($r.avisos).Count) { Fallo "El arranque con datos mostró avisos: $($r.avisos | ConvertTo-Json -Compress)" }

Paso 'Actualizar con el programa abierto (debe negarse sin tocar nada)'
$s = $sh.CreateShortcut($Acceso)
$abierto = Start-Process -FilePath "$Instdir\runtime\pythonw.exe" -ArgumentList $s.Arguments -WorkingDirectory "$Instdir\app" -PassThru
$limite = (Get-Date).AddSeconds(60)
do { Start-Sleep -Milliseconds 500; $abierto.Refresh() } until ($abierto.MainWindowTitle -like '*Agencia*' -or $abierto.HasExited -or (Get-Date) -gt $limite)
if ($abierto.HasExited) { Fallo 'El programa se cerró antes de probar la actualización' }
$huella = (Get-FileHash "$Instdir\app\agencia.py").Hash
$trabajo = Start-Job -ScriptBlock { param($i) (Start-Process -FilePath $i -ArgumentList '/S' -Wait -PassThru).ExitCode } -ArgumentList $Instalador
if (Wait-Job $trabajo -Timeout 180) {
  $codigo = Receive-Job $trabajo
  Write-Host "Actualización con programa abierto -> código $codigo"
  if ($codigo -ne 2) { Fallo "Con el programa abierto el instalador debía negarse con código 2 y devolvió $codigo" }
} else {
  Fallo 'El instalador se quedó colgado con el programa abierto'
  Get-Process | Where-Object ProcessName -like 'Agencia-de-Empleos*' | Stop-Process -Force -ErrorAction SilentlyContinue
}
if (-not (Test-Path "$Instdir\runtime\pythonw.exe") -or (Get-FileHash "$Instdir\app\agencia.py").Hash -ne $huella) { Fallo 'La instalación cambió tras negarse a actualizar' }
$abierto.Refresh()
[void]$abierto.CloseMainWindow()
if (-not $abierto.WaitForExit(30000)) { Stop-Process -Id $abierto.Id -Force -ErrorAction SilentlyContinue; Fallo 'No se cerró el programa abierto con la X' }
Start-Sleep -Seconds 2

Paso 'Actualizar con el programa cerrado (reinstalar encima, conservando datos)'
$antesDb = (Get-FileHash (Join-Path $Datos 'agencia.db')).Hash
$codigo = Instalar 'Actualización'
if ($codigo -ne 0) { Fallo "La actualización terminó con código $codigo" }
if (-not (Test-Path (Join-Path $Datos 'agencia.db'))) { Fallo 'La actualización borró los datos' }
elseif ((Get-FileHash (Join-Path $Datos 'agencia.db')).Hash -ne $antesDb) { Fallo 'La actualización modificó agencia.db' }
Get-ChildItem $Instdir -Directory -Force | Where-Object Name -notin 'runtime', 'app' |
  ForEach-Object { Fallo "Quedó una carpeta temporal tras actualizar: $($_.Name)" }
& "$aqui\abrir_programa.ps1" -Archivo $Acceso -Proceso pythonw -Datos $Datos -Nombre 'tras-actualizar' -Salida $Salida
if ($LASTEXITCODE -ne 0) { Fallo 'El programa no abrió después de actualizar' }
$r = Arranque 'arranque-tras-actualizar'

Paso 'Antivirus de Windows (Defender) sobre el instalador y la instalación'
$mp = Join-Path $env:ProgramFiles 'Windows Defender\MpCmdRun.exe'
if (Test-Path $mp) {
  & $mp -SignatureUpdate 2>&1 | Select-Object -Last 2 | Write-Host
  foreach ($objetivo in $Instalador, $Instdir) {
    $salidaMp = & $mp -Scan -ScanType 3 -File $objetivo -DisableRemediation 2>&1
    $salidaMp | Select-Object -Last 6 | Write-Host
    if ($LASTEXITCODE -eq 2) { Fallo "Defender detectó una amenaza en $objetivo" }
    elseif ($LASTEXITCODE -ne 0) { Write-Host "Defender no pudo analizar $objetivo (código $LASTEXITCODE)" }
  }
} else { Write-Host 'Defender no está disponible en esta imagen.' }

if (-not $SinDesinstalar) {
  Paso 'Desinstalar con el programa abierto (debe negarse)'
  $abierto = Start-Process -FilePath "$Instdir\runtime\pythonw.exe" -ArgumentList $s.Arguments -WorkingDirectory "$Instdir\app" -PassThru
  $limite = (Get-Date).AddSeconds(60)
  do { Start-Sleep -Milliseconds 500; $abierto.Refresh() } until ($abierto.MainWindowTitle -like '*Agencia*' -or $abierto.HasExited -or (Get-Date) -gt $limite)
  $p = Start-Process -FilePath "$Instdir\Desinstalar.exe" -ArgumentList '/S', "_?=$Instdir" -Wait -PassThru
  Write-Host "Desinstalar con el programa abierto -> código $($p.ExitCode)"
  if ($p.ExitCode -ne 2) { Fallo "Con el programa abierto el desinstalador debía negarse con código 2 y devolvió $($p.ExitCode)" }
  if (-not (Test-Path "$Instdir\runtime\pythonw.exe")) { Fallo 'El desinstalador borró archivos con el programa abierto' }
  $abierto.Refresh()
  [void]$abierto.CloseMainWindow()
  if (-not $abierto.WaitForExit(30000)) { Stop-Process -Id $abierto.Id -Force -ErrorAction SilentlyContinue; Fallo 'No se cerró el programa abierto con la X' }
  Start-Sleep -Seconds 2

  Paso 'Desinstalar (en silencio conserva los datos)'
  $p = Start-Process -FilePath "$Instdir\Desinstalar.exe" -ArgumentList '/S', "_?=$Instdir" -Wait -PassThru
  Write-Host "Desinstalador -> código $($p.ExitCode)"
  if ($p.ExitCode -ne 0) { Fallo "El desinstalador terminó con código $($p.ExitCode)" }
  if (Test-Path "$Instdir\runtime") { Fallo 'El desinstalador dejó runtime' }
  if (Test-Path "$Instdir\app") { Fallo 'El desinstalador dejó app' }
  if (Test-Path $Acceso) { Fallo 'El desinstalador dejó el acceso del menú Inicio' }
  if (-not (Test-Path (Join-Path $Datos 'agencia.db'))) { Fallo 'El desinstalador borró los datos' }
}

Paso 'Resumen'
if ($fallos.Count) { $fallos | ForEach-Object { Write-Host "FALLO: $_" }; exit 1 }
Write-Host 'Instalador comprobado sin fallos.'
exit 0
