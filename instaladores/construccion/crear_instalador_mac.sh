#!/bin/bash
# Crea el instalador de Mac (Apple Silicon / arm64):  instaladores/Agencia-de-Empleos-Mac-arm64.dmg
# Debe ejecutarse en un Mac con Apple Silicon.  Uso:  ./crear_instalador_mac.sh
set -euo pipefail

RAIZ="$(cd "$(dirname "$0")/../.." && pwd)"          # carpeta del proyecto (donde esta agencia.py)
CONSTRUCCION="$RAIZ/instaladores/construccion"
SALIDA="$RAIZ/instaladores"
TRABAJO="$(mktemp -d "${TMPDIR:-/tmp}/agencia-instalador-mac.XXXXXX")"    # carpeta temporal de trabajo (se puede borrar)
NOMBRE="Agencia de Empleos"
VERSION="${VERSION:-1.7.1}"
trap 'codigo=$?; if [ "$codigo" -eq 0 ]; then rm -rf "$TRABAJO"; else echo "Construccion fallida. Archivos conservados en: $TRABAJO" >&2; fi' EXIT
DMG="$SALIDA/Agencia-de-Empleos-Mac-arm64.dmg"

[ "$(uname -m)" = "arm64" ] || { echo "Este script es para Mac con Apple Silicon (arm64)."; exit 1; }
for recurso in agencia.py logo.png icono.png icono.ico icono.icns; do
  [ -f "$RAIZ/$recurso" ] || { echo "Falta $recurso en la carpeta de Agencia de Empleos."; exit 1; }
done

# 1) Preferir Python 3.12 para soportar mas versiones de macOS.
# El minimo real se calcula despues con todos los binarios incluidos.
PYTHON=""
for c in python3.12 "$HOME/.local/bin/python3.12" /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12 \
         /opt/homebrew/bin/python3.* /usr/local/bin/python3.* "$HOME"/.local/bin/python3.*; do
  case "$(basename "$c")" in python3.[0-9]|python3.[0-9][0-9]) ;; *) continue ;; esac
  if "$c" -c 'import sys,tkinter; sys.exit(0 if tkinter.TkVersion>=8.6 else 1)' 2>/dev/null; then PYTHON="$c"; break; fi
done
[ -n "$PYTHON" ] || { echo "No encontre un Python con Tk 8.6+. Instale uno:  brew install python-tk"; exit 1; }
echo "Python: $PYTHON ($("$PYTHON" -c 'import sys,tkinter;print(sys.version.split()[0],"Tk",tkinter.TkVersion)'))"

# 2) Entorno aislado con PyInstaller (no toca su Python)
mkdir -p "$TRABAJO" "$SALIDA"
[ -x "$TRABAJO/venv/bin/pyinstaller" ] || {
  "$PYTHON" -m venv "$TRABAJO/venv"
  "$TRABAJO/venv/bin/pip" install --quiet --disable-pip-version-check pyinstaller
}

# 3) La app
rm -rf "$TRABAJO/dist" "$TRABAJO/work" "$TRABAJO/spec"
"$TRABAJO/venv/bin/pyinstaller" --noconfirm --windowed --name "$NOMBRE" --icon "$RAIZ/icono.icns" \
  --add-data "$RAIZ/logo.png:." --add-data "$RAIZ/icono.png:." --add-data "$RAIZ/icono.ico:." \
  --osx-bundle-identifier pe.servicioexclusivo.agencia \
  --distpath "$TRABAJO/dist" --workpath "$TRABAJO/work" --specpath "$TRABAJO/spec" "$RAIZ/agencia.py" >"$TRABAJO/pyinstaller.log" 2>&1 || { cat "$TRABAJO/pyinstaller.log"; exit 1; }
APP="$TRABAJO/dist/$NOMBRE.app"
[ -d "$APP" ] || { echo "PyInstaller no creo la app."; exit 1; }

PLIST="$APP/Contents/Info.plist"
MINIMO="$(/usr/bin/python3 "$CONSTRUCCION/minimo_macos.py" "$APP")"
echo "Version minima de macOS de este paquete: $MINIMO"
plutil -replace CFBundleShortVersionString -string "$VERSION" "$PLIST"
plutil -replace CFBundleVersion -string "$VERSION" "$PLIST"
plutil -replace LSMinimumSystemVersion -string "$MINIMO" "$PLIST"
plutil -replace LSApplicationCategoryType -string "public.app-category.business" "$PLIST"
plutil -replace NSHumanReadableCopyright -string "$NOMBRE" "$PLIST"
codesign --force --deep --sign - "$APP"          # firma local (sin cuenta de desarrollador)
codesign --verify --deep --strict "$APP"

# 4) El .dmg: la app y un acceso a Aplicaciones para arrastrar
PUESTA="$TRABAJO/dmg"
rm -rf "$PUESTA" && mkdir -p "$PUESTA"
cp -R "$APP" "$PUESTA/"
ln -s /Applications "$PUESTA/Aplicaciones"
cat > "$PUESTA/LEAME - primera vez.txt" <<TXT
INSTALAR
  Requiere un Mac con Apple Silicon y macOS $MINIMO o posterior.
  1. Arrastre "$NOMBRE" a la carpeta "Aplicaciones".
  2. Abralo desde Aplicaciones (o el Launchpad).

LA PRIMERA VEZ, si el Mac dice que no puede verificar al desarrollador:
  - Haga clic derecho (o Control + clic) sobre el programa > Abrir > Abrir.
  - Si no aparece esa opcion: Ajustes del Sistema > Privacidad y seguridad >
    "Abrir igualmente".
  Solo hace falta la primera vez.

SUS DATOS
  Se guardan en:  ~/Library/Application Support/$NOMBRE
  (clientes, trabajadoras, contratos y respaldos automaticos).
  Actualizar o borrar el programa NO borra esa carpeta.
TXT
NUEVO="$TRABAJO/Agencia-de-Empleos-Mac-arm64.dmg"
hdiutil create -quiet -volname "$NOMBRE" -srcfolder "$PUESTA" -ov -format UDZO -imagekey zlib-level=9 "$NUEVO"
hdiutil verify -quiet "$NUEVO"
mv -f "$NUEVO" "$DMG"

echo
echo "Listo: $DMG ($(du -h "$DMG" | cut -f1))"
