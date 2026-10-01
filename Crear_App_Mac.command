#!/bin/bash
# Crea un lanzador local de Agencia de Empleos. Requiere Python con Tk ya instalado.
cd "$(dirname "$0")" || exit 1

/usr/bin/python3 - <<'PYTHON'
import glob
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile

carpeta = os.getcwd()
app = os.path.join(carpeta, "Agencia de Empleos.app")

def comprobar_app_cerrada():
    try:
        procesos = subprocess.run(["/bin/ps", "-axo", "pid=,command="], check=True,
                                  capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as error:
        sys.exit(f"No pude comprobar si la app esta abierta: {error}")
    carpetas_propias = {carpeta}
    carpeta_logica = os.environ.get("PWD", "")
    if carpeta_logica and os.path.realpath(carpeta_logica) == os.path.realpath(carpeta):
        carpetas_propias.add(carpeta_logica)
    referencias = tuple(referencia for propia in carpetas_propias for referencia in (
        os.path.join(propia, os.path.basename(app), "Contents", "MacOS") + "/",
        os.path.join(propia, "agencia.py")))
    activos = []
    for linea in procesos.stdout.splitlines():
        campos = linea.strip().split(None, 2)
        if len(campos) < 2 or campos[0] == str(os.getpid()):
            continue
        programa = os.path.basename(campos[1]).lower()
        comando = linea.strip().split(None, 1)[1]
        if (programa.startswith("python") or programa in ("bash", "sh", "agencia")) and any(
                referencia in comando for referencia in referencias):
            activos.append(campos[0])
    if activos:
        sys.exit("Cierre esta agencia antes de recrear su app. Procesos activos: " + ", ".join(activos))

comprobar_app_cerrada()
for recurso in ("agencia.py", "logo.png", "icono.icns"):
    if not os.path.isfile(os.path.join(carpeta, recurso)):
        sys.exit(f"Falta {recurso} en la carpeta del programa.")

carpetas = ["/opt/homebrew/bin", "/usr/local/bin", os.path.expanduser("~/.local/bin"),
            *glob.glob("/Library/Frameworks/Python.framework/Versions/*/bin")]
candidatos = sorted({p for c in carpetas for p in glob.glob(os.path.join(c, "python3.*"))
                     if re.fullmatch(r"python3\.\d+", os.path.basename(p))},
                    key=lambda p: int(p.rsplit(".", 1)[1]), reverse=True)
ejecutable = None
prefijo_elegido = None
for python in candidatos:
    try:
        salida = subprocess.run([python, "-c", "import sys, tkinter; print(tkinter.TkVersion); print(sys.base_prefix)"],
                                capture_output=True, text=True, timeout=20)
        tk, prefijo = salida.stdout.split()
        app_python = os.path.join(prefijo, "Resources", "Python.app", "Contents", "MacOS", "Python")
        if salida.returncode == 0 and float(tk) >= 8.6 and os.path.exists(app_python):
            ejecutable = app_python
            prefijo_elegido = prefijo
            break
    except (OSError, ValueError, subprocess.SubprocessError):
        continue
if not ejecutable:
    sys.exit("No encontre un Python con Tk 8.6 o mas.\nInstale uno con: brew install python-tk\n"
             "o desde https://www.python.org/downloads/")

minimo = subprocess.run([sys.executable, os.path.join(carpeta, "instaladores", "construccion", "minimo_macos.py"),
                         prefijo_elegido], check=True, capture_output=True, text=True).stdout.strip()

temporal = tempfile.mkdtemp(prefix=".agencia-app-", dir=carpeta)
nueva = os.path.join(temporal, "Agencia de Empleos.app")
anterior = os.path.join(temporal, "anterior.app")
try:
    for sub in ("MacOS", "Resources"):
        os.makedirs(os.path.join(nueva, "Contents", sub))
    shutil.copy2(os.path.join(carpeta, "icono.icns"), os.path.join(nueva, "Contents", "Resources", "icono.icns"))
    os.symlink(ejecutable, os.path.join(nueva, "Contents", "MacOS", "python"))
    lanzador = os.path.join(nueva, "Contents", "MacOS", "Agencia")
    with open(lanzador, "w", encoding="utf-8") as archivo:
        archivo.write('#!/bin/bash\n'
                      'AQUI="$(cd "$(dirname "$0")" && pwd)"\n'
                      'exec "$AQUI/python" "$AQUI/../../../agencia.py" "$@"\n')
    os.chmod(lanzador, 0o755)
    with open(os.path.join(carpeta, "agencia.py"), encoding="utf-8") as fuente:
        version = re.search(r'^VERSION = "([0-9.]+)"', fuente.read(), re.M).group(1)    # la del programa
    with open(os.path.join(nueva, "Contents", "Info.plist"), "wb") as archivo:
        plistlib.dump({"CFBundleName": "Agencia de Empleos", "CFBundleDisplayName": "Agencia de Empleos",
                       "CFBundleExecutable": "Agencia", "CFBundleIdentifier": "pe.servicioexclusivo.agencia",
                       "CFBundleIconFile": "icono", "CFBundlePackageType": "APPL",
                       "CFBundleVersion": version, "CFBundleShortVersionString": version,
                       "NSHighResolutionCapable": True, "LSMinimumSystemVersion": minimo}, archivo)
    comprobar_app_cerrada()
    if os.path.exists(app):
        os.replace(app, anterior)
    try:
        os.replace(nueva, app)
    except OSError:
        if os.path.exists(anterior):
            os.replace(anterior, app)
        raise
finally:
    if os.path.exists(anterior) and not os.path.exists(app):
        print(f"La app anterior se conserva en: {anterior}", file=sys.stderr)
    else:
        shutil.rmtree(temporal)
print('Listo: "Agencia de Empleos.app" esta en esta carpeta. Dejela junto a agencia.py.')
print(f'Este lanzador usa el Python instalado en el equipo y requiere macOS {minimo} o posterior.')
PYTHON
status=$?
echo
[ "$status" -eq 0 ] || echo "No se pudo crear la app."
if [ -t 0 ]; then
  read -n 1 -s -r -p "Pulse una tecla para cerrar..."
  echo
fi
exit "$status"
