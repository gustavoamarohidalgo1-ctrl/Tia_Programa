# Instala y abre el programa como otra persona usuaria de Windows (cuenta estándar, sin administrador) cuyo
# nombre puede llevar tildes, eñe y espacio (C:\Users\José Peña), para comprobar rutas con caracteres especiales
# en AppData, Documentos y Tcl/Tk, y una cuenta sin permisos de administrador.
param(
  [Parameter(Mandatory)][string]$Instalador,
  [string]$Salida = "$env:RUNNER_TEMP\resultados",
  [string]$Usuario = "Jos$([char]0x00E9) Pe$([char]0x00F1)a"
)
$ErrorActionPreference = 'Continue'
New-Item -ItemType Directory -Force $Salida | Out-Null
$fallos = 0
$etiqueta = ($Usuario -replace '[^A-Za-z0-9]', '_')
function Fallo($t) { Write-Host "::error::usuario $Usuario - $t"; $script:fallos++ }
function Paso($t) { Write-Host ""; Write-Host "==================== $t ====================" }

Paso "Crear la cuenta estándar '$Usuario'"
$clave = ConvertTo-SecureString "Prueba-Agencia-$(Get-Random -Minimum 100000 -Maximum 999999)!a" -AsPlainText -Force
New-LocalUser -Name $Usuario -Password $clave -PasswordNeverExpires -AccountNeverExpires | Out-Null
Add-LocalGroupMember -Group 'Users' -Member $Usuario -ErrorAction SilentlyContinue
$cred = [pscredential]::new("$env:COMPUTERNAME\$Usuario", $clave)
$comun = "C:\prueba-agencia-$etiqueta"
New-Item -ItemType Directory -Force $comun | Out-Null
& icacls $comun /grant '*S-1-1-0:(OI)(CI)F' | Out-Null
Copy-Item (Resolve-Path $Instalador).Path "$comun\instalador.exe" -Force
Copy-Item "$PSScriptRoot\arranque.py", "$PSScriptRoot\humo.py" $comun -Force
$script:entorno = $null

function Como([string]$archivo, [string[]]$argumentos, [string]$carpeta, [string]$nombre, [int]$minutos = 5) {
  $o = "$comun\$nombre-salida.txt"; $e = "$comun\$nombre-errores.txt"
  $opciones = @{ FilePath = $archivo; ArgumentList = $argumentos; Credential = $cred; LoadUserProfile = $true
                 WorkingDirectory = $carpeta; RedirectStandardOutput = $o; RedirectStandardError = $e; PassThru = $true }
  if ($script:entorno) { $opciones.Environment = $script:entorno }
  $p = Start-Process @opciones
  if (-not $p) { Fallo "$nombre no se pudo iniciar"; return -1 }
  if (-not $p.WaitForExit($minutos * 60000)) { Stop-Process -Id $p.Id -Force; Fallo "$nombre no terminó en $minutos min" }
  foreach ($f in $o, $e) { if ((Test-Path $f) -and (Get-Item $f).Length) { Get-Content $f -Raw -Encoding utf8 | Write-Host; Copy-Item $f "$Salida\$etiqueta-$(Split-Path $f -Leaf)" } }
  Write-Host "$nombre -> código $($p.ExitCode)"
  return $p.ExitCode
}

Paso 'Entorno que recibe un proceso de esa persona'
[void](Como "$env:WINDIR\System32\cmd.exe" @('/c', 'whoami & set') $comun 'entorno-heredado')
Paso 'Diagnóstico: instalación en silencio con el entorno heredado de la cuenta de la prueba'
$diagnostico = Como "$comun\instalador.exe" @('/S') $comun 'instalar-entorno-heredado'
Write-Host "Con el entorno heredado el instalador devolvió $diagnostico (solo informativo)"
$sid = (Get-LocalUser -Name $Usuario).SID.Value
$perfil = (Get-CimInstance Win32_UserProfile | Where-Object SID -eq $sid).LocalPath
Write-Host "Perfil: $perfil"
if (-not $perfil) { Fallo 'No se creó el perfil de la persona usuaria'; exit 1 }
# Un doble clic real recibe las carpetas de su propio perfil. Start-Process -Credential puede heredar las de la
# cuenta que lanza la prueba (a las que esta persona no tiene acceso): se fijan las propias explícitamente.
$local = Join-Path $perfil 'AppData\Local'
New-Item -ItemType Directory -Force "$local\Temp" | Out-Null
$script:entorno = @{ TEMP = "$local\Temp"; TMP = "$local\Temp"; LOCALAPPDATA = $local; APPDATA = (Join-Path $perfil 'AppData\Roaming')
                     USERPROFILE = $perfil; HOMEPATH = $perfil.Substring(2); USERNAME = $Usuario }
[void](Como "$env:WINDIR\System32\cmd.exe" @('/c', 'whoami & set') $comun 'entorno-propio')
$inst = Join-Path $local 'Programs\Agencia de Empleos'
$datos = Join-Path $local 'Agencia de Empleos'
$acceso = Join-Path $perfil 'AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Agencia de Empleos\Agencia de Empleos.lnk'
Get-ChildItem -Force $local -ErrorAction SilentlyContinue | Out-String | Write-Host
Remove-Item -Recurse -Force $inst, $datos, (Split-Path $acceso) -ErrorAction SilentlyContinue   # empezar de cero

Paso 'Instalar con ventanas como esa persona'
& "$PSScriptRoot\instalar_con_ventanas.ps1" -Instalador "$comun\instalador.exe" -Salida $Salida -Nombre "ventanas-$etiqueta" -Credencial $cred -Entorno $script:entorno
if ($LASTEXITCODE -ne 0) {
  Fallo 'La instalación con ventanas falló'
  Get-ChildItem -Force -Recurse -Depth 2 $local -ErrorAction SilentlyContinue | Where-Object FullName -notlike '*\Microsoft\*' |
    Select-Object -First 80 FullName | Out-String | Write-Host
}
foreach ($f in "$inst\runtime\pythonw.exe", "$inst\app\agencia.py", $acceso) { if (-not (Test-Path $f)) { Fallo "Falta $f" } }
if (-not (Test-Path $acceso)) { exit 1 }
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($acceso)
Write-Host "Acceso directo: $($s.TargetPath) $($s.Arguments)"
$partes = @([regex]::Matches($s.Arguments, '"([^"]*)"|(\S+)') | ForEach-Object { if ($_.Groups[1].Success) { $_.Groups[1].Value } else { $_.Groups[2].Value } })
if ($partes.Count -ne 3 -or $partes[1] -ne '--datos' -or $partes[2] -ne $datos) { Fallo "Argumentos inesperados: $($partes -join ' ; ')"; exit 1 }

Paso 'Reinstalar en silencio encima (actualización) como esa persona'
$codigo = Como "$comun\instalador.exe" @('/S') $comun 'actualizar'
if ($codigo -ne 0) { Fallo "La actualización en silencio terminó con código $codigo" }

Paso 'Abrir con pythonw.exe (como el acceso directo) y cerrar con la X'
$argumentos = @("`"$comun\arranque.py`"", "`"$comun\arranque-pythonw.json`"", "`"$($partes[0])`"", '--datos', "`"$($partes[2])`"")
$codigo = Como "$inst\runtime\pythonw.exe" $argumentos "$inst\app" 'arranque-pythonw'
if (Test-Path "$comun\arranque-pythonw.json") { Get-Content "$comun\arranque-pythonw.json" -Raw -Encoding utf8 | Write-Host; Copy-Item "$comun\arranque-pythonw.json" "$Salida\$etiqueta-arranque-pythonw.json" }
else { Fallo 'pythonw no dejó resultado (no llegó a ejecutarse el programa)' }
if ($codigo -ne 0) { Fallo "El arranque con pythonw falló (código $codigo)" }

Paso 'Recorrido completo como esa persona (humo.py)'
$codigo = Como "$inst\runtime\python.exe" @("`"$comun\humo.py`"", "`"$inst\app`"", "`"$datos`"") "$inst\app" 'humo'
if ($codigo -ne 0) { Fallo "humo.py falló (código $codigo)" }

Paso 'Segundo arranque con datos'
$argumentos[1] = "`"$comun\arranque-2.json`""
$codigo = Como "$inst\runtime\python.exe" $argumentos "$inst\app" 'arranque-2'
if ($codigo -ne 0) { Fallo "El segundo arranque falló (código $codigo)" }

Paso 'Resumen'
if ($fallos) { exit 1 }
Write-Host "OK: instalación y uso con la cuenta estándar '$Usuario'."
exit 0
