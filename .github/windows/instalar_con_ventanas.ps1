# Instala como una persona: abre el instalador con doble clic (sin /S), pulsa Siguiente, Instalar y Terminar
# con la casilla "Abrir ahora" marcada, captura cada pantalla y comprueba que el programa se abre al final.
param(
  [Parameter(Mandatory)][string]$Instalador,
  [string]$Salida = "$env:RUNNER_TEMP\resultados",
  [string]$Nombre = 'ventanas',
  [pscredential]$Credencial,        # para instalar como otra persona usuaria
  [hashtable]$Entorno
)
$ErrorActionPreference = 'Continue'
New-Item -ItemType Directory -Force $Salida | Out-Null
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, System.Windows.Forms, System.Drawing
$A = [System.Windows.Automation.AutomationElement]
$fallos = 0
function Fallo($t) { Write-Host "::error::$Nombre - $t"; $script:fallos++ }
function Captura($n) {
  try {
    $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
    $bmp.Save((Join-Path $Salida "$n.png")); $g.Dispose(); $bmp.Dispose()
  } catch { Write-Host "No se pudo capturar: $_" }
}
function Textos($ventana) {
  # Solo los hijos directos: los botones, los títulos de la página y el texto de un cuadro de mensaje. Recorrer
  # todos los descendientes incluiría la lista de miles de archivos extraídos y bloquearía la prueba.
  $hijos = $ventana.FindAll([System.Windows.Automation.TreeScope]::Children, [System.Windows.Automation.Condition]::TrueCondition)
  ($hijos | ForEach-Object { $_.Current.Name } | Where-Object { $_ } | Select-Object -Unique) -join ' | '
}

$antes = @(Get-Process -Name pythonw -ErrorAction SilentlyContinue | ForEach-Object Id)
$inicio = @{ FilePath = (Resolve-Path $Instalador).Path; PassThru = $true }
if ($Credencial) { $inicio.Credential = $Credencial; $inicio.LoadUserProfile = $true; $inicio.WorkingDirectory = Split-Path $inicio.FilePath }
if ($Entorno) { $inicio.Environment = $Entorno }
$p = Start-Process @inicio
Write-Host "Instalador abierto con interfaz: PID $($p.Id)"
$pagina = 0
$limite = (Get-Date).AddMinutes(6)
$ultimo = ''
while (-not $p.HasExited -and (Get-Date) -lt $limite) {
  Start-Sleep -Milliseconds 800
  $cond = New-Object System.Windows.Automation.PropertyCondition($A::ProcessIdProperty, $p.Id)
  $ventanas = $A::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children, $cond)
  foreach ($v in $ventanas) {
    $boton = $v.FindFirst([System.Windows.Automation.TreeScope]::Children,
      (New-Object System.Windows.Automation.PropertyCondition($A::AutomationIdProperty, '1')))
    if (-not $boton) {   # un cuadro de mensaje: su botón no siempre tiene el identificador 1
      $boton = $v.FindFirst([System.Windows.Automation.TreeScope]::Children,
        (New-Object System.Windows.Automation.PropertyCondition($A::ControlTypeProperty, [System.Windows.Automation.ControlType]::Button)))
    }
    if (-not $boton -or -not $boton.Current.IsEnabled) { continue }
    $texto = Textos $v
    if ($texto -eq $ultimo) { continue }     # la misma pantalla todavía no avanzó
    $pagina++
    Write-Host "$(Get-Date -Format HH:mm:ss) Pantalla $pagina [$($v.Current.Name)] botón '$($boton.Current.Name)': $texto"
    Captura ("$Nombre-{0:D2}" -f $pagina)
    if ($v.Current.ClassName -eq '#32770' -and $texto -match 'No se pudo|fall|Hay una instancia|no pudo|datos dentro|Ya hay un instalador') {
      Fallo "El instalador mostró un aviso de error: $texto"
    }
    $ultimo = $texto
    try { $boton.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke() }
    catch { Write-Host "No se pudo pulsar: $_" }
    break
  }
}
if (-not $p.HasExited) { Captura "$Nombre-colgado"; Fallo 'El instalador no terminó en 6 minutos'; Stop-Process -Id $p.Id -Force }
else { Write-Host "Instalador terminado con código $($p.ExitCode) tras $pagina pantallas"; if ($p.ExitCode -ne 0) { Fallo "Código de salida $($p.ExitCode)" } }
if ($pagina -lt 3) { Fallo "Solo se vieron $pagina pantallas (se esperaban bienvenida, carpeta y final)" }

# La casilla "Abrir Agencia de Empleos ahora" del final debe abrir el programa
$ventana = $null
$limite = (Get-Date).AddSeconds(60)
while ((Get-Date) -lt $limite -and -not $ventana) {
  Start-Sleep -Milliseconds 500
  $ventana = Get-Process -Name pythonw -ErrorAction SilentlyContinue |
    Where-Object { $antes -notcontains $_.Id -and $_.MainWindowTitle -like '*Agencia de Empleos*' } | Select-Object -First 1
}
if (-not $ventana) { Captura "$Nombre-sin-programa"; Fallo 'El programa no se abrió al pulsar Terminar' }
else {
  Start-Sleep -Seconds 6
  Captura "$Nombre-programa-abierto"
  Write-Host "Programa abierto desde el final del instalador: PID $($ventana.Id)"
  [void]$ventana.CloseMainWindow()
  if (-not $ventana.WaitForExit(30000)) { Captura "$Nombre-no-cierra"; Fallo 'El programa no se cerró con la X'; Stop-Process -Id $ventana.Id -Force }
}
if ($fallos) { exit 1 } else { Write-Host "OK: $Nombre"; exit 0 }
