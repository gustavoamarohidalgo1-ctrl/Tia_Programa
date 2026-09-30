# Las máquinas de GitHub traen el antivirus de Windows con la protección en tiempo real APAGADA y C:\ y D:\ excluidos.
# Un equipo real lo tiene encendido: se enciende aquí para que el instalador se pruebe en esas condiciones.
$ErrorActionPreference = 'Continue'
$antes = Get-MpPreference
foreach ($ruta in @($antes.ExclusionPath)) { if ($ruta) { Remove-MpPreference -ExclusionPath $ruta } }
foreach ($proceso in @($antes.ExclusionProcess)) { if ($proceso) { Remove-MpPreference -ExclusionProcess $proceso } }
foreach ($extension in @($antes.ExclusionExtension)) { if ($extension) { Remove-MpPreference -ExclusionExtension $extension } }
Set-MpPreference -DisableRealtimeMonitoring $false -DisableBehaviorMonitoring $false -DisableIOAVProtection $false `
                 -DisableScriptScanning $false -DisableArchiveScanning $false
Start-Sleep -Seconds 5
$estado = Get-MpComputerStatus
$estado | Format-List AMServiceEnabled, AntivirusEnabled, RealTimeProtectionEnabled, OnAccessProtectionEnabled,
                     IoavProtectionEnabled, BehaviorMonitorEnabled, AntivirusSignatureVersion | Out-String | Write-Host
$ahora = Get-MpPreference
Write-Host "Exclusiones restantes: $(@($ahora.ExclusionPath) -join ', ')"
if (-not $estado.RealTimeProtectionEnabled) { Write-Host '::warning::No se pudo encender la protección en tiempo real' }
