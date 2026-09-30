# Deja la máquina de pruebas lo más parecida posible a una computadora de casa con Windows 10/11:
# antivirus con protección en tiempo real Y en la nube (bloqueo a primera vista), SmartScreen para programas
# descargados y ninguna exclusión. Las máquinas de GitHub traen todo esto apagado.
$ErrorActionPreference = 'Continue'
& "$PSScriptRoot\activar_defender.ps1"
Set-MpPreference -MAPSReporting Advanced -SubmitSamplesConsent SendSafeSamples -DisableBlockAtFirstSeen $false `
                 -CloudBlockLevel Default -CloudExtendedTimeout 0 -PUAProtection Enabled
$mp = Join-Path $env:ProgramFiles 'Windows Defender\MpCmdRun.exe'
& $mp -ValidateMapsConnection 2>&1 | Select-Object -Last 3 | Write-Host
Get-MpPreference | Format-List MAPSReporting, SubmitSamplesConsent, DisableBlockAtFirstSeen, CloudBlockLevel, PUAProtection,
                                DisableRealtimeMonitoring, DisableBehaviorMonitoring, DisableIOAVProtection | Out-String | Write-Host

# SmartScreen de Windows para programas descargados (como en una computadora de casa: avisa antes de abrirlos)
$pol = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\System'
New-Item -Path $pol -Force | Out-Null
Set-ItemProperty -Path $pol -Name EnableSmartScreen -Type DWord -Value 1
Set-ItemProperty -Path $pol -Name ShellSmartScreenLevel -Type String -Value 'Warn'
Set-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer' -Name SmartScreenEnabled -Type String -Value 'Warn'
Write-Host 'SmartScreen para programas: Warn'
