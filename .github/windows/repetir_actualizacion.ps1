# Instala en un equipo limpio y actualiza encima varias veces seguidas (como quien baja la versión nueva),
# abriendo el programa entre cada vez. Con el antivirus activo, cualquier fallo intermitente sale aquí.
param(
  [Parameter(Mandatory)][string]$Instalador,
  [int]$Veces = 6,
  [string]$Salida = "$env:RUNNER_TEMP\resultados"
)
$ErrorActionPreference = 'Continue'
New-Item -ItemType Directory -Force $Salida | Out-Null
$Instalador = (Resolve-Path $Instalador).Path
$Instdir = Join-Path $env:LOCALAPPDATA 'Programs\Agencia de Empleos'
$Datos = Join-Path $env:LOCALAPPDATA 'Agencia de Empleos'
$Acceso = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Agencia de Empleos\Agencia de Empleos.lnk'
$fallos = 0
$resultados = @()
for ($vez = 1; $vez -le $Veces; $vez++) {
  if ($vez -eq 1) {
    & "$Instdir\Desinstalar.exe" /S "_?=$Instdir" 2>$null
    Remove-Item -Recurse -Force $Instdir, $Datos -ErrorAction SilentlyContinue
  }
  # Copia nueva del instalador cada vez: un archivo recién descargado es lo que el antivirus analiza a fondo.
  $copia = Join-Path $env:RUNNER_TEMP "instalador-$vez.exe"
  Copy-Item $Instalador $copia -Force
  $inicio = Get-Date
  $p = Start-Process -FilePath $copia -ArgumentList '/S' -Wait -PassThru
  $segundos = [int]((Get-Date) - $inicio).TotalSeconds
  $restos = @(Get-ChildItem $Instdir -Directory -Force -ErrorAction SilentlyContinue | Where-Object Name -notin 'runtime', 'app' | ForEach-Object Name)
  $completo = (Test-Path "$Instdir\runtime\pythonw.exe") -and (Test-Path "$Instdir\app\agencia.py") -and (Test-Path "$Instdir\Desinstalar.exe")
  $linea = "Vez $vez ($(if ($vez -eq 1) { 'instalación' } else { 'actualización' })): código $($p.ExitCode), $segundos s, completa=$completo, restos=[$($restos -join ',')]"
  Write-Host $linea
  $resultados += $linea
  if ($p.ExitCode -ne 0 -or -not $completo) { Write-Host "::error::$linea"; $fallos++ }
  if ($restos) { Write-Host "::warning::Quedaron carpetas temporales: $($restos -join ', ')" }
  if ($completo) {
    & "$PSScriptRoot\abrir_programa.ps1" -Archivo $Acceso -Proceso pythonw -Datos $Datos -Nombre "repetir-$vez" -Salida $Salida -Espera 120 | Out-Host
    if ($LASTEXITCODE -ne 0) { Write-Host "::error::Vez ${vez}: el programa no abrió bien"; $fallos++ }
  }
}
$eventos = Get-MpThreatDetection -ErrorAction SilentlyContinue
if ($eventos) { Write-Host '::warning::Detecciones del antivirus:'; $eventos | Format-List | Out-String | Write-Host }
$resultados | Set-Content (Join-Path $Salida 'repetir-actualizacion.txt') -Encoding utf8
Write-Host "Fallos: $fallos de $Veces"
if ($fallos) { exit 1 }
exit 0
