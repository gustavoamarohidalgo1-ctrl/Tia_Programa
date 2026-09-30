# Instala y abre el programa como otra persona usuaria de Windows cuyo nombre lleva tildes, eñe y espacio
# (C:\Users\José Peña), para comprobar rutas con caracteres especiales en AppData, Documentos y Tcl/Tk.
param(
  [Parameter(Mandatory)][string]$Instalador,
  [string]$Salida = "$env:RUNNER_TEMP\resultados",
  [string]$Usuario = "Jos$([char]0x00E9) Pe$([char]0x00F1)a"
)
$ErrorActionPreference = 'Continue'
New-Item -ItemType Directory -Force $Salida | Out-Null
$fallos = 0
function Fallo($t) { Write-Host "::error::usuario-con-tildes - $t"; $script:fallos++ }
function Paso($t) { Write-Host ""; Write-Host "==================== $t ====================" }

Paso "Crear la cuenta '$Usuario'"
$clave = ConvertTo-SecureString "Prueba-Agencia-$(Get-Random -Minimum 100000 -Maximum 999999)!a" -AsPlainText -Force
New-LocalUser -Name $Usuario -Password $clave -PasswordNeverExpires -AccountNeverExpires | Out-Null
Add-LocalGroupMember -Group 'Users' -Member $Usuario -ErrorAction SilentlyContinue
$cred = [pscredential]::new("$env:COMPUTERNAME\$Usuario", $clave)
$comun = 'C:\prueba-agencia'
New-Item -ItemType Directory -Force $comun | Out-Null
& icacls $comun /grant '*S-1-1-0:(OI)(CI)F' | Out-Null
Copy-Item (Resolve-Path $Instalador).Path "$comun\instalador.exe" -Force
Copy-Item "$PSScriptRoot\arranque.py", "$PSScriptRoot\humo.py" $comun -Force

function Como([string]$archivo, [string[]]$argumentos, [string]$carpeta, [string]$nombre, [int]$minutos = 5) {
  $o = "$comun\$nombre-salida.txt"; $e = "$comun\$nombre-errores.txt"
  $p = Start-Process -FilePath $archivo -ArgumentList $argumentos -Credential $cred -LoadUserProfile -WorkingDirectory $carpeta `
                     -RedirectStandardOutput $o -RedirectStandardError $e -PassThru
  if (-not $p.WaitForExit($minutos * 60000)) { Stop-Process -Id $p.Id -Force; Fallo "$nombre no terminó en $minutos min" }
  foreach ($f in $o, $e) { if ((Test-Path $f) -and (Get-Item $f).Length) { Get-Content $f -Raw -Encoding utf8 | Write-Host; Copy-Item $f $Salida } }
  Write-Host "$nombre -> código $($p.ExitCode)"
  return $p.ExitCode
}

Paso 'Instalar en silencio como esa persona'
$codigo = Como "$comun\instalador.exe" @('/S') $comun 'instalar'
if ($codigo -ne 0) { Fallo "El instalador terminó con código $codigo" }
$sid = (Get-LocalUser -Name $Usuario).SID.Value
$perfil = (Get-CimInstance Win32_UserProfile | Where-Object SID -eq $sid).LocalPath
Write-Host "Perfil: $perfil"
if (-not $perfil) { Fallo 'No se creó el perfil de la persona usuaria'; exit 1 }
$inst = Join-Path $perfil 'AppData\Local\Programs\Agencia de Empleos'
$datos = Join-Path $perfil 'AppData\Local\Agencia de Empleos'
$acceso = Join-Path $perfil 'AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Agencia de Empleos\Agencia de Empleos.lnk'
foreach ($f in "$inst\runtime\pythonw.exe", "$inst\app\agencia.py", $acceso) { if (-not (Test-Path $f)) { Fallo "Falta $f" } }
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($acceso)
Write-Host "Acceso directo: $($s.TargetPath) $($s.Arguments)"
$partes = [regex]::Matches($s.Arguments, '"([^"]*)"|(\S+)') | ForEach-Object { if ($_.Groups[1].Success) { $_.Groups[1].Value } else { $_.Groups[2].Value } }
if ($partes.Count -ne 3 -or $partes[1] -ne '--datos' -or $partes[2] -ne $datos) { Fallo "Argumentos inesperados: $($partes -join ' ; ')" }

Paso 'Abrir con pythonw.exe (como el acceso directo) y cerrar con la X'
$argumentos = @("`"$comun\arranque.py`"", "`"$comun\arranque-pythonw.json`"", "`"$($partes[0])`"", '--datos', "`"$($partes[2])`"")
$codigo = Como "$inst\runtime\pythonw.exe" $argumentos "$inst\app" 'arranque-pythonw'
if (Test-Path "$comun\arranque-pythonw.json") { Get-Content "$comun\arranque-pythonw.json" -Raw -Encoding utf8 | Write-Host; Copy-Item "$comun\arranque-pythonw.json" $Salida }
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
Write-Host 'OK: instalación y uso con una cuenta con tildes, eñe y espacio.'
exit 0
