"""Prueba de humo de la aplicación instalada en Windows (se ejecuta en GitHub Actions).

Uso:  python.exe humo.py CARPETA_APP CARPETA_DATOS
Abre la ventana real, recorre todas las pantallas, registra un cliente y una trabajadora, los asigna,
genera el contrato, hace copias de seguridad, exporta CSV, restaura una copia y cierra como lo haría
la persona usuaria. Cualquier error de Tk, cuadro de error o excepción hace fallar la prueba."""
import os
import sys
import time
import traceback

APP, DATOS = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
sys.argv = [os.path.join(APP, "iniciar.pyw"), "--datos", DATOS]
sys.path.insert(0, APP)

import agencia  # noqa: E402
import tkinter as tk  # noqa: E402
from tkinter import messagebox  # noqa: E402

fallos, pasos = [], []


def anotar(texto):
    pasos.append(texto)
    print("·", texto, flush=True)


def fallo(texto):
    fallos.append(texto)
    print("FALLO:", texto, flush=True)


# Los cuadros modales bloquearían la prueba: se responden solos y los de error cuentan como fallo.
def _aviso(tipo):
    def responder(titulo="", mensaje="", **_):
        if tipo in ("showerror",):
            fallo(f"messagebox.{tipo}: {titulo}: {mensaje}")
        else:
            anotar(f"messagebox.{tipo}: {titulo}: {str(mensaje)[:200]}")
        return {"askyesno": True, "askokcancel": True, "askyesnocancel": True,
                "askretrycancel": False, "askquestion": "yes"}.get(tipo, "ok")
    return responder


for _nombre in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel",
                "askyesnocancel", "askretrycancel", "askquestion"):
    setattr(messagebox, _nombre, _aviso(_nombre))
    setattr(agencia.messagebox, _nombre, _aviso(_nombre))

# Las copias «externas» van a una carpeta de la prueba, no a Documentos: así no quedan copias que el
# programa real ofrezca recuperar en los arranques siguientes.
_documentos = os.path.join(DATOS, "Documentos de prueba")
agencia.carpeta_documentos = lambda: _documentos

# No abrir el navegador ni el Explorador durante la prueba, pero sí comprobar lo que se abriría.
import webbrowser  # noqa: E402
webbrowser.open = lambda url, *a, **k: anotar(f"webbrowser.open({url[:120]})") or True
_startfile = getattr(os, "startfile", None)
os.startfile = lambda ruta, *a, **k: anotar(f"os.startfile({ruta})") if os.path.exists(ruta) else fallo(f"startfile sin destino: {ruta}")


def paso(nombre):
    def decorador(funcion):
        def envoltura(*args):
            try:
                resultado = funcion(*args)
                anotar(f"OK {nombre}")
                return resultado
            except Exception:
                fallo(f"{nombre}:\n{traceback.format_exc()}")
        return envoltura
    return decorador


def valor_campo(campo):
    clave, etiqueta = campo[0], campo[1]
    tipo = campo[2] if len(campo) > 2 else "entry"
    if tipo in ("combo", "autocompletar") and len(campo) > 3 and campo[3]:
        return campo[3][0]
    if tipo == "check":
        return "1"
    if tipo in ("readonly", "ref"):
        return None
    if "telefono" in clave:
        return "987654321"
    if clave == "dni":
        return "12345678"
    if "sueldo" in clave or clave in ("edad", "experiencia", "personas_hogar"):
        return "1200" if "sueldo" in clave else "30"
    return f"Prueba Windows {etiqueta.split()[0]} ñáéíóú"


def main():
    anotar(f"Python {sys.version} en {sys.platform}; Tk {tk.TkVersion}; ejecutable {sys.executable}")
    anotar(f"Datos: {agencia.CARPETA}; recursos: {agencia.RECURSOS}")
    if os.path.normcase(agencia.CARPETA) != os.path.normcase(DATOS):
        fallo(f"--datos no se respetó: {agencia.CARPETA}")
    root = tk.Tk()
    root.report_callback_exception = lambda t, v, tb: fallo("Tk callback:\n" + "".join(traceback.format_exception(t, v, tb)))
    os.makedirs(agencia.CARPETA, exist_ok=True)
    aviso, oferta = agencia.preparar_base()
    anotar(f"preparar_base -> aviso={aviso!r} oferta={bool(oferta)}")
    app = agencia.App(root)
    root.update()
    anotar(f"Ventana: {root.winfo_width()}x{root.winfo_height()} estado={root.state()} título={root.title()!r}")

    @paso("recorrer pantallas del menú")
    def recorrer():
        for pagina in app.menu:
            app.mostrar(pagina)
            root.update()

    @paso("registrar cliente")
    def cliente():
        app.registrar("clientes")
        root.update()
        for campo in agencia.CAMPOS_CLIENTE:
            if campo[0] != agencia.SECCION:
                valor = valor_campo(campo)
                if valor is not None:
                    app.clientes.form.poner_valor(campo[0], valor)
        app.clientes.guardar(silencioso=True)
        root.update()
        if not app.db.todos("clientes"):
            raise AssertionError("El cliente no se guardó")

    @paso("registrar trabajadora")
    def trabajadora():
        app.registrar("trabajadoras")
        root.update()
        for campo in agencia.CAMPOS_TRABAJADORA:
            if campo[0] != agencia.SECCION:
                valor = valor_campo(campo)
                if valor is not None:
                    app.trabajadoras.form.poner_valor(campo[0], valor)
        app.trabajadoras.form.poner_valor("estado", "Disponible")
        app.trabajadoras.guardar(silencioso=True)
        root.update()
        if not app.db.todos("trabajadoras"):
            raise AssertionError("La trabajadora no se guardó")

    @paso("asignar y generar contrato")
    def asignar():
        cli = app.db.todos("clientes")[0]
        tra = app.db.todos("trabajadoras")[0]
        with app.db.lote():
            nuevo = app.db.insertar("colocaciones", {
                "cliente_id": str(cli["id"]), "trabajadora_id": str(tra["id"]),
                "fecha_enlace": time.strftime("%d/%m/%Y"), "estado": "Activa", "comision": "300.00",
                "sueldo_acordado": "1200", "garantia": "Sí", "meses_garantia": "2"})
        app.refrescar_todo()
        app.abrir_asignaciones(nuevo)
        root.update()
        c = app.db.uno("colocaciones", nuevo)
        documento = agencia.html_contrato(c, cli, tra)
        if "<html" not in documento.lower():
            raise AssertionError("Contrato sin HTML")
        for pagina in (app.contratos, app.comisiones, app.garantias, app.ganancias, app.areas):
            app.mostrar(pagina)
            root.update()

    @paso("abrir un área")
    def area():
        tipo = next(iter(agencia.AREAS))
        app.abrir_area(tipo)
        root.update()

    @paso("copia de seguridad en primer plano")
    def copia():
        resultado = app.hacer_copia("prueba", avisar=False)
        if not resultado["archivo"]:
            raise AssertionError(f"Sin copia: {resultado}")
        if resultado["errores"]:
            raise AssertionError(f"Errores de copia: {resultado['errores']}")
        anotar(f"copia: {resultado['archivo']} externas={resultado['externas']}")

    @paso("copia de seguridad en segundo plano")
    def copia_fondo():
        app.hacer_copia_en_segundo_plano("prueba-fondo")
        limite = time.monotonic() + 60
        while app._copiando and time.monotonic() < limite:
            root.update()
            time.sleep(0.05)
        if app._copiando:
            raise AssertionError("La copia en segundo plano no terminó")

    @paso("exportar CSV")
    def exportar():
        destino = os.path.join(DATOS, "exportacion-prueba")
        agencia.exportar_legible(agencia.DB_PATH, destino)
        archivos = os.listdir(destino)
        anotar(f"CSV: {archivos}")
        if not any(a.endswith(".csv") for a in archivos):
            raise AssertionError("No se generaron CSV")

    @paso("diálogo de copias y restauración")
    def restaurar():
        dialogo = agencia.DialogoCopias(root, app)
        root.update()
        dialogo.destroy()
        copias = agencia.listar_copias(agencia.carpetas_de_copias())
        if not copias:
            raise AssertionError("No hay copias listadas")
        if not app.restaurar_copia(copias[0]):
            raise AssertionError("restaurar_copia devolvió False")
        root.update()

    @paso("imprimir contrato (abre navegador)")
    def imprimir():
        c = app.db.todos("colocaciones")[0]
        app.contratos.imprimir_contrato(c)
        root.update()

    @paso("abrir carpeta de datos")
    def carpeta():
        if sys.platform == "win32":
            agencia.abrir_carpeta(agencia.CARPETA)

    for accion in (recorrer, cliente, trabajadora, asignar, area, copia, copia_fondo, exportar,
                   restaurar, imprimir, carpeta):
        accion()
        root.update()

    @paso("cerrar como la persona usuaria")
    def cerrar():
        app.cerrar()

    root.after(500, cerrar)
    root.after(20000, lambda: (fallo("La ventana no se cerró"), root.destroy()))
    root.mainloop()

    errores = os.path.join(DATOS, "errores.log")
    if os.path.exists(errores):
        with open(errores, encoding="utf-8", errors="replace") as archivo:
            fallo("errores.log:\n" + archivo.read())
    print("\n==== RESUMEN ====")
    print(f"{len(pasos)} pasos, {len(fallos)} fallos")
    for f in fallos:
        print("-", f)
    return 1 if fallos else 0


if __name__ == "__main__":
    try:
        codigo = main()
    except Exception:
        traceback.print_exc()
        codigo = 2
    sys.exit(codigo)
