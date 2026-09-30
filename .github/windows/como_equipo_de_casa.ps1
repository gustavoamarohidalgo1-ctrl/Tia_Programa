# Deja la máquina de pruebas lo más parecida posible a una computadora de casa con Windows 10/11:
# antivirus con protección en tiempo real Y en la nube (bloqueo a primera vista), SmartScreen para programas
# descargados y ninguna exclusión. Las máquinas de GitHub traen todo esto apagado.
$ErrorActionPreference = 'Continue'
# Las imágenes de GitHub pueden forzar el antivirus en «modo pasivo» (no bloquea nada): se quita esa directiva.
foreach ($clave in 'HKLM:\SOFTWARE\Policies\Microsoft\Windows Advanced Threat Protection', 'HKLM:\SOFTWARE\Microsoft\Windows Advanced Threat Protection') {
  if (Test-Path $clave) { Remove-ItemProperty -Path $clave -Name ForceDefenderPassiveMode -ErrorAction SilentlyContinue }
}
& "$PSScriptRoot\activar_defender.ps1"
Set-MpPreference -MAPSReporting Advanced -SubmitSamplesConsent SendSafeSamples -DisableBlockAtFirstSeen $false `
                 -CloudBlockLevel Default -CloudExtendedTimeout 0 -PUAProtection Enabled
$mp = Join-Path $env:ProgramFiles 'Windows Defender\MpCmdRun.exe'
& $mp -ValidateMapsConnection 2>&1 | Select-Object -Last 3 | Write-Host
$nube = $LASTEXITCODE
Get-MpPreference | Format-List MAPSReporting, SubmitSamplesConsent, DisableBlockAtFirstSeen, CloudBlockLevel, PUAProtection,
                                DisableRealtimeMonitoring, DisableBehaviorMonitoring, DisableIOAVProtection | Out-String | Write-Host

# SmartScreen de Windows para programas descargados (como en una computadora de casa: avisa antes de abrirlos)
$pol = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\System'
New-Item -Path $pol -Force | Out-Null
Set-ItemProperty -Path $pol -Name EnableSmartScreen -Type DWord -Value 1
Set-ItemProperty -Path $pol -Name ShellSmartScreenLevel -Type String -Value 'Warn'
Set-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer' -Name SmartScreenEnabled -Type String -Value 'Warn'
Write-Host 'SmartScreen para programas: Warn'
$estado = Get-MpComputerStatus
Write-Host "Nube de Defender (MAPS): $(if ($nube -eq 0) { 'conectada' } else { 'sin conexion en esta maquina' }); tiempo real: $($estado.RealTimeProtectionEnabled); modo: $($estado.AMRunningMode); descargas: $($estado.IoavProtectionEnabled); comportamiento: $($estado.BehaviorMonitorEnabled)"

# Comprobación de que el antivirus de verdad actúa: el archivo de prueba estándar EICAR, marcado como descargado,
# debe desaparecer (cuarentena) en segundos. Si no desaparece, esta máquina no reproduce una PC de casa.
$eicar = Join-Path $env:USERPROFILE 'Downloads\prueba-eicar.com'
New-Item -ItemType Directory -Force (Split-Path $eicar) | Out-Null
$texto = 'X5O!P%@AP[4\PZX54(P^)7CC)7}' + '$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*'
try { [IO.File]::WriteAllText($eicar, $texto) } catch { Write-Host "El antivirus impidió escribir EICAR: $_" }
Start-Sleep -Seconds 8
if (Test-Path $eicar) { Write-Host '::warning::EICAR sigue en Descargas: el antivirus no está bloqueando como en una PC de casa'; Remove-Item $eicar -Force -ErrorAction SilentlyContinue }
else { Write-Host 'Antivirus activo de verdad: EICAR fue bloqueado' }
exit 0
