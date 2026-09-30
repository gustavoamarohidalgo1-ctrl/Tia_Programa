# Abre el programa como lo haría la persona usuaria (acceso directo o EXE), espera su ventana, toma una captura,
# lo cierra con la X (WM_CLOSE) y revisa errores.log. Devuelve código 0 solo si todo salió bien.
param(
  [Parameter(Mandatory)][string]$Archivo,          # .lnk, .exe o python(w).exe
  [string]$Argumentos = "",
  [string]$Carpeta = "",
  [Parameter(Mandatory)][string]$Proceso,          # pythonw, python o Agencia
  [Parameter(Mandatory)][string]$Datos,            # carpeta donde el programa deja agencia.db y errores.log
  [Parameter(Mandatory)][string]$Nombre,           # nombre de la captura
  [string]$Salida = "$env:RUNNER_TEMP\resultados",
  [int]$Espera = 90
)
$ErrorActionPreference = 'Continue'
New-Item -ItemType Directory -Force $Salida | Out-Null
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$fallos = 0
function Fallo($t) { Write-Host "::error::$Nombre - $t"; $script:fallos++ }
function Captura($n) {
  try {
    $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
    $bmp.Save((Join-Path $Salida "$n.png"))
    $g.Dispose(); $bmp.Dispose()
  } catch { Write-Host "No se pudo capturar la pantalla: $_" }
}

$errores = Join-Path $Datos 'errores.log'
if (Test-Path $errores) { Remove-Item $errores -Force }
$registroArranque = Join-Path $Datos 'arranque.log'
if (Test-Path $registroArranque) { Remove-Item $registroArranque -Force }
$antes = @(Get-Process -Name $Proceso -ErrorAction SilentlyContinue | ForEach-Object Id)
$stdout = Join-Path $Salida "$Nombre-stdout.txt"
$stderr = Join-Path $Salida "$Nombre-stderr.txt"
$inicio = @{ FilePath = $Archivo; PassThru = $true }
if ($Argumentos) { $inicio.ArgumentList = $Argumentos }
if ($Carpeta) { $inicio.WorkingDirectory = $Carpeta }
if ($Archivo -like '*.exe') { $inicio.RedirectStandardOutput = $stdout; $inicio.RedirectStandardError = $stderr }
Write-Host "Abriendo: $Archivo $Argumentos"
$lanzado = Start-Process @inicio

# La ventana principal del programa: la del proceso nuevo con el título de la agencia.
$ventana = $null
$limite = (Get-Date).AddSeconds($Espera)
while ((Get-Date) -lt $limite) {
  $ventana = Get-Process -Name $Proceso -ErrorAction SilentlyContinue |
    Where-Object { $antes -notcontains $_.Id -and $_.MainWindowTitle -like '*Agencia de Empleos*' } | Select-Object -First 1
  if ($ventana) { break }
  $nuevos = @(Get-Process -Name $Proceso -ErrorAction SilentlyContinue | Where-Object { $antes -notcontains $_.Id })
  if (-not $nuevos -and $lanzado -and $lanzado.HasExited -and ((Get-Date) -gt $lanzado.StartTime.AddSeconds(5))) { break }
  Start-Sleep -Milliseconds 500
}
if (-not $ventana) {
  Captura "$Nombre-sin-ventana"
  Fallo "No apareció la ventana 'Agencia de Empleos' en $Espera s."
  Get-Process | Where-Object MainWindowTitle | Format-Table Id, ProcessName, MainWindowTitle -AutoSize | Out-String | Write-Host
} else {
  Write-Host "Ventana abierta: PID $($ventana.Id) '$($ventana.MainWindowTitle)' en $([int]((Get-Date) - $ventana.StartTime).TotalSeconds) s"
  Start-Sleep -Seconds 8     # dejar que termine la copia inicial y los avisos diferidos
  Captura $Nombre
  $ventana.Refresh()
  if ($ventana.HasExited) { Fallo "El programa se cerró solo después de abrir." }
  else {
    # Si quedó un cuadro de aviso encima, la ventana principal cambia: registrar los títulos visibles.
    Get-Process -Id $ventana.Id | Format-Table Id, ProcessName, MainWindowTitle, Responding -AutoSize | Out-String | Write-Host
    if (-not $ventana.Responding) { Fallo "La ventana no responde." }
    [void]$ventana.CloseMainWindow()
    if (-not $ventana.WaitForExit(30000)) {
      Captura "$Nombre-no-cierra"
      Fallo "La ventana no se cerró con la X en 30 s."
      Stop-Process -Id $ventana.Id -Force -ErrorAction SilentlyContinue
    } else { Write-Host "Cerrado con la X correctamente." }
  }
}
# Cualquier resto del proceso (p. ej. si la ventana nunca apareció)
Get-Process -Name $Proceso -ErrorAction SilentlyContinue | Where-Object { $antes -notcontains $_.Id } |
  ForEach-Object { Write-Host "Terminando PID $($_.Id)"; Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }

foreach ($f in $stdout, $stderr) {
  if ((Test-Path $f) -and (Get-Item $f).Length) { Write-Host "--- $(Split-Path $f -Leaf) ---"; Get-Content $f -Raw | Write-Host }
}
if (Test-Path $errores) {
  Fallo "errores.log tiene contenido:"
  Get-Content $errores -Raw | Write-Host
  Copy-Item $errores (Join-Path $Salida "$Nombre-errores.log")
}
if ((Test-Path $registroArranque) -and (Select-String -Path $registroArranque -Pattern 'Traceback|Error|Fatal' -Quiet)) {
  Fallo "arranque.log registra un error:"
  Get-Content $registroArranque -Raw | Write-Host
  Copy-Item $registroArranque (Join-Path $Salida "$Nombre-arranque.log")
}
if (-not (Test-Path (Join-Path $Datos 'agencia.db'))) { Fallo "No se creó agencia.db en $Datos" }
if ($fallos) { exit 1 } else { Write-Host "OK: $Nombre"; exit 0 }
