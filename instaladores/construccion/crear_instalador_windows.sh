#!/bin/bash
# Crea el instalador de Windows de 64 bits:  instaladores/Agencia-de-Empleos-Windows-x64.exe
# Se puede ejecutar desde un Mac. Necesita:  brew install makensis sevenzip msitools
#
# Como no se puede compilar un .exe de Windows desde un Mac, el instalador lleva su propio Python oficial
# para Windows (python.org) con Tcl/Tk, mas el programa. Uso:  ./crear_instalador_windows.sh
set -euo pipefail

RAIZ="$(cd "$(dirname "$0")/../.." && pwd)"
AQUI="$RAIZ/instaladores/construccion"
SALIDA="$RAIZ/instaladores/Agencia-de-Empleos-Windows-x64.exe"
TRABAJO="$(mktemp -d "${TMPDIR:-/tmp}/agencia-instalador-windows.XXXXXX")"
CACHE="${TMPDIR:-/tmp}/agencia-instalador-descargas"
VERSION="${VERSION:-$(sed -n 's/^VERSION = "\([0-9.]*\)".*/\1/p' "$RAIZ/agencia.py")}"   # la de agencia.py
[ -n "$VERSION" ] || { echo "No se encontro VERSION en agencia.py."; exit 1; }
trap 'codigo=$?; if [ "$codigo" -eq 0 ]; then rm -rf "$TRABAJO"; else echo "Construccion fallida. Archivos conservados en: $TRABAJO" >&2; fi' EXIT
PYVER="3.12.10"     # ultima 3.12 con binarios para Windows

# Huellas SHA-256 de lo que se descarga (si algo cambia, el script se detiene)
NUPKG_URL="https://api.nuget.org/v3-flatcontainer/python/$PYVER/python.$PYVER.nupkg"
NUPKG_SHA="0eb85c2dfccccf1b17352de4c397f69194035b7d37149eacc16f1147d93de3b8"
EXE_URL="https://www.python.org/ftp/python/$PYVER/python-$PYVER-amd64.exe"
EXE_SHA="67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb"

for herramienta in makensis 7zz msiextract unzip curl python3 shasum; do
  command -v "$herramienta" >/dev/null || { echo "Falta '$herramienta'.  Instale:  brew install makensis sevenzip msitools"; exit 1; }
done
for recurso in agencia.py logo.png icono.png icono.ico; do
  [ -f "$RAIZ/$recurso" ] || { echo "Falta $recurso en la carpeta de Agencia de Empleos."; exit 1; }
done
mkdir -p "$TRABAJO" "$CACHE" "$RAIZ/instaladores"

descargar() {   # url archivo huella
  if [ -f "$2" ] && [ "$(shasum -a 256 "$2" | cut -d' ' -f1)" = "$3" ]; then return; fi
  echo "Descargando $(basename "$2")..."
  local temporal
  temporal="$(mktemp "$CACHE/descarga.XXXXXX")"
  curl -fsSL -m 600 -o "$temporal" "$1" || { rm -f "$temporal"; return 1; }
  [ "$(shasum -a 256 "$temporal" | cut -d' ' -f1)" = "$3" ] || { echo "La huella de $(basename "$2") no coincide. Se detiene."; rm -f "$temporal"; exit 1; }
  mv -f "$temporal" "$2"
}
descargar "$NUPKG_URL" "$CACHE/python.nupkg" "$NUPKG_SHA"
descargar "$EXE_URL" "$CACHE/python-instalador.exe" "$EXE_SHA"

# 1) Base: Python para Windows (paquete de nuget: python.exe, pythonw.exe, DLLs y libreria estandar)
rm -rf "$TRABAJO/nuget" "$TRABAJO/runtime" "$TRABAJO/cab" "$TRABAJO/paquetes" "$TRABAJO/tcltk"
unzip -q "$CACHE/python.nupkg" -d "$TRABAJO/nuget"
mkdir "$TRABAJO/runtime"
cp -R "$TRABAJO/nuget/tools/." "$TRABAJO/runtime/"
rm -rf "$TRABAJO/runtime/include" "$TRABAJO/runtime/libs"

# 2) Tcl/Tk y tkinter: ese paquete no los trae; salen del instalador oficial (contenedor CAB con los MSI)
python3 - "$TRABAJO" "$CACHE" <<'PYTHON'
import struct, sys
t = sys.argv[1]
datos = open(f"{sys.argv[2]}/python-instalador.exe", "rb").read()
mejor, pos = (0, 0), 0
while (i := datos.find(b"MSCF\x00\x00\x00\x00", pos)) >= 0:
    mejor = max(mejor, (struct.unpack("<I", datos[i + 8:i + 12])[0], i)); pos = i + 1
tam, i = mejor
open(f"{t}/contenedor.cab", "wb").write(datos[i:i + tam])
PYTHON
mkdir "$TRABAJO/paquetes"
7zz x -y -o"$TRABAJO/paquetes" "$TRABAJO/contenedor.cab" >/dev/null
TCLTK=""
for f in "$TRABAJO"/paquetes/a*; do
  lista="$(msiextract -l "$f" 2>/dev/null || true)"      # (sin tuberia: con pipefail, grep -q la cortaria)
  if grep -q "_tkinter.pyd" <<<"$lista"; then TCLTK="$f"; break; fi
done
[ -n "$TCLTK" ] || { echo "No encontre el paquete de Tcl/Tk dentro del instalador de Python."; exit 1; }
mkdir "$TRABAJO/tcltk"
msiextract -C "$TRABAJO/tcltk" "$TCLTK" >/dev/null
cp -R "$TRABAJO/tcltk/DLLs/." "$TRABAJO/runtime/DLLs/"
cp -R "$TRABAJO/tcltk/Lib/." "$TRABAJO/runtime/Lib/"
cp -R "$TRABAJO/tcltk/tcl" "$TRABAJO/runtime/tcl"

# 3) Recortar lo que el programa no usa (pruebas, IDLE, demos, pip...)
R="$TRABAJO/runtime"
rm -rf "$R/Lib/test" "$R/Lib/idlelib" "$R/Lib/turtledemo" "$R/Lib/ensurepip" "$R/Lib/site-packages" \
       "$R/Lib/lib2to3" "$R/Lib/venv" "$R/Lib/tkinter/test" "$R/Lib/unittest/test" "$R/tcl/tk8.6/demos"
find "$R" -name "__pycache__" -type d -prune -exec rm -rf {} +
find "$R/DLLs" \( -name "_test*.pyd" -o -name "xxlimited*.pyd" -o -name "_ctypes_test.pyd" \) -delete
find "$R" -name "*.pdb" -delete

# 3b) Precompilar (mas rapido al abrir): sin esto, Windows compila la libreria estandar la primera vez y el
#     programa entero en CADA apertura. El bytecode de Python 3.12 es el mismo en todos los sistemas; se usa el
#     modo "unchecked-hash" (no depende de las fechas de los archivos). Necesita un Python 3.12 en este equipo.
PY312=""
for c in python3.12 "$HOME/.local/bin/python3.12" /opt/homebrew/bin/python3.12; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info[:2]==(3,12) else 1)' 2>/dev/null; then PY312="$c"; break; fi
done
APP="$TRABAJO/aplicacion"
rm -rf "$APP" && mkdir -p "$APP"
cp "$RAIZ/agencia.py" "$RAIZ/logo.png" "$RAIZ/icono.png" "$RAIZ/icono.ico" "$AQUI/iniciar.pyw" "$APP/"
if [ -n "$PY312" ]; then
  # -s: los .pyc no guardan la carpeta temporal de este equipo, solo la ruta dentro del programa
  "$PY312" -m compileall -q -f -s "$R" --invalidation-mode unchecked-hash "$R/Lib" >/dev/null
  # El programa, con huella comprobada: si alguna vez se reemplaza app\agencia.py a mano, Python usa el nuevo.
  "$PY312" -m compileall -q -f -s "$APP" --invalidation-mode checked-hash "$APP/agencia.py" >/dev/null
  echo "Precompilado con $("$PY312" -V): $(find "$R/Lib" "$APP" -name '*.pyc' | wc -l | tr -d ' ') archivos"
else
  echo "AVISO: no hay Python 3.12 para precompilar; el instalador funciona igual pero abrira mas lento."
fi

# 4) Comprobar que estan las piezas que el programa necesita antes de empaquetar
faltan=0
for f in python.exe pythonw.exe python312.dll vcruntime140.dll DLLs/_tkinter.pyd DLLs/tcl86t.dll DLLs/tk86t.dll \
         DLLs/_sqlite3.pyd DLLs/sqlite3.dll DLLs/_ctypes.pyd Lib/tkinter/__init__.py Lib/tkinter/ttk.py \
         Lib/sqlite3/__init__.py Lib/json/__init__.py Lib/html/__init__.py tcl/tcl8.6/init.tcl tcl/tk8.6/tk.tcl; do
  [ -e "$R/$f" ] || { echo "FALTA: $f"; faltan=1; }
done
[ $faltan -eq 0 ] || exit 1

# 5) Icono del instalador (sin la imagen PNG de 256 px, que NSIS no admite en su icono)
python3 - "$RAIZ/icono.ico" "$TRABAJO/instalador.ico" <<'PYTHON'
import struct, sys
d = open(sys.argv[1], "rb").read()
n = struct.unpack("<H", d[4:6])[0]
ent = [struct.unpack("<BBBBHHII", d[6 + 16 * i:22 + 16 * i]) for i in range(n)]
ent = [e for e in ent if e[0] != 0]                      # ancho 0 = 256 px (PNG)
pos, tabla, cuerpo = 6 + 16 * len(ent), b"", b""
for w, h, c, r, pl, bpp, tam, off in ent:
    tabla += struct.pack("<BBBBHHII", w, h, c, r, pl, bpp, tam, pos + len(cuerpo)); cuerpo += d[off:off + tam]
open(sys.argv[2], "wb").write(struct.pack("<HHH", 0, 1, len(ent)) + tabla + cuerpo)
PYTHON

# 6) Compilar el instalador (el guion lleva marca UTF-8 para que NSIS lea bien los acentos)
{ printf '\xEF\xBB\xBF'; cat "$AQUI/instalador.nsi"; } > "$TRABAJO/instalador.nsi"
NUEVO="$TRABAJO/Agencia-de-Empleos-Windows-x64.exe"
export LC_ALL=en_US.UTF-8     # sin una configuracion regional UTF-8, makensis se cae al generar las tablas de idioma
makensis -V2 -DRAIZ="$RAIZ" -DAPLICACION="$APP" -DRUNTIME="$R" -DVERSION="$VERSION" -DSALIDA="$NUEVO" \
         -DICONO="$TRABAJO/instalador.ico" "$TRABAJO/instalador.nsi" | tail -n 12
[ -s "$NUEVO" ] || { echo "NSIS no genero el instalador."; exit 1; }
mv -f "$NUEVO" "$SALIDA"

echo
echo "Listo: $SALIDA ($(du -h "$SALIDA" | cut -f1))"
