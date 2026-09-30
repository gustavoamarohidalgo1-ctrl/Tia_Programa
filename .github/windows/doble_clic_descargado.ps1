# Reproduce lo que hace la persona: el instalador llega por WhatsApp (queda marcado como descargado de Internet),
# lo abre con doble clic desde el Explorador y mira qué aparece. Registra cada ventana nueva con capturas,
# atraviesa los avisos normales de Windows («Windows protegió su PC» > Más información > Ejecutar de todas
# formas) y dice si llegó a verse la ventana del instalador. Al final revisa qué hizo el antivirus.
param(
  [Parameter(Mandatory)][string]$Instalador,
  [Parameter(Mandatory)][string]$Nombre,
  [string]$Salida = "$env:RUNNER_TEMP\resultados",
  [int]$Espera = 150
)
$ErrorActionPreference = 'Continue'
New-Item -ItemType Directory -Force $Salida | Out-Null
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, System.Windows.Forms, System.Drawing
$A = [System.Windows.Automation.AutomationElement]
$T = [System.Windows.Automation.TreeScope]
function Captura($n) {
  try {
    $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
    $bmp.Save((Join-Path $Salida "$Nombre-$n.png")); $g.Dispose(); $bmp.Dispose()
  } catch { Write-Host "captura: $_" }
}
function Pulsar($ventana, [string[]]$nombres) {
  foreach ($n in $nombres) {
    $e = $ventana.FindFirst($T::Descendants, (New-Object System.Windows.Automation.PropertyCondition($A::NameProperty, $n)))
    if ($e) {
      try { $e.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke(); return "invocado '$n'" }
      catch {
        try { $e.GetCurrentPattern([System.Windows.Automation.LegacyIAccessiblePattern]::Pattern).DoDefaultAction(); return "accion '$n'" }
        catch { return "no se pudo pulsar '$n': $_" }
      }
    }
  }
  return $null
}

# 1) El archivo tal como lo guarda WhatsApp: en Descargas y marcado como venido de Internet
$descargas = Join-Path $env:USERPROFILE 'Downloads'
New-Item -ItemType Directory -Force $descargas | Out-Null
$archivo = Join-Path $descargas "$Nombre.exe"
Copy-Item (Resolve-Path $Instalador).Path $archivo -Force
Set-Content -Path $archivo -Stream Zone.Identifier -Value "[ZoneTransfer]`r`nZoneId=3`r`nReferrerUrl=https://web.whatsapp.com/`r`nHostUrl=https://mmg.whatsapp.net/"
Write-Host "Archivo: $archivo ($((Get-Item $archivo).Length) bytes, SHA256 $((Get-FileHash $archivo).Hash))"
Get-Content -Path $archivo -Stream Zone.Identifier | Write-Host
$proceso = [IO.Path]::GetFileNameWithoutExtension($archivo)

# 2) Doble clic: el Explorador lo abre (pasan los controles de Windows para archivos descargados)
$antes = @{}
foreach ($v in $A::RootElement.FindAll($T::Children, [System.Windows.Automation.Condition]::TrueCondition)) { $antes[$v.Current.NativeWindowHandle] = 1 }
$inicio = Get-Date
Start-Process -FilePath explorer.exe -ArgumentList "`"$archivo`""
$eventos = New-Object System.Collections.Generic.List[string]
$vistas = @{}
$instalador = $false
$segundos = $null
$momentos = @(3, 15, 45)
while (((Get-Date) - $inicio).TotalSeconds -lt $Espera) {
  Start-Sleep -Milliseconds 1200
  $t = [int]((Get-Date) - $inicio).TotalSeconds
  if ($momentos -and $t -ge $momentos[0]) { Captura "t$($momentos[0])s"; $momentos = @($momentos | Select-Object -Skip 1) }
  foreach ($v in $A::RootElement.FindAll($T::Children, [System.Windows.Automation.Condition]::TrueCondition)) {
    $h = $v.Current.NativeWindowHandle
    if ($antes.ContainsKey($h)) { continue }
    $pn = try { (Get-Process -Id $v.Current.ProcessId -ErrorAction Stop).ProcessName } catch { '?' }
    $clave = "$h|$($v.Current.Name)"
    if (-not $vistas.ContainsKey($clave)) {
      $vistas[$clave] = 1
      $linea = "t=${t}s ventana nueva: '$($v.Current.Name)' clase=$($v.Current.ClassName) proceso=$pn"
      Write-Host $linea; $eventos.Add($linea)
      Captura ("ventana-{0:D2}" -f $vistas.Count)
    }
    $titulo = $v.Current.Name
    if ($pn -eq $proceso -and $titulo -like '*Agencia de Empleos*') {
      if (-not $instalador) { $instalador = $true; $segundos = $t; Write-Host "LA VENTANA DEL INSTALADOR APARECIÓ a los $t s"; Start-Sleep 2; Captura 'instalador' }
      continue
    }
    # Los avisos normales de Windows para archivos descargados: se aceptan como lo haría la persona
    $r = $null
    if ($titulo -match 'Windows protected your PC|Windows protegi' -or $pn -eq 'smartscreen') {
      $r = Pulsar $v @('More info', 'Más información', 'Mas información')
      Start-Sleep -Milliseconds 800
      $r2 = Pulsar $v @('Run anyway', 'Ejecutar de todas formas', 'Ejecutar de todos modos')
      $r = "$r / $r2"
    } elseif ($titulo -match 'Security Warning|Advertencia de seguridad') {
      $r = Pulsar $v @('Run', '&Run', 'Ejecutar', '&Ejecutar')
    }
    if ($r) { $linea = "t=${t}s en '$titulo': $r"; Write-Host $linea; $eventos.Add($linea) }
  }
  if ($instalador -and $t -gt $segundos + 4) { break }
}
if (-not $instalador) { Captura 'final'; Write-Host "NO APARECIÓ la ventana del instalador en $Espera s" }
$corriendo = @(Get-Process -Name $proceso -ErrorAction SilentlyContinue)
Write-Host "Procesos del instalador todavía abiertos: $($corriendo.Count)"
$corriendo | Stop-Process -Force -ErrorAction SilentlyContinue

# 3) Qué hizo el antivirus
$detecciones = @(Get-MpThreatDetection -ErrorAction SilentlyContinue | Where-Object { $_.InitialDetectionTime -ge $inicio.AddMinutes(-1) })
foreach ($d in $detecciones) { $linea = "DEFENDER: amenaza $($d.ThreatID) en $($d.Resources -join ', ') acción=$($d.ActionSuccess)"; Write-Host $linea; $eventos.Add($linea) }
Get-MpThreat -ErrorAction SilentlyContinue | Format-List ThreatName, SeverityID, Resources | Out-String | Write-Host
try {
  Get-WinEvent -LogName 'Microsoft-Windows-Windows Defender/Operational' -MaxEvents 40 -ErrorAction Stop |
    Where-Object { $_.TimeCreated -ge $inicio.AddMinutes(-1) -and $_.Id -in 1006,1007,1015,1116,1117,1118,1119,1121,1122,1123,1124,1125,1126,1127,1128,5007 } |
    ForEach-Object { $linea = "EVENTO DEFENDER $($_.Id): $(($_.Message -split "`n" | Select-Object -First 6) -join ' | ')"; Write-Host $linea; $eventos.Add($linea) }
} catch { Write-Host "Sin registro de Defender: $_" }
$mp = Join-Path $env:ProgramFiles 'Windows Defender\MpCmdRun.exe'
if (Test-Path $archivo) {
  $escaneo = & $mp -Scan -ScanType 3 -File $archivo -DisableRemediation 2>&1
  Write-Host "Escaneo con la nube: código $LASTEXITCODE"; $escaneo | Select-Object -Last 4 | Write-Host
} else { $eventos.Add('El archivo desapareció de Descargas (¿el antivirus lo quitó?)'); Write-Host 'El archivo desapareció de Descargas' }

$resumen = [ordered]@{ instalador = $Nombre; aparecio = $instalador; segundos = $segundos; eventos = $eventos; detecciones = $detecciones.Count }
$resumen | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $Salida "$Nombre-resumen.json") -Encoding utf8
$resumen | ConvertTo-Json -Depth 4 | Write-Host
if ($instalador) { exit 0 } else { exit 1 }
