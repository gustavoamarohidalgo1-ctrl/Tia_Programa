# Actualización de una agencia que ya trabajaba con la versión 1.7.0: su carpeta de datos tiene una base con la
# estructura de 1.7.0 (datos ficticios en vieja_1_7_0.sql, generados con el código de 1.7.0) y un contrato firmado.
# Se instala encima la versión nueva y se abre: debe guardar una copia, actualizar la base sin perder nada y abrir
# sin avisos de error.
param(
  [Parameter(Mandatory)][string]$Instalador,
  [string]$Salida = "$env:RUNNER_TEMP\resultados"
)
$ErrorActionPreference = 'Continue'
New-Item -ItemType Directory -Force $Salida | Out-Null
$fallos = 0
function Fallo($t) { Write-Host "::error::desde-1.7.0 - $t"; $script:fallos++ }
$Instalador = (Resolve-Path $Instalador).Path
$Instdir = Join-Path $env:LOCALAPPDATA 'Programs\Agencia de Empleos'
$Datos = Join-Path $env:LOCALAPPDATA 'Agencia de Empleos'
Remove-Item -Recurse -Force $Instdir, $Datos -ErrorAction SilentlyContinue

# 1) Una instalación previa con la misma estructura de carpetas que dejaba 1.7.0
$p = Start-Process -FilePath $Instalador -ArgumentList '/S' -Wait -PassThru
if ($p.ExitCode -ne 0) { Fallo "Instalación previa: código $($p.ExitCode)" }
$py = "$Instdir\runtime\python.exe"

# 2) Los datos de 1.7.0
New-Item -ItemType Directory -Force $Datos | Out-Null
& $py -c "import sqlite3, sys; c = sqlite3.connect(sys.argv[1]); c.executescript(open(sys.argv[2], encoding='utf-8').read()); c.close()" `
  (Join-Path $Datos 'agencia.db') "$PSScriptRoot\vieja_1_7_0.sql"
if ($LASTEXITCODE -ne 0) { Fallo 'No se pudo preparar la base 1.7.0' }

# 3) Instalar la versión nueva encima
$p = Start-Process -FilePath $Instalador -ArgumentList '/S' -Wait -PassThru
Write-Host "Actualización sobre 1.7.0 -> código $($p.ExitCode)"
if ($p.ExitCode -ne 0) { Fallo "La actualización terminó con código $($p.ExitCode)" }

# 4) Primer arranque de la versión nueva con esos datos
$s = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Agencia de Empleos\Agencia de Empleos.lnk'))
$partes = [regex]::Matches($s.Arguments, '"([^"]*)"|(\S+)') | ForEach-Object { if ($_.Groups[1].Success) { $_.Groups[1].Value } else { $_.Groups[2].Value } }
$json = Join-Path $Salida 'desde-170.json'
& $py "$PSScriptRoot\arranque.py" $json @partes 2>&1 | Out-File (Join-Path $Salida 'desde-170.txt') -Encoding utf8
if ($LASTEXITCODE -ne 0) { Fallo "El primer arranque sobre datos 1.7.0 falló: $(Get-Content $json -Raw -Encoding utf8)" }
$r = Get-Content $json -Raw -Encoding utf8 | ConvertFrom-Json
foreach ($a in @($r.avisos)) { Write-Host "aviso $($a.tipo): $($a.titulo) - $($a.mensaje)" }

# 5) Comprobar la base actualizada
$comprobacion = @'
import sqlite3, sys, os, glob
c = sqlite3.connect(sys.argv[1])
columnas = {r[1] for r in c.execute("PRAGMA table_info(colocaciones)")}
assert "contrato_html" in columnas, "falta contrato_html"
html = c.execute("SELECT contrato_html FROM colocaciones WHERE contrato_firmado = '1'").fetchone()[0]
assert html and "Cliente Ficticio" in html, "el contrato firmado no se conservó"
assert c.execute("SELECT COUNT(*) FROM clientes").fetchone()[0] == 2
assert c.execute("SELECT COUNT(*) FROM trabajadoras").fetchone()[0] == 2
assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
copias = glob.glob(os.path.join(sys.argv[2], "respaldos", "agencia-antes-de-actualizar-*.db"))
assert copias, "no se guardó la copia antes de actualizar"
v = sqlite3.connect(copias[0])
assert "contrato_html" not in {r[1] for r in v.execute("PRAGMA table_info(colocaciones)")}, "la copia previa no es la base 1.7.0"
print("Base 1.7.0 actualizada; copia previa:", os.path.basename(copias[0]))
'@
$guion = Join-Path $env:RUNNER_TEMP 'comprobar_170.py'
Set-Content -Path $guion -Value $comprobacion -Encoding utf8
& $py $guion (Join-Path $Datos 'agencia.db') $Datos
if ($LASTEXITCODE -ne 0) { Fallo 'La base 1.7.0 no quedó bien actualizada' }

if ($fallos) { exit 1 }
Write-Host 'OK: actualización desde 1.7.0 con datos.'
exit 0
