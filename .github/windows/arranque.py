"""Arranque real del programa instalado, tal como lo hace el acceso directo, con cierre automático.

Uso:  python.exe arranque.py RESULTADO.json RUTA\\iniciar.pyw --datos CARPETA_DE_DATOS
Ejecuta iniciar.pyw (que llama a agencia.main()) con esos mismos argumentos. Los cuadros de aviso se
responden solos y se anotan; a los SEGUNDOS la ventana se cierra con su propio botón X. Escribe en
RESULTADO.json lo que ocurrió, para que la prueba funcione aunque la ejecute otro usuario de Windows."""
import json
import os
import runpy
import sys
import time
import traceback

RESULTADO = sys.argv[1]
SEGUNDOS = float(os.environ.get("AGENCIA_PRUEBA_SEGUNDOS", "10"))
sys.argv = sys.argv[2:]
sys.path.insert(0, os.path.dirname(os.path.abspath(sys.argv[0])))
informe = {"argv": sys.argv, "ejecutable": sys.executable, "avisos": [], "errores_tk": [], "ventana": None,
           "cerrada": False, "excepcion": None, "inicio": time.time()}

import tkinter as tk  # noqa: E402
from tkinter import messagebox  # noqa: E402


def _responder(tipo):
    def responder(titulo="", mensaje="", **_):
        informe["avisos"].append({"tipo": tipo, "titulo": titulo, "mensaje": str(mensaje)})
        return {"askyesno": False, "askokcancel": False, "askyesnocancel": False,
                "askretrycancel": False, "askquestion": "no"}.get(tipo, "ok")
    return responder


for _nombre in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel",
                "askyesnocancel", "askretrycancel", "askquestion"):
    setattr(messagebox, _nombre, _responder(_nombre))

_mainloop = tk.Misc.mainloop


def mainloop(self, n=0):
    def revisar():
        try:
            self.update_idletasks()
            informe["ventana"] = {"titulo": self.title(), "ancho": self.winfo_width(), "alto": self.winfo_height(),
                                  "estado": self.state(), "visible": bool(self.winfo_viewable()),
                                  "tk": self.tk.call("info", "patchlevel"), "escala": self.tk.call("tk", "scaling")}
        except Exception:
            informe["excepcion"] = traceback.format_exc()

    def cerrar():
        revisar()
        informe["cerrada"] = True
        self.tk.call(self.protocol("WM_DELETE_WINDOW"))   # lo mismo que pulsar la X

    self.after(int(SEGUNDOS * 1000), cerrar)
    self.after(int(SEGUNDOS * 1000) + 60000, self.destroy)   # último recurso: nunca dejar la prueba colgada
    anterior = self.report_callback_exception
    self.report_callback_exception = lambda t, v, tb: (informe["errores_tk"].append(
        "".join(traceback.format_exception(t, v, tb))), anterior(t, v, tb))
    return _mainloop(self, n)


tk.Misc.mainloop = mainloop

if sys.platform == "win32":   # el aviso de error de iniciar.pyw sería un cuadro de Windows que bloquearía la prueba
    import ctypes
    ctypes.windll.user32.MessageBoxW = lambda _v, texto, titulo, _t: informe["avisos"].append(
        {"tipo": "MessageBoxW", "titulo": titulo, "mensaje": texto}) or 1

try:
    runpy.run_path(sys.argv[0], run_name="__main__")
except SystemExit as salida:
    informe["salida"] = salida.code
except BaseException:
    informe["excepcion"] = traceback.format_exc()
informe["duracion"] = time.time() - informe.pop("inicio")
datos = sys.argv[sys.argv.index("--datos") + 1] if "--datos" in sys.argv else None
if datos:
    errores = os.path.join(datos, "errores.log")
    informe["errores_log"] = open(errores, encoding="utf-8", errors="replace").read() if os.path.exists(errores) else ""
    informe["base_creada"] = os.path.exists(os.path.join(datos, "agencia.db"))
with open(RESULTADO, "w", encoding="utf-8") as archivo:
    json.dump(informe, archivo, ensure_ascii=False, indent=2)
print(json.dumps(informe, ensure_ascii=False, indent=2))
ok = (informe["cerrada"] and not informe["excepcion"] and not informe["errores_tk"] and not informe.get("salida")
      and not informe.get("errores_log") and not any(a["tipo"] in ("showerror", "MessageBoxW") for a in informe["avisos"]))
sys.exit(0 if ok else 1)
