"""Lee el minimo de macOS declarado por los binarios Mach-O de una distribucion."""
from pathlib import Path
import re
import subprocess
import sys

MAGIAS = {b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",
          b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca"}


def minimo_macos(rutas):
    versiones = ["11.0"]  # primer macOS con soporte para Apple Silicon
    vistos = set()
    encontrados = 0
    for ruta in rutas:
        ruta = Path(ruta).resolve()
        archivos = ruta.rglob("*") if ruta.is_dir() else [ruta]
        for archivo in archivos:
            if not archivo.is_file():
                continue
            real = archivo.resolve()
            if real in vistos:
                continue
            vistos.add(real)
            with real.open("rb") as entrada:
                if entrada.read(4) not in MAGIAS:
                    continue
            salida = subprocess.run(["/usr/bin/otool", "-l", str(real)],
                                    check=True, capture_output=True, text=True).stdout
            for comando, campo in (("LC_BUILD_VERSION", "minos"), ("LC_VERSION_MIN_MACOSX", "version")):
                patron = rf"cmd {comando}\n(?:(?!Load command).)*?\b{campo}\s+(\d+(?:\.\d+)+)"
                versiones.extend(re.findall(patron, salida, re.S))
            encontrados += 1
    if not encontrados:
        raise ValueError("No se encontraron binarios Mach-O para verificar el minimo de macOS.")
    return max(versiones, key=lambda v: tuple(int(n) for n in v.split(".")))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Uso: minimo_macos.py RUTA [RUTA...]")
    print(minimo_macos(sys.argv[1:]))
