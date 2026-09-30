"""Arranque de la Agencia de Empleos en Windows.

Se abre el programa como módulo (no como script): así Python usa su versión ya compilada (carpeta __pycache__) y el
programa abre más rápido; ejecutar agencia.py directamente lo recompilaría entero cada vez.

pythonw.exe no tiene consola: si algo fallara antes de que exista la ventana, el programa se cerraría sin decir
nada. Por eso aquí todo lo que Python escribiría en la consola va a «arranque.log» (en la carpeta de datos) y
cualquier error de arranque se muestra en un aviso de Windows."""
import os
import sys

CARPETA_APP = os.path.dirname(os.path.abspath(__file__))
if CARPETA_APP not in sys.path:
    sys.path.insert(0, CARPETA_APP)


def carpeta_de_datos():
    if "--datos" in sys.argv[:-1]:
        return sys.argv[sys.argv.index("--datos") + 1]
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return os.path.join(base, "Agencia de Empleos")


def avisar(texto):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, texto, "Agencia de Empleos", 0x10)   # MB_ICONERROR
    except Exception:
        pass


registro = None
if sys.stderr is None or sys.stdout is None:
    try:
        os.makedirs(carpeta_de_datos(), exist_ok=True)
        ruta = os.path.join(carpeta_de_datos(), "arranque.log")
        if os.path.exists(ruta) and os.path.getsize(ruta) > 256 * 1024:
            os.replace(ruta, ruta + ".anterior")
        registro = open(ruta, "a", encoding="utf-8", errors="replace", buffering=1)
        sys.stdout = sys.stdout or registro
        sys.stderr = sys.stderr or registro
        import faulthandler
        faulthandler.enable(registro)   # también un cierre brusco dentro de Tcl/Tk deja rastro
    except Exception:
        pass

try:
    import agencia
    agencia.main()
except SystemExit:
    raise
except BaseException as error:
    import traceback
    detalle = traceback.format_exc()
    try:
        if registro is not None:
            import datetime
            registro.write(f"--- {datetime.datetime.now():%d/%m/%Y %H:%M:%S} ---\n{detalle}\n")
            registro.flush()
    except Exception:
        pass
    avisar("No se pudo abrir Agencia de Empleos.\n\n"
           f"{type(error).__name__}: {error}\n\n"
           f"El detalle quedó en:\n{os.path.join(carpeta_de_datos(), 'arranque.log')}\n\n"
           "Si el problema continúa, vuelva a ejecutar el instalador.")
    raise SystemExit(1)
