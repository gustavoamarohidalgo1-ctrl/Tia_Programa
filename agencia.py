"""
Agencia de Empleo - programa para Windows.

Flujo: pedido del cliente (cuestionario) -> perfil de la trabajadora ->
buscar trabajadora -> entrevistas -> documentos -> contrato y porcentaje ->
garantía con cambio de personal.

Requiere solo Python 3 (trae tkinter y sqlite3). Los datos se guardan en
"agencia.db" y los contratos en la carpeta "contratos", junto a este archivo.
"""
import os
import re
import sys
import html
import math
import json
import sqlite3
import threading
import unicodedata
from contextlib import contextmanager
from decimal import Decimal, DecimalException, ROUND_HALF_EVEN, localcontext
from functools import lru_cache
from pathlib import Path
from datetime import datetime, date, timedelta

if sys.platform == "win32":  # Python incluido en el instalador: indicar dónde están los archivos de Tcl/Tk
    # Siempre los propios: si otro programa dejó TCL_LIBRARY en el entorno de Windows, apuntaría a otra
    # versión de Tcl y la ventana no podría abrirse («version conflict for package Tcl»).
    for _variable, _carpeta, _archivo in (("TCL_LIBRARY", "tcl8.6", "init.tcl"), ("TK_LIBRARY", "tk8.6", "tk.tcl")):
        _ruta = os.path.join(sys.base_prefix, "tcl", _carpeta)
        if os.path.isfile(os.path.join(_ruta, _archivo)):
            os.environ[_variable] = _ruta

try:
    import tkinter as tk
    import tkinter.font as tkfont
    from tkinter import ttk, messagebox
except ImportError:  # Python sin tkinter: avisar en vez de cerrarse sin decir nada (pyw no tiene consola)
    _AVISO = ("Este Python no incluye tkinter, que el programa necesita.\n\nReinstale Python desde "
              "https://www.python.org/downloads/ y deje marcada la opción «tcl/tk and IDLE».")
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, _AVISO, "Agencia de Empleos", 0x10)
    except Exception:
        print(_AVISO, file=sys.stderr)
    raise SystemExit(1)

# ---------------------------------------------------------------- Configuración
AGENCIA_NOMBRE = "Agencia de Empleos"
AGENCIA_ESLOGAN = "Servicio Exclusivo"
AGENCIA_RUC = "10436157334"
AGENCIA_DOMICILIO = ("Av. Nicolás Ayllón N° 5695, 3er piso, oficina 304, distrito de Ate, "
                     "provincia y departamento de Lima")
CIUDAD_CONTRATO = "Lima"
MONEDA = "S/"
COBRO_DEFECTO = "300.00"   # lo que paga el empleador a la agencia, por única vez (si no se usa un porcentaje)
PORCENTAJE_DEFECTO = None  # p. ej. 20: la comisión propuesta sería el 20 % del sueldo; None = usar COBRO_DEFECTO
                           # (en cada contrato se puede cambiar el monto o el porcentaje)
MESES_GARANTIA = 2         # garantía por defecto, en meses (cada cliente puede acordar otra)
FMT_FECHA = "%d/%m/%Y"


def carpeta_app():
    """Dónde está el programa y sus recursos (logo, íconos)."""
    if getattr(sys, "frozen", False):  # programa empaquetado con PyInstaller
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def instalado_con_runtime(plataforma=None):
    """True si el programa está en una instalación de Windows: carpeta «app» junto a «runtime» con su Python.
    Vale aunque lo abra otro Python (p. ej. doble clic en app\\iniciar.pyw con un Python del sistema)."""
    plataforma = sys.platform if plataforma is None else plataforma
    if not plataforma.startswith("win"):
        return False
    app = carpeta_app()
    return (os.path.basename(os.path.normpath(app)).lower() == "app"
            and os.path.isfile(os.path.join(os.path.dirname(os.path.normpath(app)), "runtime", "pythonw.exe")))


def carpeta_datos(argv=None, entorno=None, plataforma=None, casa=None):
    """Dónde se guardan la base, los contratos, los respaldos y el registro de errores.

    Por orden: la opción --datos RUTA, la variable AGENCIA_DATOS, la carpeta del usuario si el programa
    está instalado (una app instalada no puede escribir junto a sí misma, y al actualizarla o desinstalarla
    se llevaría los datos) y, si no, la carpeta del programa, como siempre."""
    argv = sys.argv if argv is None else argv
    entorno = os.environ if entorno is None else entorno
    plataforma = sys.platform if plataforma is None else plataforma
    casa = os.path.expanduser("~") if casa is None else casa
    if "--datos" in argv[:-1]:
        return argv[argv.index("--datos") + 1]
    if entorno.get("AGENCIA_DATOS"):
        return entorno["AGENCIA_DATOS"]
    if not getattr(sys, "frozen", False) and instalado_con_runtime(plataforma):
        # Instalación de Windows abierta sin --datos (p. ej. doble clic en app\iniciar.pyw): los datos van a la
        # carpeta del usuario, como con el acceso directo, y nunca dentro de la carpeta del programa.
        return os.path.join(entorno.get("LOCALAPPDATA") or os.path.join(casa, "AppData", "Local"), AGENCIA_NOMBRE)
    if getattr(sys, "frozen", False):
        junto_al_programa = os.path.dirname(sys.executable)
        if os.path.exists(os.path.join(junto_al_programa, "agencia.db")):   # instalación antigua: datos junto al .exe
            return junto_al_programa
        if plataforma == "darwin":
            return os.path.join(casa, "Library", "Application Support", AGENCIA_NOMBRE)
        if plataforma.startswith("win"):
            return os.path.join(entorno.get("LOCALAPPDATA") or os.path.join(casa, "AppData", "Local"), AGENCIA_NOMBRE)
        return os.path.join(entorno.get("XDG_DATA_HOME") or os.path.join(casa, ".local", "share"), AGENCIA_NOMBRE)
    return carpeta_app()


RECURSOS = carpeta_app()
CARPETA = carpeta_datos()
DB_PATH = os.path.join(CARPETA, "agencia.db")
CARPETA_CONTRATOS = os.path.join(CARPETA, "contratos")
LOGO_PATH = os.path.join(RECURSOS, "logo.png")
ICONO_PNG = os.path.join(RECURSOS, "icono.png")   # ventana y Dock (Mac)
ICONO_ICO = os.path.join(RECURSOS, "icono.ico")   # ventana y barra de tareas (Windows)
ERRORES_PATH = os.path.join(CARPETA, "errores.log")
CARPETA_RESPALDOS = os.path.join(CARPETA, "respaldos")

# Áreas de trabajo: tipo de servicio -> (título, descripción). Estas son las que trae el programa la primera vez;
# después la agencia crea y elimina las suyas (se guardan en la base de datos, tabla «areas») y AREAS y
# TIPOS_SERVICIO se llenan desde ahí (ver cargar_areas). Se modifican en el mismo lugar: quien las usa las ve al día.
AREAS_INICIALES = {
    "Niñera": ("Niñeras", "Cuidado de bebés y niños"),
    "Cama adentro": ("Cama adentro", "Vive en la casa del cliente"),
    "Cama afuera": ("Cama afuera", "Entra y sale cada día"),
    "Por días": ("Por días", "Limpieza algunos días a la semana"),
    "Cuidado de adulto mayor": ("Adulto mayor", "Cuidado y compañía"),
    "Cocinera": ("Cocina", "Preparación de comidas"),
}
AREAS = dict(AREAS_INICIALES)
TIPOS_SERVICIO = list(AREAS)   # lo que se elige en «Tipo de servicio» del cliente y «Especialidad» de la trabajadora
PEDIDOS_POR_ENLAZAR = ("Pendiente", "Buscando")  # clientes que aún esperan trabajadora
SI_NO = ["Sí", "No"]
ESTADOS_CLIENTE = ["Pendiente", "Buscando", "En entrevista", "Colocado", "Cancelado"]
ESTADOS_TRABAJADORA = ["Disponible", "En proceso", "Trabajando", "No disponible"]
# Garantía que puede acordar cada cliente (en el contrato se puede escribir cualquier número de meses)
OPCIONES_GARANTIA = ["Sin garantía"] + [f"{n} mes" if n == 1 else f"{n} meses" for n in range(1, 7)]

# Estado del enlace -> (estado de la trabajadora, estado del cliente)
SINCRONIZAR_ESTADOS = {
    "En proceso": ("En proceso", "En entrevista"),
    "Activa": ("Trabajando", "Colocado"),
    "Garantía cumplida": ("Trabajando", "Colocado"),
    "Reemplazo solicitado": ("Disponible", "Buscando"),
    "Cancelada": ("Disponible", "Buscando"),
}


# ---------------------------------------------------------------- Utilidades
def hoy():
    return date.today().strftime(FMT_FECHA)


@lru_cache(maxsize=4096)  # las mismas fechas se leen muchas veces al dibujar las listas
def leer_fecha(texto):
    try:
        return datetime.strptime((texto or "").strip(), FMT_FECHA).date()
    except ValueError:
        return None


def leer_numero(texto):
    """Número finito compatible con la API numérica de las pantallas."""
    if isinstance(texto, (int, float, Decimal)):
        try:
            numero = float(texto)
        except (ValueError, TypeError, OverflowError):
            return None
        return numero if math.isfinite(numero) else None
    return _leer_numero_texto(texto or "", MONEDA) if isinstance(texto, (str, type(None))) else None


def _normalizar_numero_texto(texto, moneda):
    limpio = texto.replace(moneda, "").replace(" ", "").replace("\u00a0", "")
    coma, punto = limpio.rfind(","), limpio.rfind(".")
    if coma >= 0 and punto >= 0:
        decimal, miles = (",", ".") if coma > punto else (".", ",")
        limpio = limpio.replace(miles, "").replace(decimal, ".")
    elif coma >= 0:
        limpio = limpio.replace(",", "" if re.fullmatch(r"-?\d{1,3}(,\d{3})+", limpio) else ".")
    elif limpio.count(".") > 1:
        limpio = limpio.replace(".", "")
    return limpio


@lru_cache(maxsize=4096)
def _leer_numero_texto(texto, moneda):
    try:
        numero = float(_normalizar_numero_texto(texto, moneda))
        return numero if math.isfinite(numero) else None
    except (ValueError, OverflowError):
        return None


def leer_decimal(texto):
    """Importe exacto con el mismo formato monetario; rechaza NaN, infinito y desbordamientos."""
    if isinstance(texto, str) or texto is None:
        return _leer_decimal_texto(texto or "", MONEDA)
    try:
        numero = texto if isinstance(texto, Decimal) else Decimal(str(texto))
        return numero if numero.is_finite() and leer_numero(numero) is not None else None
    except (DecimalException, ValueError, TypeError, OverflowError):
        return None


@lru_cache(maxsize=4096)
def _leer_decimal_texto(texto, moneda):
    try:
        numero = Decimal(_normalizar_numero_texto(texto, moneda))
        return numero if numero.is_finite() and leer_numero(numero) is not None else None
    except (DecimalException, ValueError, OverflowError):
        return None


def importe_texto(valor, decimales=2):
    """Redondeo decimal a par, como format/Python, sin el error de representación binaria."""
    numero = valor if isinstance(valor, Decimal) and valor.is_finite() else leer_decimal(valor)
    if numero is None:
        return None
    with localcontext() as contexto:
        contexto.rounding = ROUND_HALF_EVEN
        return f"{numero:.{decimales}f}"


def dinero_corto(texto):
    n = texto if isinstance(texto, Decimal) and texto.is_finite() else leer_decimal(texto)
    if n is None:
        return "-"
    with localcontext() as contexto:
        contexto.rounding = ROUND_HALF_EVEN
        return f"{MONEDA} {n:,.0f}"


def dinero(valor):
    n = valor if isinstance(valor, Decimal) and valor.is_finite() else leer_decimal(valor)
    if n is None:
        return "________"
    with localcontext() as contexto:
        contexto.rounding = ROUND_HALF_EVEN
        return f"{MONEDA} {n:,.2f}"


def resumen_ganancias(colocaciones, clientes, fecha_hoy=None):
    """Suma importes decimales exactos y conserva la API float en casos normales.

    Sin fecha válida, un cobro cuenta en total pero no en períodos ni historial.
    Se descartan cantidades nulas, negativas y no finitas. Si un total desborda
    float, todos los importes se devuelven como Decimal para conservar el valor.
    """
    fecha_hoy = fecha_hoy or date.today()
    filas_clientes = clientes.values() if isinstance(clientes, dict) else clientes
    cliente_por_id = {str(c.get("id")): c for c in filas_clientes}
    cero = Decimal(0)
    por_area = {titulo: cero for titulo, _ in AREAS.values()}
    meses_anio = [cero] * 12
    cobrado_total = por_cobrar = cobrado_semana = cobrado_mes = cobrado_anio = cero
    inicio_semana = fecha_hoy - timedelta(days=fecha_hoy.weekday())
    fin_semana = inicio_semana + timedelta(days=6)
    historial = []

    with localcontext() as contexto:
        # Conserva centavos incluso al sumar cantidades cercanas al rango de float.
        contexto.prec = 340
        contexto.rounding = ROUND_HALF_EVEN
        for colocacion in colocaciones:
            try:
                monto = leer_decimal(colocacion.get("comision"))
            except (TypeError, ValueError, AttributeError, OverflowError):
                continue
            if monto is None or monto <= 0:
                continue
            if colocacion.get("comision_pagada") != "1":
                por_cobrar += monto
                continue

            cobrado_total += monto
            cliente_id = colocacion.get("cliente_id")
            cliente = cliente_por_id.get(str(cliente_id), {})
            tipo = cliente.get("tipo_servicio") or ""
            area = AREAS.get(tipo, (tipo or "Sin área",))[0]
            por_area[area] = por_area.get(area, cero) + monto

            fecha_texto = colocacion.get("fecha_pago")
            fecha_pago = leer_fecha(fecha_texto) if isinstance(fecha_texto, str) else None
            if fecha_pago is None:
                continue
            if inicio_semana <= fecha_pago <= fin_semana:
                cobrado_semana += monto
            if fecha_pago.year == fecha_hoy.year:
                cobrado_anio += monto
                meses_anio[fecha_pago.month - 1] += monto
                if fecha_pago.month == fecha_hoy.month:
                    cobrado_mes += monto
            historial.append({
                "id": colocacion.get("id"), "cliente_id": cliente_id,
                "trabajadora_id": colocacion.get("trabajadora_id"),
                "cliente": cliente.get("nombre") or "Cliente no disponible",
                "area": area, "fecha_pago": fecha_texto, "fecha": fecha_pago, "monto": monto,
            })

    totales = dict(cobrado_total=cobrado_total, por_cobrar=por_cobrar,
                   cobrado_semana=cobrado_semana, cobrado_mes=cobrado_mes, cobrado_anio=cobrado_anio)
    desborda = any(not math.isfinite(float(n)) for n in [*totales.values(), *por_area.values(), *meses_anio])
    convertir = (lambda n: n) if desborda else float
    historial.sort(key=lambda pago: pago["fecha"], reverse=True)
    for pago in historial:
        pago["monto"] = convertir(pago["monto"])
    return {**{clave: convertir(n) for clave, n in totales.items()},
            "meses_anio": [convertir(n) for n in meses_anio],
            "por_area": {area: convertir(n) for area, n in por_area.items()}, "historial": historial}


# ---------------------------------------------------------------- Campos
# Cada campo: (clave, etiqueta, tipo, opciones). Tipos: entry, text, combo,
# check, readonly, ref (lista de otra tabla). SECCION agrega un subtítulo.
SECCION = "--"

CAMPOS_CLIENTE = [
    (SECCION, "Datos del cliente"),
    ("nombre", "Nombre completo *"),
    ("dni", "DNI"),
    ("telefono", "Teléfono *"),
    ("ocupacion", "Ocupación"),
    ("direccion", "Dirección"),
    ("zona", "Zona / distrito"),
    ("fecha_registro", "Fecha de registro", "readonly"),
    (SECCION, "Cuestionario del pedido"),
    ("tipo_servicio", "Tipo de servicio", "autocompletar", TIPOS_SERVICIO),
    ("sueldo_ofrecido", f"Sueldo ofrecido ({MONEDA})"),
    ("horario", "Horario"),
    ("dias_libres", "Días libres"),
    ("personas_hogar", "Personas en el hogar"),
    ("ninos", "Niños (cantidad y edades)"),
    ("mascotas", "¿Tiene mascotas?", "combo", SI_NO),
    ("tareas", "Tareas a realizar", "text"),
    ("requisitos", "Requisitos (edad, experiencia...)", "text"),
    ("fecha_necesita", "¿Para cuándo la necesita?"),
    ("notas", "Notas", "text"),
]

DOCUMENTOS = [
    ("doc_dni", "Copia de DNI"),
    ("doc_antecedentes", "Certificado de antecedentes"),
    ("doc_salud", "Certificado de salud"),
    ("doc_domicilio", "Recibo de luz/agua (domicilio)"),
    ("doc_referencias", "Cartas de referencia"),
]

CAMPOS_TRABAJADORA = [
    (SECCION, "Perfil"),
    ("nombre", "Nombre completo *"),
    ("dni", "DNI"),
    ("telefono", "Teléfono *"),
    ("edad", "Edad"),
    ("direccion", "Dirección"),
    ("zona", "Zona / distrito"),
    ("tipo_servicio", "Especialidad", "autocompletar", TIPOS_SERVICIO),
    ("cama_adentro", "¿Acepta cama adentro?", "combo", SI_NO),
    ("experiencia", "Años de experiencia"),
    ("referencias", "Referencias (trabajos anteriores)", "text"),
    (SECCION, "Documentos"),
    *[(clave, texto, "check") for clave, texto in DOCUMENTOS],
    (SECCION, "Estado"),
    ("estado", "Estado", "combo", ESTADOS_TRABAJADORA),
    ("notas", "Notas", "text"),
]

# Enlace entre un cliente y una trabajadora (tabla "colocaciones"). Solo define las columnas.
CAMPOS_COLOCACION = [(clave, clave) for clave in (
    "cliente_id", "trabajadora_id", "fecha_enlace", "estado", "notas",
    "sueldo_acordado", "porcentaje", "comision", "comision_pagada", "fecha_pago",
    "contrato_firmado", "fecha_firma", "firma_cliente", "firma_trabajadora", "firma_agencia",
    "garantia", "meses_garantia", "fecha_inicio", "fin_garantia", "reemplazo_de",
    # datos que se imprimen en el contrato (se pueden revisar antes de imprimir)
    "fecha_contrato", "puesto", "modalidad", "descanso", "contrato_html")]


def claves(campos):
    return [c[0] for c in campos if c[0] != SECCION]


def etiqueta_de(campos, clave):
    for c in campos:
        if c[0] == clave:
            return partir_etiqueta(c[1])[0]
    return clave


def docs_presentados(t):
    return [texto for clave, texto in DOCUMENTOS if t.get(clave) == "1"]


NUMEROS = ("cero", "un", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez", "once",
           "doce", "trece", "catorce", "quince", "dieciséis", "diecisiete", "dieciocho", "diecinueve", "veinte",
           "veintiún", "veintidós", "veintitrés", "veinticuatro", "veinticinco", "veintiséis", "veintisiete",
           "veintiocho", "veintinueve")
DECENAS = {3: "treinta", 4: "cuarenta", 5: "cincuenta", 6: "sesenta", 7: "setenta", 8: "ochenta", 9: "noventa"}


@lru_cache(maxsize=4096)
def sin_acentos(texto):
    """Minúsculas y sin tildes, para comparar lo que se escribe: «NIÑERA», «niñera» y «ninera» son lo mismo."""
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn").casefold()


def filtrar_opciones(texto, opciones, sinonimos=None):
    """Opciones que coinciden con lo escrito (primero las que empiezan igual). `sinonimos(opción)` da otros
    nombres por los que también se puede buscar."""
    escrito = sin_acentos(texto.strip())
    if not escrito:
        return []
    empiezan, contienen = [], []
    for opcion in opciones:
        nombres = [sin_acentos(opcion)] + [sin_acentos(x) for x in (sinonimos(opcion) if sinonimos else ()) if x]
        if any(n.startswith(escrito) for n in nombres):
            empiezan.append(opcion)
        elif any(escrito in n for n in nombres):
            contienen.append(opcion)
    return empiezan + contienen


def sinonimos_de_area(nombre):
    return (AREAS.get(nombre, ("",))[0],)     # también se encuentra por su título («Cocina» -> «Cocinera»)


def area_de_texto(texto):
    """El área a la que se refiere lo escrito (por su nombre o su título, sin importar mayúsculas ni tildes)."""
    escrito = sin_acentos(texto.strip())
    for nombre, (titulo, _) in AREAS.items():
        if escrito in (sin_acentos(nombre), sin_acentos(titulo)):
            return nombre
    return None


def restablecer_areas():
    AREAS.clear()
    AREAS.update(AREAS_INICIALES)
    TIPOS_SERVICIO[:] = list(AREAS)


def cargar_areas(db):
    """Pone al día AREAS y TIPOS_SERVICIO con las áreas guardadas en la base (en el orden en que se crearon)."""
    filas = sorted(db.todos("areas"), key=lambda fila: fila["id"])
    if not filas:
        restablecer_areas()
        return
    AREAS.clear()
    AREAS.update({f["nombre"]: (f["titulo"] or f["nombre"], f["descripcion"]) for f in filas})
    TIPOS_SERVICIO[:] = list(AREAS)


def texto_meses(n):
    return "Sin garantía" if n == 0 else f"{n} mes" if n == 1 else f"{n} meses"


def numero_en_letras(n):
    """Como en el resto del contrato («treinta (30) días»): el plazo en letras y entre paréntesis en número."""
    if not isinstance(n, int) or n < 0:
        return str(n)
    if n < 30:
        return NUMEROS[n]
    if n < 100:
        return DECENAS[n // 10] + (f" y {NUMEROS[n % 10]}" if n % 10 else "")
    return "cien" if n == 100 else str(n)


def porcentaje_en_letras(porcentaje):
    """«veinte por ciento (20 %)»; con decimales solo en número («12.5 %»)."""
    valor = leer_decimal(porcentaje)
    if valor is None:
        return f"{porcentaje} %"
    if valor != int(valor):
        return f"{porcentaje} %"
    letras = numero_en_letras(int(valor))
    letras = {"un": "uno", "veintiún": "veintiuno"}.get(letras, letras)
    letras = letras[:-2] + "uno" if letras.endswith(" y un") else letras       # «treinta y un» -> «treinta y uno»
    return f"{letras} por ciento ({int(valor)} %)"


def meses_del_cliente(cli):
    """Meses de garantía que pidió el cliente. Los clientes de versiones anteriores solo tenían Sí/No."""
    texto = (cli.get("meses_garantia") or "").strip()
    numero = re.match(r"\d+", texto)
    if numero:
        return int(numero.group())
    if texto.lower().startswith("sin"):
        return 0
    return 0 if cli.get("garantia") == "No" else MESES_GARANTIA


def con_garantia(c):
    # los enlaces antiguos sin dato tienen garantía
    return c.get("garantia") != "No" and str(c.get("meses_garantia") or MESES_GARANTIA) != "0"


def meses_de_garantia(c):
    if not con_garantia(c):
        return 0
    try:
        return int(c.get("meses_garantia") or MESES_GARANTIA)
    except ValueError:
        return MESES_GARANTIA


def porcentaje_de(monto, sueldo):
    """Porcentaje exacto y finito del sueldo, redondeado a dos decimales."""
    m, s = leer_decimal(monto), leer_decimal(sueldo)
    if m is None or s is None or m < 0 or s <= 0:
        return ""
    with localcontext() as contexto:
        contexto.prec = 340
        contexto.rounding = ROUND_HALF_EVEN
        p = m / s * 100
    return "" if leer_numero(p) is None else importe_texto(p).rstrip("0").rstrip(".")


def monto_por_porcentaje(porcentaje, sueldo):
    """Comisión decimal con dos decimales; None para datos inválidos o desbordados."""
    p, s = leer_decimal(porcentaje), leer_decimal(sueldo)
    if p is None or s is None or p < 0 or s <= 0:
        return None
    with localcontext() as contexto:
        contexto.prec = 340
        contexto.rounding = ROUND_HALF_EVEN
        m = s * p / 100
    return None if leer_numero(m) is None else importe_texto(m)


def origen_garantia(c, alternativa=None):
    """Origen único ya acordado: contrato, enlace y, si faltan, la fecha alternativa."""
    return leer_fecha(c.get("fecha_contrato")) or leer_fecha(c.get("fecha_enlace")) or alternativa or date.today()


def validar_condiciones_financieras(datos):
    """Valida importes y, cuando están presentes, fecha y plazo del contrato."""
    comision = leer_decimal(datos.get("comision"))
    sueldo_texto = datos.get("sueldo_acordado")
    sueldo = leer_decimal(sueldo_texto)
    porcentaje_texto = datos.get("porcentaje")
    porcentaje = leer_decimal(porcentaje_texto)
    if comision is None or comision < 0:
        return "El pago a la agencia debe ser un número finito no negativo."
    if sueldo_texto not in (None, "") and (sueldo is None or sueldo <= 0):
        return "El sueldo debe ser un número finito positivo."
    if porcentaje_texto not in (None, "") and (porcentaje is None or porcentaje < 0):
        return "El porcentaje debe ser un número finito no negativo."
    if sueldo is not None and not porcentaje_de(comision, sueldo):
        return "La relación entre la comisión y el sueldo produce un porcentaje fuera del rango numérico."
    if porcentaje is not None and sueldo is not None and monto_por_porcentaje(porcentaje, sueldo) is None:
        return "El porcentaje y el sueldo producen un importe fuera del rango numérico."
    if "fecha_contrato" in datos and not leer_fecha(datos.get("fecha_contrato")):
        return "Escriba la fecha del contrato así: dd/mm/aaaa."
    if "meses_garantia" in datos or "dias_garantia" in datos:
        try:
            meses = int(datos.get("meses_garantia") or 0)
            dias = int(datos.get("dias_garantia") or 0)
            if meses < 0 or dias < 0:
                raise ValueError
            for clave, cantidad in (("meses_garantia", meses), ("dias_garantia", dias)):
                valor = datos.get(clave)
                if valor not in (None, "") and not isinstance(valor, str) and valor != cantidad:
                    raise ValueError
            plazo = dict(datos, meses_garantia=str(meses), dias_garantia=str(dias))
            vencimiento_garantia(origen_garantia(datos), plazo)
        except (ValueError, TypeError, OverflowError):
            return "El plazo de garantía debe ser entero no negativo y producir una fecha dentro del rango admitido."
    return None


def sumar_meses(fecha, meses):
    """Misma fecha N meses después; rechaza fechas fuera del calendario admitido."""
    try:
        cantidad = int(meses)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("Los meses deben ser un número entero.") from None
    if cantidad != meses:
        raise ValueError("Los meses deben ser un número entero.")
    total = fecha.month - 1 + cantidad
    anio, mes = fecha.year + total // 12, total % 12 + 1
    if not 1 <= anio <= 9999:
        raise ValueError("El plazo produce una fecha fuera del rango admitido.")
    dias_mes = [31, 29 if anio % 4 == 0 and (anio % 100 or anio % 400 == 0) else 28,
                31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mes - 1]
    return date(anio, mes, min(fecha.day, dias_mes))


def vencimiento_garantia(inicio, c):
    """Vencimiento por los meses acordados; None cuando no hay garantía."""
    return sumar_meses(inicio, meses_de_garantia(c)) if con_garantia(c) else None


def inicio_por_firma(c):
    """Datos de inicio que produce un contrato firmado: el trabajo y la garantía
    corren desde la fecha del contrato. None si no corresponde iniciar."""
    if c.get("estado") != "En proceso" or c.get("contrato_firmado") != "1":
        return None
    inicio = origen_garantia(c)
    datos = {"fecha_inicio": inicio.strftime(FMT_FECHA), "estado": "Activa"}
    if con_garantia(c):
        datos["fin_garantia"] = vencimiento_garantia(inicio, c).strftime(FMT_FECHA)
    return datos


def plural(n, uno, varios):
    return f"{n} {uno if n == 1 else varios}"


def describir_perdida(enlaces):
    """Aviso de lo valioso que se perdería al borrar asignaciones: comisiones ya cobradas y contratos firmados."""
    cobradas = [monto for c in enlaces if c["comision_pagada"] == "1"
                if (monto := leer_decimal(c["comision"])) is not None and monto > 0]
    firmadas = [c for c in enlaces if c["contrato_firmado"] == "1"]
    partes = []
    if cobradas:
        with localcontext() as contexto:
            contexto.prec = 340
            total = sum(cobradas, Decimal(0))
        partes.append(f"{plural(len(cobradas), 'comisión cobrada', 'comisiones cobradas')} ({dinero(total)})")
    if firmadas:
        partes.append(plural(len(firmadas), "contrato firmado", "contratos firmados"))
    if not partes:
        return ""
    return ("\n\n⚠ Se perderían " + " y ".join(partes) + ", y dejarían de contarse en Comisiones y Ganancias.")


def situacion_garantia(c, reemplazos_atendidos):
    """Texto de la garantía de un enlace y si está pendiente."""
    if not con_garantia(c):
        return "Sin garantía", False
    if c["estado"] == "Reemplazo solicitado":
        if str(c["id"]) in reemplazos_atendidos:
            return "Reemplazada", False
        return "Reemplazo por atender", True
    if c["estado"] == "En proceso":
        return "Sin iniciar", True
    fin = leer_fecha(c["fin_garantia"])
    if c["estado"] == "Activa" and fin:
        dias = (fin - date.today()).days
        if dias >= 0:
            return ("Vence hoy" if dias == 0 else f"Quedan {dias} día{'' if dias == 1 else 's'}"), True
    return "Cumplida", False


def html_firma(dato):
    """Muestra una firma con nombre o los trazos de una firma anterior."""
    try:
        firma = json.loads(dato)
    except (TypeError, ValueError):
        return ""
    if not isinstance(firma, dict):
        return ""
    if firma.get("tipo") == "nombre":
        nombre = firma.get("texto")
        if not isinstance(nombre, str) or not nombre.strip():
            return ""
        nombre = nombre.strip()
        tamano = 26 if len(nombre) <= 18 else 23 if len(nombre) <= 25 else 20 if len(nombre) <= 33 else 17
        return (f'<span class="nombre-firma" style="font-size:{tamano}pt">'
                f'{html.escape(nombre)}</span>')
    ancho, alto = firma.get("w"), firma.get("h")
    if (type(ancho) not in (int, float) or type(alto) not in (int, float)
            or not 0 < ancho <= 10000 or not 0 < alto <= 10000
            or not isinstance(firma.get("trazos"), list)):
        return ""
    trazos = "".join(
        '<polyline points="' + " ".join(f"{x},{y}" for x, y in zip(t[::2], t[1::2])) + '"/>'
        for t in firma["trazos"]
        if (isinstance(t, list) and len(t) >= 4 and len(t) % 2 == 0
            and all(type(v) in (int, float) and -1000000 <= v <= 1000000 for v in t)))
    if not trazos:
        return ""
    return (f'<svg class="firma" viewBox="0 0 {ancho} {alto}" '
            'preserveAspectRatio="xMidYMid meet"><g fill="none" stroke="#13213F" stroke-width="2.5" '
            f'stroke-linecap="round" stroke-linejoin="round">{trazos}</g></svg>')


# ---------------------------------------------------------------- Base de datos
# Datos del cliente que el programa maneja solo y no se piden en el formulario: el estado del pedido lo cambia
# el propio flujo (pendiente, en entrevista, colocado...) y los meses de garantía se acuerdan en el contrato.
CAMPOS_OCULTOS_CLIENTE = [("estado", "estado"), ("meses_garantia", "meses_garantia")]

TABLAS = {
    "clientes": CAMPOS_CLIENTE + CAMPOS_OCULTOS_CLIENTE,
    "trabajadoras": CAMPOS_TRABAJADORA,
    "colocaciones": CAMPOS_COLOCACION,
}


class BaseDatos:
    def __init__(self, ruta):
        # Espera hasta 30 s si otra copia del programa está guardando (por defecto serían 5 s y fallaría el guardado)
        self.ruta = os.fspath(ruta)
        if self.ruta not in ("", ":memory:"):
            self.ruta = os.path.abspath(self.ruta)
        self.con = sqlite3.connect(ruta, timeout=30)
        self.con.row_factory = sqlite3.Row
        try:
            self.con.execute("PRAGMA synchronous = FULL")  # confirmar también en disco
            self.con.execute("PRAGMA fullfsync = ON")
            self._migrar()
        except BaseException:
            self.con.close()  # un arranque fallido no conserva conexiones ni bloqueos
            raise
        self.version = 0     # aumenta con cada cambio; sirve para saber si un cálculo guardado sigue valiendo
        self._memoria = {}   # tabla -> (filas, {id: fila})
        self._individuales = {}  # consultas por ID sin cargar la tabla entera
        self._posiciones = {}    # posiciones de la última lista entregada
        self._listas_pendientes = {}  # IDs que cambiaron desde esa lista
        self._revision = {}  # tabla -> número que aumenta con cada cambio de esa tabla
        self._registro = {}  # tabla -> últimos cambios [(revisión, «ins»/«act»/«del»/«todo», id)]
        self._en_lote = False
        self._numero_lote = 0
        self._version_externa = self._leer_version_externa()

    def _migrar(self):
        """Crea las tablas y agrega las columnas que falten (versiones antiguas o copias antiguas).
        Todo en una sola transacción: o se aplica entero o no se toca nada."""
        self.con.execute("BEGIN IMMEDIATE")  # reservar escritura antes de leer el esquema evita upgrade BUSY
        try:
            for tabla, campos in TABLAS.items():
                self.con.execute(f"CREATE TABLE IF NOT EXISTS {tabla} "
                                 "(id INTEGER PRIMARY KEY AUTOINCREMENT)")
                existentes = {r["name"] for r in self.con.execute(f"PRAGMA table_info({tabla})")}
                for clave in claves(campos):
                    if clave not in existentes:
                        self.con.execute(f"ALTER TABLE {tabla} ADD COLUMN {clave} TEXT DEFAULT ''")
            area_nueva = not self.con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'areas'").fetchone()
            self.con.execute("CREATE TABLE IF NOT EXISTS areas (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                             "nombre TEXT DEFAULT '', titulo TEXT DEFAULT '', descripcion TEXT DEFAULT '')")
            if area_nueva:    # solo la primera vez: si la agencia elimina áreas, no se vuelven a crear
                self.con.executemany("INSERT INTO areas (nombre, titulo, descripcion) VALUES (?, ?, ?)",
                                     [(nombre, titulo, descripcion) for nombre, (titulo, descripcion) in AREAS_INICIALES.items()])
            if "garantia" in {r["name"] for r in self.con.execute("PRAGMA table_info(clientes)")}:
                # clientes de versiones anteriores: su Sí/No de garantía pasa a meses (el dato viejo no se toca)
                self.con.execute("UPDATE clientes SET meses_garantia = CASE WHEN garantia = 'No' THEN ? ELSE ? END "
                                 "WHERE meses_garantia IS NULL OR meses_garantia = ''",
                                 (texto_meses(0), texto_meses(MESES_GARANTIA)))
            # Congela los contratos firmados heredados con las fichas todavía disponibles.
            # Un contrato con personas ausentes conserva sus datos sin inventar un documento.
            self.con.execute("CREATE INDEX IF NOT EXISTS idx_colocaciones_firma_sin_html ON colocaciones(id) "
                             "WHERE contrato_firmado = '1' AND (contrato_html IS NULL OR contrato_html = '')")
            firmados = self.con.execute("SELECT * FROM colocaciones WHERE contrato_firmado = '1' "
                                        "AND (contrato_html IS NULL OR contrato_html = '')").fetchall()
            for fila in firmados:
                contrato = self._fila(fila)
                cliente = self.con.execute("SELECT * FROM clientes WHERE id = ?", (contrato['cliente_id'],)).fetchone()
                trabajadora = self.con.execute("SELECT * FROM trabajadoras WHERE id = ?", (contrato['trabajadora_id'],)).fetchone()
                if cliente is not None and trabajadora is not None:
                    documento = html_contrato(contrato, self._fila(cliente), self._fila(trabajadora))
                    self.con.execute("UPDATE colocaciones SET contrato_html = ? WHERE id = ?", (documento, contrato['id']))
            self.con.commit()
        except BaseException:
            self.con.rollback()
            raise

    def restaurar_desde(self, ruta):
        """Migra la copia antes de publicarla y conserva el destino ante cualquier fallo."""
        import shutil
        import tempfile

        if self._en_lote or self.con.in_transaction:
            raise ValueError("No se puede restaurar durante una transacción pendiente.")
        if self.ruta not in ("", ":memory:") and misma_ruta(ruta, self.ruta):
            raise ValueError("La copia elegida es la misma base que está abierta.")
        origen = conexion_lectura(ruta, timeout=10)
        temporal = None
        preparada = resguardo = None
        conservar_resguardo = False
        try:
            tablas = {r[0] for r in origen.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not tablas.intersection(TABLAS) or origen.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise sqlite3.DatabaseError("La copia no contiene una base de la agencia válida.")
            for tabla in tablas.intersection(set(TABLAS) | {"areas"}):
                columnas = origen.execute(f"PRAGMA table_info({tabla})").fetchall()
                primaria = [r for r in columnas if r[5]]
                indice_primario = any(r[3] == "pk" for r in origen.execute(f"PRAGMA index_list({tabla})"))
                if (len(primaria) != 1 or primaria[0][1] != "id" or primaria[0][2].upper() != "INTEGER"
                        or indice_primario):  # DESC/compuesta/WITHOUT ROWID no generan IDs como esta app
                    raise sqlite3.DatabaseError("La copia tiene una tabla sin identificadores compatibles.")
            temporal = tempfile.mkdtemp(prefix="agencia-restauracion-")
            preparada = sqlite3.connect(os.path.join(temporal, "preparada.db"), timeout=10)
            preparada.row_factory = sqlite3.Row
            _copiar_sqlite(origen, preparada)
            preparada.execute("PRAGMA journal_mode = DELETE")  # la copia debe ser legible sin WAL/SHM laterales
            migradora = type(self).__new__(type(self))
            migradora.con = preparada
            migradora._migrar()
            resguardo_ruta = os.path.join(temporal, "antes_de_restaurar.db")
            resguardo = sqlite3.connect(resguardo_ruta, timeout=10)
            _copiar_sqlite(self.con, resguardo)
            resguardo.execute("PRAGMA journal_mode = DELETE")
            try:
                _copiar_sqlite(preparada, self.con)
            except BaseException as error:
                try:
                    _copiar_sqlite(resguardo, self.con)
                except BaseException:
                    conservar_resguardo = True
                    self._olvidar_memoria()
                    self._cambio_desconocido()
                    self.version += 1
                    raise sqlite3.DatabaseError(
                        "La restauración y su recuperación fallaron. Se conserva la base anterior en: "
                        + resguardo_ruta) from error
                raise
        finally:
            origen.close()
            if preparada is not None:
                preparada.close()
            if resguardo is not None:
                resguardo.close()
            if temporal is not None and not conservar_resguardo:
                shutil.rmtree(temporal, ignore_errors=True)   # en Windows un antivirus puede retenerlo un momento
        self._version_externa = self._leer_version_externa()
        self._olvidar_memoria()
        self._cambio_desconocido()
        self.version += 1

    def _leer_version_externa(self):
        # SQLite cambia este número cuando OTRA conexión guarda algo en el archivo
        return self.con.execute("PRAGMA data_version").fetchone()[0]

    def cambio_externo(self):
        """True si otra copia abierta del programa guardó cambios; en ese caso olvida la memoria."""
        actual = self._leer_version_externa()
        if actual == self._version_externa:
            return False
        self._version_externa = actual
        self._olvidar_memoria()
        self._cambio_desconocido()
        self.version += 1
        return True

    def todos(self, tabla):
        """Todas las filas, de la más nueva a la más antigua.
        La lista es una instantánea: se conserva hasta el próximo cambio y sus filas no deben modificarse.
        Los cambios de un lote se incorporan juntos cuando se solicita otra instantánea."""
        if tabla not in self._memoria:
            individuales = self._individuales.pop(tabla, {})
            filas = []
            for registro in self.con.execute(f"SELECT * FROM {tabla} ORDER BY id DESC"):
                fila = self._fila(registro)
                anterior = individuales.get(fila["id"])
                filas.append(anterior if anterior is not None and anterior == fila else fila)
            self._memoria[tabla] = (filas, {f["id"]: f for f in filas})
            self._posiciones[tabla] = {f["id"]: i for i, f in enumerate(filas)}
            self._listas_pendientes.pop(tabla, None)
        elif tabla in self._listas_pendientes:
            filas, por_id = self._memoria[tabla]
            posiciones = self._posiciones[tabla]
            pendientes = self._listas_pendientes.pop(tabla)
            estructura_igual = all((id_ in por_id) == (id_ in posiciones) for id_ in pendientes)
            if estructura_igual:
                nuevas = list(filas)
                for id_ in pendientes:
                    if id_ in posiciones:
                        nuevas[posiciones[id_]] = por_id[id_]
            else:
                insertados = sorted((id_ for id_ in pendientes if id_ in por_id and id_ not in posiciones), reverse=True)
                nuevas = [por_id[id_] for id_ in insertados]
                nuevas.extend(por_id[f["id"]] for f in filas if f["id"] in por_id)
                self._posiciones[tabla] = {f["id"]: i for i, f in enumerate(nuevas)}
            self._memoria[tabla] = (nuevas, por_id)
        return self._memoria[tabla][0]

    @staticmethod
    def _fila(registro):
        # Leer los valores por posición evita buscar cada columna por nombre en sqlite3.Row.
        fila = dict(zip(registro.keys(), registro)) if isinstance(registro, sqlite3.Row) else dict(registro)
        if None in fila.values():   # un dato vacío (NULL) escrito desde fuera del programa no debe romper las pantallas
            fila.update({k: "" for k, v in fila.items() if v is None})
        return fila

    def _olvidar_memoria(self, tabla=None):
        for memoria in (self._memoria, self._individuales, self._posiciones, self._listas_pendientes):
            if tabla is None:
                memoria.clear()
            else:
                memoria.pop(tabla, None)

    def _poner_al_dia(self, tabla, tipo, id_):
        """Actualiza el índice por ID; copiar la lista se aplaza hasta el siguiente todos()."""
        completa = self._memoria.get(tabla)
        por_id = completa[1] if completa is not None else self._individuales.get(tabla)
        if por_id is None:
            return
        try:
            id_ = int(id_)
            if tipo == "del":
                por_id.pop(id_, None)
            else:
                if completa is None and id_ not in por_id:
                    return  # una fila no consultada no necesita entrar en la caché individual
                registro = self.con.execute(f"SELECT * FROM {tabla} WHERE id = ?", (id_,)).fetchone()
                if registro is None:
                    raise LookupError
                fila = self._fila(registro)
                if completa is not None:
                    if tipo == "ins" and completa[0] and id_ < completa[0][0]["id"]:
                        raise LookupError  # una inserción con ID manual requiere reconstruir el orden
                    if tipo == "act" and id_ not in por_id:
                        raise LookupError
                por_id[id_] = fila
        except (LookupError, TypeError, ValueError, OverflowError, sqlite3.Error):
            self._olvidar_memoria(tabla)
            return
        if completa is not None:
            self._listas_pendientes.setdefault(tabla, set()).add(id_)

    def uno(self, tabla, id_):
        try:
            id_ = int(id_)
        except (TypeError, ValueError, OverflowError):
            return None
        if not -(1 << 63) <= id_ < (1 << 63):
            return None  # SQLite no admite un ID fuera del rango de INTEGER PRIMARY KEY.
        if tabla in self._memoria:
            return self._memoria[tabla][1].get(id_)
        individuales = self._individuales.setdefault(tabla, {})
        if id_ not in individuales:
            registro = self.con.execute(f"SELECT * FROM {tabla} WHERE id = ?", (id_,)).fetchone()
            if registro is None:
                return None
            individuales[id_] = self._fila(registro)
        return individuales[id_]

    @contextmanager
    def lote(self):
        """Serializa decisiones entre instancias y protege confirmación y lotes anidados."""
        self._numero_lote += 1
        punto = f"lote_{self._numero_lote}"
        anterior = self._en_lote
        propia = not anterior and not self.con.in_transaction
        try:
            if propia:
                self.con.execute("BEGIN IMMEDIATE")
            self.con.execute(f"SAVEPOINT {punto}")
            self._en_lote = True
            if not anterior:
                self.cambio_externo()  # leer fichas actuales con la reserva de escritura tomada
            yield
            self.con.execute(f"RELEASE {punto}")
            if propia:
                self.con.commit()
            if not anterior:
                self.cambio_externo()
        except BaseException:
            try:
                self.con.execute(f"ROLLBACK TO {punto}")
                self.con.execute(f"RELEASE {punto}")
                if propia:
                    self.con.rollback()
            except sqlite3.Error:
                self.con.rollback()
            finally:
                self._olvidar_memoria()
                self._cambio_desconocido()
                self.version += 1
            raise
        finally:
            self._en_lote = anterior

    def _cambio(self, tabla, tipo="todo", id_=None):
        if not self._en_lote:
            try:
                self.con.commit()
            except BaseException:
                self.con.rollback()
                self._olvidar_memoria()
                self._cambio_desconocido()
                self.version += 1
                raise
            self.cambio_externo()  # incorpora escrituras ajenas anteriores al guardado local
        if tipo in ("ins", "act", "del"):
            self._poner_al_dia(tabla, tipo, id_)
        else:
            self._olvidar_memoria(tabla)
        self.version += 1
        revision = self._revision.get(tabla, 0) + 1
        self._revision[tabla] = revision
        registro = self._registro.setdefault(tabla, [])
        registro.append((revision, tipo, id_))
        del registro[:-64]

    def _cambio_desconocido(self):
        """Cambios que no se saben (otra copia del programa, reversión, restauración): todo se vuelve a leer."""
        for tabla in set(self._revision) | set(TABLAS) | {"areas"}:
            revision = self._revision.get(tabla, 0) + 1
            self._revision[tabla] = revision
            self._registro[tabla] = [(revision, "todo", None)]

    def revision(self, tabla):
        return self._revision.get(tabla, 0)

    def cambios_desde(self, tabla, revision):
        """[(tipo, id)] de los cambios de la tabla posteriores a esa revisión; None si no se pueden saber."""
        if revision == self._revision.get(tabla, 0):
            return []
        registro = self._registro.get(tabla, [])
        if not registro or registro[0][0] > revision + 1:
            return None
        return [(tipo, id_) for r, tipo, id_ in registro if r > revision]

    def _ejecutar_escritura(self, sql, parametros):
        """Una escritura rechazada no se confirma por accidente en el siguiente guardado."""
        punto = None
        if self._en_lote:
            self._numero_lote += 1
            punto = f"escritura_{self._numero_lote}"
            self.con.execute(f"SAVEPOINT {punto}")
        try:
            cursor = self.con.execute(sql, parametros)
            if punto is not None:
                self.con.execute(f"RELEASE {punto}")
            return cursor
        except BaseException:
            try:
                if punto is not None:
                    try:
                        self.con.execute(f"ROLLBACK TO {punto}")
                        self.con.execute(f"RELEASE {punto}")
                    except sqlite3.Error:
                        self.con.rollback()
                else:
                    self.con.rollback()
            finally:
                self._olvidar_memoria()
                self._cambio_desconocido()
                self.version += 1
            raise

    def insertar(self, tabla, datos):
        cols = list(datos)
        cur = self._ejecutar_escritura(
            f"INSERT INTO {tabla} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            [datos[c] for c in cols])
        self._cambio(tabla, "ins", cur.lastrowid)
        return cur.lastrowid

    def actualizar(self, tabla, id_, datos):
        cols = list(datos)
        self._ejecutar_escritura(f"UPDATE {tabla} SET {', '.join(c + ' = ?' for c in cols)} WHERE id = ?",
                         [datos[c] for c in cols] + [id_])
        self._cambio(tabla, "act", id_)

    def eliminar(self, tabla, id_):
        self._ejecutar_escritura(f"DELETE FROM {tabla} WHERE id = ?", (id_,))
        self._cambio(tabla, "del", id_)


# ---------------------------------------------------------------- Diseño
ES_WINDOWS = sys.platform.startswith("win")
FAMILIA = "Segoe UI" if ES_WINDOWS else "Avenir Next" if sys.platform == "darwin" else "DejaVu Sans"
BASE = 10 if ES_WINDOWS else 12
PAD = "  "  # sangría de las celdas de las tablas

# Superficies oscuras con una jerarquía clara. El logo y los acentos azul/rojo
# conservan los colores de la agencia.
C = {
    "fondo": "#1A293B",        # paneles elevados, tarjetas y ventanas
    "lateral": "#0B1522",      # navegación y zona de marca
    "suave": "#101D2C",        # lienzo de las páginas
    "campo": "#122235",        # entradas y listas desplegables
    "hover": "#253A51",
    "activo": "#243C58",
    "borde": "#304359",
    "barra": "#64788E",
    "tabla_alt": "#1D3045",
    "texto": "#F5F8FC",
    "texto2": "#D4E0EC",
    "tenue": "#9FB1C4",
    "acento": "#A5C7FF",       # azul claro legible sobre fondos oscuros
    "acento_osc": "#D1E2FF",
    "acento_suave": "#2B4B72",
    "azul_marca": "#1B4DB1",   # azul rey original para botones
    "azul_hover": "#2864D4",
    "logo_fondo": "#CBE3FB",   # respaldo celeste del logo transparente
    "rojo": "#E0282E",         # rojo original de la flecha
    "rojo_osc": "#BD1F27",
    "peligro": "#FF7B80",
    "peligro_suave": "#382632",
    "alerta": "#3D3221",
}

F = {
    "base": (FAMILIA, BASE),
    "pequena": (FAMILIA, BASE - 1),
    "seccion": (FAMILIA, BASE - 2, "bold"),
    "negrita": (FAMILIA, BASE, "bold"),
    "detalle": (FAMILIA, BASE + 5, "bold"),
    "titulo": (FAMILIA, BASE + 12, "bold"),
    "subtitulo": (FAMILIA, BASE),
    "marca": (FAMILIA, BASE + 2, "bold"),
    "eslogan": (FAMILIA, BASE - 1, "bold italic"),
    "numero": (FAMILIA, BASE + 3, "bold"),
}


def aplicar_tema(root):
    for nombre in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        try:
            tkfont.nametofont(nombre).configure(family=FAMILIA, size=BASE)
        except tk.TclError:
            pass
    root.configure(bg=C["fondo"])
    root.option_add("*TCombobox*Listbox.background", C["campo"])
    root.option_add("*TCombobox*Listbox.foreground", C["texto"])
    root.option_add("*TCombobox*Listbox.selectBackground", C["acento_suave"])
    root.option_add("*TCombobox*Listbox.selectForeground", C["texto"])
    root.option_add("*TCombobox*Listbox.font", F["base"])
    root.option_add("*TCombobox*Listbox.borderWidth", 0)

    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".", background=C["fondo"], foreground=C["texto"], font=F["base"],
                bordercolor=C["borde"], lightcolor=C["fondo"], darkcolor=C["fondo"],
                troughcolor=C["fondo"], focuscolor=C["fondo"], insertcolor=C["texto"],
                selectbackground=C["acento_suave"], selectforeground=C["texto"])
    s.configure("TFrame", background=C["fondo"])
    s.configure("Fondo.TFrame", background=C["suave"])
    s.configure("TLabel", background=C["fondo"], foreground=C["texto"])
    s.configure("Fondo.TLabel", background=C["suave"], foreground=C["texto"])
    s.configure("Tenue.TLabel", foreground=C["tenue"])
    s.configure("Pista.TLabel", foreground=C["tenue"], font=F["pequena"])
    s.configure("FondoPista.TLabel", background=C["suave"], foreground=C["tenue"],
                font=F["pequena"])
    s.configure("Etiqueta.TLabel", foreground=C["texto2"], font=F["base"])
    s.configure("Seccion.TLabel", foreground=C["acento"], font=F["seccion"])
    s.configure("Titulo.TLabel", font=F["titulo"])
    s.configure("Subtitulo.TLabel", foreground=C["tenue"], font=F["subtitulo"])
    s.configure("Detalle.TLabel", font=F["detalle"])
    s.configure("Aviso.TLabel", foreground=C["acento"])

    # Campos de texto y listas desplegables
    campo = dict(fieldbackground=C["campo"], bordercolor=C["borde"], lightcolor=C["campo"],
                 darkcolor=C["campo"], foreground=C["texto"], padding=(13, 9),
                 insertcolor=C["texto"], selectbackground=C["acento_suave"],
                 selectforeground=C["texto"])
    s.configure("TEntry", **campo)
    s.map("TEntry", bordercolor=[("focus", C["acento"])],
          fieldbackground=[("readonly", C["suave"]), ("disabled", C["suave"])],
          foreground=[("disabled", C["tenue"]), ("readonly", C["texto"])],
          lightcolor=[("readonly", C["suave"])], darkcolor=[("readonly", C["suave"])])
    s.configure("Busqueda.TEntry", fieldbackground=C["campo"], bordercolor=C["borde"],
                lightcolor=C["campo"], darkcolor=C["campo"], padding=(13, 9))
    s.map("Busqueda.TEntry", bordercolor=[("focus", C["acento"])],
          fieldbackground=[("focus", C["campo"])])
    s.configure("Pista.TEntry", fieldbackground=C["campo"], bordercolor=C["borde"],
                lightcolor=C["campo"], darkcolor=C["campo"], padding=(13, 9), foreground=C["tenue"])
    s.configure("TCombobox", **campo, background=C["campo"], arrowcolor=C["texto2"], arrowsize=13)
    s.map("TCombobox",
          fieldbackground=[("readonly", C["campo"]), ("disabled", C["suave"])],
          background=[("active", C["hover"]), ("readonly", C["campo"])],
          bordercolor=[("focus", C["acento"])],
          foreground=[("disabled", C["tenue"]), ("readonly", C["texto"])],
          selectbackground=[("readonly", C["campo"])], selectforeground=[("readonly", C["texto"])],
          lightcolor=[("focus", C["campo"])], darkcolor=[("focus", C["campo"])])

    # Botones planos
    def boton(estilo, fondo, texto, borde, hover, borde_hover=None, padding=(18, 9), fuente=F["base"]):
        s.configure(estilo, background=fondo, foreground=texto, bordercolor=borde,
                    lightcolor=fondo, darkcolor=fondo, focuscolor=fondo, padding=padding,
                    relief="flat", font=fuente, anchor="center")
        estados = [("disabled", C["borde"]), ("pressed", hover), ("active", hover)]
        s.map(estilo, background=estados, lightcolor=estados, darkcolor=estados, focuscolor=estados,
              bordercolor=[("disabled", C["borde"]), ("focus", C["acento"]),
                           ("active", borde_hover or borde)],
              foreground=[("disabled", C["tenue"])])

    boton("Primario.TButton", C["azul_marca"], "#FFFFFF", C["azul_marca"], C["azul_hover"],
          C["azul_hover"], fuente=F["negrita"])
    boton("Rojo.TButton", C["rojo"], "#FFFFFF", C["rojo"], C["rojo_osc"],
          C["rojo_osc"], fuente=F["negrita"])
    boton("Secundario.TButton", C["activo"], C["texto"], C["borde"], C["hover"], C["barra"])
    boton("Pequeno.TButton", C["activo"], C["texto2"], C["borde"], C["hover"], C["barra"],
          padding=(12, 7), fuente=F["pequena"])
    boton("Accion.TButton", C["fondo"], C["texto2"], C["borde"], C["hover"], C["barra"])
    boton("Peligro.TButton", C["fondo"], C["peligro"], C["fondo"], C["peligro_suave"],
          C["peligro_suave"], padding=(12, 8))
    boton("Enlace.TButton", C["fondo"], C["acento"], C["fondo"], C["fondo"], C["fondo"],
          padding=(0, 0), fuente=F["pequena"])
    s.map("Enlace.TButton", foreground=[("active", C["acento_osc"])])

    # Casillas
    s.configure("TCheckbutton", background=C["fondo"], foreground=C["texto"], padding=(0, 3),
                indicatorbackground=C["campo"], indicatorforeground="#FFFFFF",
                upperbordercolor=C["barra"], lowerbordercolor=C["barra"],
                indicatormargin=(0, 0, 8, 0), focuscolor=C["fondo"])
    s.map("TCheckbutton", background=[("active", C["fondo"])],
          foreground=[("disabled", C["tenue"])],
          indicatorbackground=[("selected", C["azul_marca"]), ("active", C["hover"])],
          upperbordercolor=[("selected", C["azul_marca"])],
          lowerbordercolor=[("selected", C["azul_marca"])])

    # Tablas
    alto = tkfont.Font(font=F["base"]).metrics("linespace") + 19
    s.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    s.configure("Treeview", background=C["fondo"], fieldbackground=C["fondo"],
                foreground=C["texto"], borderwidth=0, rowheight=alto, font=F["base"])
    s.map("Treeview", background=[("selected", C["acento_suave"])],
          foreground=[("selected", C["texto"])])
    s.configure("Treeview.Heading", background=C["activo"], foreground=C["texto2"],
                font=F["seccion"], relief="flat", borderwidth=0, padding=(0, 10, 0, 11),
                bordercolor=C["fondo"], lightcolor=C["fondo"], darkcolor=C["fondo"])
    s.map("Treeview.Heading", background=[("active", C["hover"])])

    # Barra de desplazamiento fina, sin flechas
    s.layout("Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {
        "sticky": "ns", "children": [("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
    s.configure("Vertical.TScrollbar", troughcolor=C["fondo"], background=C["barra"],
                bordercolor=C["fondo"], lightcolor=C["barra"], darkcolor=C["barra"],
                arrowsize=7, gripcount=0, relief="flat")
    s.map("Vertical.TScrollbar", background=[("active", C["barra"])],
          lightcolor=[("active", C["barra"])], darkcolor=[("active", C["barra"])])
    s.layout("Horizontal.TScrollbar", [("Horizontal.Scrollbar.trough", {
        "sticky": "we", "children": [("Horizontal.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
    s.configure("Horizontal.TScrollbar", troughcolor=C["campo"], background=C["barra"],
                bordercolor=C["campo"], lightcolor=C["barra"], darkcolor=C["barra"],
                arrowsize=7, gripcount=0, relief="flat")
    s.map("Horizontal.TScrollbar", background=[("active", C["acento"])],
          lightcolor=[("active", C["acento"])], darkcolor=[("active", C["acento"])])


def poner_icono(root):
    """Ícono de la aplicación: barra de título y de tareas en Windows, Dock en Mac. Si falta el archivo
    el programa abre igual con el ícono por defecto."""
    if ES_WINDOWS:
        try:
            root.iconbitmap(default=ICONO_ICO)
            return
        except tk.TclError:
            pass
    for ruta in (ICONO_PNG, LOGO_PATH):
        try:
            imagen = tk.PhotoImage(file=ruta)
            root.iconphoto(True, imagen)
            root._icono = imagen    # tkinter no la conserva sola: sin esta referencia el ícono desaparece
            return
        except tk.TclError:
            continue


def maximizar(root):
    """Abre la ventana ocupando toda la pantalla (Windows, Mac y Linux)."""
    if sys.platform == "darwin":
        # En Mac "zoomed" espera la animación del sistema (~3 s); dar el tamaño directo es instantáneo
        root.geometry(f"{root.winfo_screenwidth()}x{root.winfo_screenheight()}+0+0")
        return
    try:
        root.state("zoomed")
    except tk.TclError:
        try:
            root.attributes("-zoomed", True)
        except tk.TclError:
            pass


def divisor(master, vertical=False):
    if vertical:
        return tk.Frame(master, bg=C["borde"], width=1)
    return tk.Frame(master, bg=C["borde"], height=1)


def subrayado(master, ancho=46):
    """Línea roja corta, como el subrayado del logo."""
    return tk.Frame(master, bg=C["rojo"], width=ancho, height=3)


def partir_etiqueta(texto):
    """'Sueldo (S/)' -> ('Sueldo', 'S/');  'Nombre *' -> ('Nombre', 'obligatorio')."""
    if texto.endswith(" *"):
        return texto[:-2], "obligatorio"
    if texto.endswith(")") and " (" in texto:
        principal, pista = texto.rsplit(" (", 1)
        return principal, pista[:-1]
    return texto, ""


def escala_pantalla(widget):
    """Escala de pantalla de Windows: 1.25 con «125 %», 1.5 con «150 %»... (1 en Mac y Linux).

    El programa pide a Windows texto nítido (SetProcessDpiAwareness), así que las letras crecen con la escala
    de la pantalla; los tamaños fijos de las ventanas, pensados para 96 ppp, se multiplican por este factor
    para que el contenido y sus botones sigan cabiendo."""
    if not ES_WINDOWS:
        return 1.0
    try:
        return max(1.0, float(widget.winfo_fpixels("1i")) / 96.0)
    except (tk.TclError, ValueError):
        return 1.0


def area_de_trabajo(widget):
    """(x, y, ancho, alto) de la pantalla sin la barra de tareas de Windows (en Mac y Linux, la pantalla entera)."""
    if ES_WINDOWS:
        try:
            import ctypes
            from ctypes import wintypes
            rect = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):   # SPI_GETWORKAREA
                if rect.right > rect.left and rect.bottom > rect.top:
                    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
        except Exception:
            pass
    return 0, 0, widget.winfo_screenwidth(), widget.winfo_screenheight()


def _marco_de_ventana(widget):
    """Alto aproximado de la barra de título y los bordes que Windows agrega a una ventana."""
    return round(40 * escala_pantalla(widget))


def _crecer_si_falta(ventana, ancho, alto):
    """Si el contenido de una ventana pide más espacio que el previsto, se agranda (sin salir del área visible)."""
    try:
        if not ventana.winfo_exists():
            return
        ventana.update_idletasks()
        _, _, ancho_util, alto_util = area_de_trabajo(ventana)
        nuevo_ancho = min(max(ancho, ventana.winfo_reqwidth()), ancho_util)
        nuevo_alto = min(max(alto, ventana.winfo_reqheight()), alto_util - _marco_de_ventana(ventana))
        if (nuevo_ancho, nuevo_alto) != (ancho, alto):
            ventana.geometry(f"{nuevo_ancho}x{nuevo_alto}")
    except tk.TclError:
        pass


def centrar(ventana, ancho, alto, sobre=None):
    """Tamaño (escalado con la pantalla) y posición centrada, siempre dentro del área visible: en Windows no se
    mete debajo de la barra de tareas, donde quedarían ocultos los botones de abajo."""
    factor = escala_pantalla(ventana)
    x0, y0, ancho_util, alto_util = area_de_trabajo(ventana)
    marco = _marco_de_ventana(ventana)
    ancho = min(round(ancho * factor), ancho_util)
    alto = min(round(alto * factor), alto_util - marco)
    if ES_WINDOWS and isinstance(ventana, tk.Toplevel):
        ventana.after_idle(lambda: _crecer_si_falta(ventana, ancho, alto))
    if sobre is not None:
        x = sobre.winfo_rootx() + (sobre.winfo_width() - ancho) // 2
        y = sobre.winfo_rooty() + (sobre.winfo_height() - alto) // 3
    else:
        x = x0 + (ancho_util - ancho) // 2
        y = y0 + (alto_util - alto) // 3
    x = min(max(x, x0), x0 + ancho_util - ancho)
    y = min(max(y, y0), y0 + alto_util - alto - marco)
    ventana.geometry(f"{ancho}x{alto}+{max(x, 0)}+{max(y, 0)}")


def pedir_texto(parent, titulo, pregunta, valor_inicial=""):
    """Pide un dato en una ventana que conserva el tema de la aplicación."""
    ventana = tk.Toplevel(parent)
    ventana.title(titulo)
    ventana.configure(bg=C["fondo"])
    ventana.resizable(False, False)
    ventana.transient(parent.winfo_toplevel())
    centrar(ventana, 480, 230, parent.winfo_toplevel())
    contenido = ttk.Frame(ventana, padding=(26, 24, 26, 22))
    contenido.pack(fill="both", expand=True)
    etiqueta = ttk.Label(contenido, text=pregunta, wraplength=round(420 * escala_pantalla(ventana)), justify="left")
    etiqueta.pack(anchor="w")
    valor = tk.StringVar(value=valor_inicial or "")
    entrada = ttk.Entry(contenido, textvariable=valor)
    entrada.pack(fill="x", pady=(16, 0))
    botones = ttk.Frame(contenido)
    botones.pack(side="bottom", fill="x", before=etiqueta)   # los botones se reservan primero: nunca quedan cortados
    resultado = [None]

    def aceptar(_evento=None):
        resultado[0] = valor.get()
        ventana.destroy()

    def cancelar(_evento=None):
        ventana.destroy()

    ttk.Button(botones, text="Aceptar", style="Primario.TButton",
               command=aceptar).pack(side="right")
    ttk.Button(botones, text="Cancelar", style="Secundario.TButton",
               command=cancelar).pack(side="right", padx=(0, 8))
    ventana.protocol("WM_DELETE_WINDOW", cancelar)
    ventana.bind("<Return>", aceptar)
    ventana.bind("<Escape>", cancelar)
    ventana.grab_set()
    entrada.focus_set()
    ventana.wait_window()
    return resultado[0]


# ---------------------------------------------------------------- Widgets
class MarcoDesplazable(ttk.Frame):
    """Marco con barra de desplazamiento vertical para formularios largos."""

    def __init__(self, master, padding=(28, 16, 24, 24)):
        super().__init__(master)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0, bg=C["fondo"])
        barra = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.interior = ttk.Frame(self.canvas, padding=padding)
        ventana = self.canvas.create_window((0, 0), window=self.interior, anchor="nw")
        self.interior.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(ventana, width=e.width))
        self.canvas.configure(yscrollcommand=barra.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        barra.pack(side="right", fill="y", padx=(0, 6))

    def activar_rueda(self):
        """Dirige la rueda y el trackpad al formulario, incluso sobre sus campos."""
        etiqueta = f"MarcoDesplazable{id(self)}"
        self.bind_class(etiqueta, "<MouseWheel>", self._rueda)
        self.bind_class(etiqueta, "<Button-4>", lambda e: self._rueda_unidades(-1, e.widget))
        self.bind_class(etiqueta, "<Button-5>", lambda e: self._rueda_unidades(1, e.widget))
        if tk.TkVersion >= 8.7:
            self.bind_class(etiqueta, "<TouchpadScroll>", self._trackpad)

        def incluir(widget):
            widget.bindtags((etiqueta,) + widget.bindtags())
            for hijo in widget.winfo_children():
                incluir(hijo)

        incluir(self)

    @staticmethod
    def _texto_desplazable(widget, hacia_abajo):
        if not isinstance(widget, tk.Text):
            return False
        inicio, fin = widget.yview()
        return fin < 1 if hacia_abajo else inicio > 0

    def _rueda_unidades(self, pasos, widget=None):
        if self._texto_desplazable(widget, pasos > 0):
            return
        self.canvas.yview_scroll(pasos, "units")
        return "break"

    def _rueda(self, e):
        if not e.delta:
            return
        pasos = int(-e.delta / 120) or (-1 if e.delta > 0 else 1)
        return self._rueda_unidades(pasos, e.widget)

    def _trackpad(self, e):
        _, delta_y = self.tk.call("tk::PreciseScrollDeltas", e.delta)
        if not delta_y:
            return
        if self._texto_desplazable(e.widget, delta_y < 0):
            return
        limites = self.canvas.bbox("all")
        if not limites:
            return
        alto = limites[3] - limites[1]
        if alto > 0:
            pixeles = float(self.tk.call("tk::ScaleNum", delta_y))
            self.canvas.yview_moveto(self.canvas.yview()[0] - pixeles / alto)
        return "break"

    def arriba(self):
        self.canvas.yview_moveto(0)


class CampoBusqueda(ttk.Entry):
    """Caja de búsqueda con texto de ayuda gris cuando está vacía.
    Filtra cuando se deja de escribir un instante, no con cada letra."""
    ESPERA_MS = 180

    def __init__(self, master, al_cambiar, pista):
        self.var = tk.StringVar()
        super().__init__(master, textvariable=self.var)
        self.pista, self.al_cambiar = pista, al_cambiar
        self._programado = None
        self.var.trace_add("write", lambda *a: None if self.vacio else self._programar())
        self.bind("<FocusIn>", self._entrar)
        self.bind("<FocusOut>", self._salir)
        self._mostrar_pista()

    def _programar(self):
        if self._programado:
            self.after_cancel(self._programado)
        self._programado = self.after(self.ESPERA_MS, self.aplicar)

    def aplicar(self):
        self._programado = None
        self.al_cambiar()

    def texto(self):
        return "" if self.vacio else self.var.get()

    def _mostrar_pista(self):
        self.vacio = True
        self.configure(style="Pista.TEntry")
        self.var.set(self.pista)

    def _entrar(self, _evento=None):
        if self.vacio:
            self.var.set("")
            self.vacio = False
            self.configure(style="Busqueda.TEntry")

    def _salir(self, _evento=None):
        if not self.var.get():
            self._mostrar_pista()


class ComboAutocompletar(ttk.Combobox):
    """Lista desplegable que además se puede escribir: mientras se escribe sugiere las opciones que coinciden
    (sin importar mayúsculas ni tildes) y con las flechas y Enter se elige. La flecha abre la lista completa.

    Las sugerencias forman parte del formulario (aparecen justo debajo del campo empujando lo de abajo) y no se
    dibujan encima de la pantalla: una lista superpuesta dejaba en macOS un residuo pintado al cerrarse, y al
    desplazar el formulario se separaba del campo.

    Escribir es siempre lo primero. Tk abre por su cuenta el menú de macOS con un clic en cualquier parte del campo
    que no sea justo el texto (bordes, relleno), y ese menú bloquea el teclado. Aquí ese menú nunca se abre: solo la
    flecha del campo (o la tecla Abajo) muestra la lista completa, dentro del formulario y sin quitar el teclado."""
    MAXIMO = 6            # líneas que se ven de las sugerencias mientras se escribe
    MAXIMO_TODAS = 8      # líneas que se ven al mostrar la lista completa
    TECLAS_QUE_NO_ESCRIBEN = {"Up", "Down", "Left", "Right", "Home", "End", "Return", "KP_Enter", "Escape", "Tab",
                              "ISO_Left_Tab", "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R",
                              "Meta_L", "Meta_R", "Caps_Lock", "Command"}

    def __init__(self, master, sinonimos=None, **opciones):
        super().__init__(master, **opciones)
        self.sinonimos = sinonimos
        self.lista = None
        self.sugeridas = []
        self.indice = -1
        self._tarea = None
        self._avisos = 0           # comprobaciones seguidas en que el campo perdió el teclado
        self.bind("<KeyRelease>", self._tecla, add="+")
        self.bind("<Up>", lambda e: self._mover(-1), add="+")
        self.bind("<Down>", lambda e: self._mover(1), add="+")
        self.bind("<Return>", self._aceptar, add="+")
        self.bind("<Escape>", lambda e: self._cerrar(), add="+")
        self.bind("<FocusOut>", self._salio, add="+")
        for secuencia, modo in (("<Button-1>", ""), ("<Shift-Button-1>", "mayus"), ("<Double-Button-1>", "doble"),
                                ("<Triple-Button-1>", "triple")):
            self.bind(secuencia, lambda e, m=modo: self._pulsar(e, m))     # antes que el «Press» de Tk, que abre el menú
        self.bind("<B1-Motion>", self._arrastrar)
        self.bind("<Alt-Down>", lambda e: self._alternar_lista() or "break")
        self.bind("<<ComboboxSelected>>", lambda e: self._cerrar(), add="+")
        self.bind("<Unmap>", lambda e: self._cerrar(), add="+")
        self.bind("<Destroy>", lambda e: self._cerrar(), add="+")
        # un clic en un fondo no le quita el foco al campo: hay que cerrar las sugerencias al hacer clic en otro lado
        self.winfo_toplevel().bind("<Button-1>", self._clic_fuera, add="+")

    def opciones(self):
        return list(self.tk.splitlist(self.cget("values")))

    def _elemento(self, x, y):
        """Parte del campo que hay en esa posición («textarea», «downarrow», el relleno...)."""
        return str(self.tk.call(str(self), "identify", "element", x, y))

    def _pulsar(self, evento, modo=""):
        """Clic: en la flecha muestra la lista completa; en cualquier otra parte solo sirve para escribir."""
        self.focus_set()
        if self._elemento(evento.x, evento.y).endswith("downarrow"):
            self._alternar_lista()
            return "break"
        self._cerrar()
        entrada = "ttk::entry::"
        try:
            if modo == "mayus":
                self.tk.call(entrada + "Shift-Press", str(self), evento.x)
            elif modo in ("doble", "triple"):
                self.tk.call(entrada + "Select", str(self), evento.x, "word" if modo == "doble" else "line")
            else:
                self.tk.call(entrada + "Press", str(self), evento.x)             # el cursor donde se hizo clic
        except tk.TclError:
            pass
        return "break"

    def _arrastrar(self, evento):
        try:
            self.tk.call("ttk::entry::Drag", str(self), evento.x)                # seleccionar texto arrastrando
        except tk.TclError:
            pass
        return "break"

    def _alternar_lista(self):
        if self._abierta():
            self._cerrar()
        elif self.opciones():
            self._mostrar(self.opciones(), self.MAXIMO_TODAS)

    def _tecla(self, evento):
        if evento.keysym in self.TECLAS_QUE_NO_ESCRIBEN:
            return
        coincidencias = filtrar_opciones(self.get(), self.opciones(), self.sinonimos)
        exacta = len(coincidencias) == 1 and sin_acentos(coincidencias[0]) == sin_acentos(self.get().strip())
        if coincidencias and not exacta:
            self._mostrar(coincidencias)
        else:
            self._cerrar()

    def _mostrar(self, opciones, lineas=None):
        if self.lista is None:
            self.lista = tk.Listbox(self.master, activestyle="none", exportselection=False, takefocus=0,
                                    relief="flat", borderwidth=0, highlightthickness=1,
                                    highlightbackground=C["acento"], highlightcolor=C["acento"], bg=C["campo"],
                                    fg=C["texto"], selectbackground=C["acento_suave"],
                                    selectforeground=C["texto"], font=F["base"])
            self.lista.bind("<Button-1>", self._clic)
        self.sugeridas = list(opciones)
        self.lista.delete(0, "end")
        self.lista.insert("end", *self.sugeridas)
        self.lista.configure(height=min(len(self.sugeridas), lineas or self.MAXIMO))
        self.indice = -1
        self._avisos = 0
        if not self._abierta():
            self.lista.pack(fill="x", pady=(2, 0), after=self)       # justo debajo del campo, dentro del formulario
        if self._tarea is None:
            self._tarea = self.after(120, self._vigilar)

    def _abierta(self):
        try:
            return self.lista is not None and self.lista.winfo_manager() == "pack"
        except tk.TclError:
            return False

    def _vigilar(self):
        """Mientras hay sugerencias: se cierran si el campo pierde el teclado (por ejemplo al cambiar de pantalla)."""
        self._tarea = None
        if not self._abierta():
            return
        try:
            fuera = not self._tiene_foco()
        except tk.TclError:
            fuera = True
            self._avisos = 99
        # se exigen dos comprobaciones seguidas para no reaccionar a un parpadeo del foco
        self._avisos = self._avisos + 1 if fuera else 0
        if self._avisos >= 2:
            self._cerrar()
            return
        self._tarea = self.after(120, self._vigilar)

    def _foco_actual(self):
        return str(self.tk.call("focus"))

    def _tiene_foco(self):
        return self._foco_actual() == str(self)

    def _clic_fuera(self, evento):
        if self._abierta() and evento.widget not in (self, self.lista):
            self._cerrar()

    def _mover(self, paso):
        if not self._abierta():
            if paso > 0:
                self._alternar_lista()                    # sin sugerencias, Abajo muestra la lista completa
            return "break"
        n = len(self.sugeridas)
        self.indice = n - 1 if self.indice == -1 and paso < 0 else (self.indice + paso) % n
        self.lista.selection_clear(0, "end")
        self.lista.selection_set(self.indice)
        self.lista.see(self.indice)
        return "break"

    def _aceptar(self, _evento):
        if not self._abierta():
            return None
        self._elegir(max(self.indice, 0))                 # Enter sin haber movido la selección: la primera sugerencia
        return "break"

    def _clic(self, evento):
        i = self.lista.nearest(evento.y)
        if 0 <= i < len(self.sugeridas):
            self._elegir(i)
        return "break"                                    # el clic no le quita el foco al campo

    def _elegir(self, i):
        self.set(self.sugeridas[i])
        self._cerrar()
        self.icursor("end")

    def _cerrar(self):
        self.indice = -1
        if self._tarea is not None:
            try:
                self.after_cancel(self._tarea)
            except tk.TclError:
                pass
            self._tarea = None
        if self.lista is not None:
            try:
                self.lista.pack_forget()
            except tk.TclError:
                pass

    def _salio(self, _evento):
        self._cerrar()
        self.after(60, self._completar)

    def _completar(self):
        """Al salir del campo: «nin» pasa a «Niñera» si solo puede ser esa opción."""
        try:
            foco = self._foco_actual()
            if foco in ("", str(self)):     # sigue en este campo, o el foco salió de la aplicación (no se toca lo escrito)
                return
            texto = self.get().strip()
            if not texto:
                return
            opciones = self.opciones()
            exacta = [o for o in opciones if sin_acentos(o) == sin_acentos(texto)]
            posibles = exacta or filtrar_opciones(texto, opciones, self.sinonimos)
            if len(posibles) == 1 or exacta:
                self.set(posibles[0])
        except tk.TclError:
            pass


class Formulario(ttk.Frame):
    """Construye el formulario en dos columnas, con una fila triple opcional."""

    ESPACIO_CAMPOS = 15
    ESPACIO_COLUMNAS = 20

    def __init__(self, master, campos, fila_triple=()):
        super().__init__(master)
        self.campos = campos
        self.tipos, self.vars, self.textos, self.widgets, self.refs = {}, {}, {}, {}, {}
        self.columnconfigure(0, weight=1, uniform="col")
        self.columnconfigure(1, weight=1, uniform="col")
        fila, col = 0, 0
        for campo in campos:
            if campo[0] == SECCION:
                if col:
                    fila, col = fila + 1, 0
                cab = ttk.Frame(self)
                cab.grid(row=fila, column=0, columnspan=2, sticky="ew",
                         pady=(3 if fila == 0 else 23, 17))
                ttk.Label(cab, text=campo[1].upper(), style="Seccion.TLabel").pack(side="left")
                divisor(cab).pack(side="left", fill="x", expand=True, padx=(18, 0))
                fila += 1
                continue

            clave, etiqueta = campo[0], campo[1]
            tipo = campo[2] if len(campo) > 2 else "entry"
            opciones = campo[3] if len(campo) > 3 else []
            ancho = 2 if tipo == "text" else 1
            if clave in fila_triple:
                indice = fila_triple.index(clave)
                if indice == 0:
                    if col:
                        fila, col = fila + 1, 0
                    grupo_triple = ttk.Frame(self)
                    grupo_triple.grid(row=fila, column=0, columnspan=2, sticky="ew",
                                      pady=(0, self.ESPACIO_CAMPOS))
                    for columna, peso in enumerate((4, 2, 3)):
                        grupo_triple.columnconfigure(columna, weight=peso, uniform="fila_triple")
                celda = ttk.Frame(grupo_triple)
                mitad = self.ESPACIO_COLUMNAS // 2
                padx = (0, mitad) if indice == 0 else (mitad, 0) if indice == 2 else (mitad, mitad)
                celda.grid(row=0, column=indice, sticky="new", padx=padx)
            else:
                if ancho == 2 and col:
                    fila, col = fila + 1, 0
                celda = ttk.Frame(self)
                mitad = self.ESPACIO_COLUMNAS // 2
                padx = 0 if ancho == 2 else (0, mitad) if col == 0 else (mitad, 0)
                celda.grid(row=fila, column=col, columnspan=ancho, sticky="new", padx=padx,
                           pady=(0, self.ESPACIO_CAMPOS))
            self.tipos[clave] = tipo

            if tipo == "check":
                v = tk.IntVar()
                w = ttk.Checkbutton(celda, text=etiqueta, variable=v)
                w.pack(anchor="w")
            else:
                principal, pista = partir_etiqueta(etiqueta)
                cab = ttk.Frame(celda)
                cab.pack(fill="x", pady=(0, 7))
                ttk.Label(cab, text=principal, style="Etiqueta.TLabel").pack(side="left")
                if pista:
                    ttk.Label(cab, text=pista, style="Pista.TLabel").pack(side="right")
                if tipo == "text":
                    w = tk.Text(celda, height=2, width=10, wrap="word", font=F["base"],
                                bg=C["campo"], fg=C["texto"], insertbackground=C["texto"],
                                relief="flat", borderwidth=0, padx=13, pady=9,
                                highlightthickness=1, highlightbackground=C["borde"],
                                highlightcolor=C["acento"], selectbackground=C["acento_suave"],
                                selectforeground=C["texto"])
                    self.textos[clave] = w
                    v = None
                elif tipo == "autocompletar":
                    v = tk.StringVar()
                    w = ComboAutocompletar(celda, textvariable=v, values=opciones, width=10, sinonimos=sinonimos_de_area)
                elif tipo in ("combo", "ref"):
                    v = tk.StringVar()
                    w = ttk.Combobox(celda, textvariable=v, values=opciones, state="readonly", width=10)
                    if tipo == "ref":
                        self.refs[clave] = {}
                else:
                    v = tk.StringVar()
                    w = ttk.Entry(celda, textvariable=v, width=10,
                                  state="readonly" if tipo == "readonly" else "normal")
                w.pack(fill="x")
            if v is not None:
                self.vars[clave] = v
            self.widgets[clave] = w

            if clave in fila_triple:
                if clave == fila_triple[-1]:
                    fila, col = fila + 1, 0
            elif ancho == 2:
                fila, col = fila + 1, 0
            else:
                col += 1
                if col == 2:
                    fila, col = fila + 1, 0

    def valor(self, clave):
        tipo = self.tipos[clave]
        if tipo == "text":
            return self.textos[clave].get("1.0", "end-1c").strip()
        if tipo == "check":
            return str(self.vars[clave].get())
        texto = self.vars[clave].get().strip()
        if tipo == "ref":
            return texto.split(" - ", 1)[0] if texto else ""
        return texto

    def poner_valor(self, clave, valor):
        valor = "" if valor is None else str(valor)
        tipo = self.tipos[clave]
        if tipo == "text":
            self.textos[clave].delete("1.0", "end")
            self.textos[clave].insert("1.0", valor)
        elif tipo == "check":
            self.vars[clave].set(1 if valor == "1" else 0)
        elif tipo == "ref":
            texto = self.refs[clave].get(valor, f"{valor} - (no encontrado)") if valor else ""
            self.vars[clave].set(texto)
        else:
            self.vars[clave].set(valor)

    def obtener(self):
        return {clave: self.valor(clave) for clave in self.tipos}

    def poner(self, datos):
        for clave in self.tipos:
            self.poner_valor(clave, datos.get(clave, ""))


def crear_tabla(master, columnas, horizontal=False):
    """Tabla con desplazamiento opcional para pantallas estrechas."""
    marco = ttk.Frame(master)
    marco.columnconfigure(0, weight=1)
    marco.rowconfigure(0, weight=1)
    tabla = ttk.Treeview(marco, columns=[c[0] for c in columnas], show="headings", selectmode="browse")
    for clave, titulo, ancho in columnas:
        tabla.heading(clave, text=PAD + titulo, anchor="w")
        tabla.column(clave, width=ancho, minwidth=40, anchor="w")
    sb = ttk.Scrollbar(marco, orient="vertical", command=tabla.yview)
    tabla.configure(yscrollcommand=sb.set)
    tabla.grid(row=0, column=0, sticky="nsew")
    sb.grid(row=0, column=1, sticky="ns")
    if horizontal:
        desplazamiento = ttk.Scrollbar(marco, orient="horizontal", command=tabla.xview)
        tabla.configure(xscrollcommand=desplazamiento.set)

        def ajustar(_evento=None):
            ancho = sum(tabla.column(clave, "width") for clave, _, _ in columnas)
            visible = ancho > tabla.winfo_width() + 2
            if visible and not desplazamiento.winfo_manager():
                desplazamiento.grid(row=1, column=0, sticky="ew")
            elif not visible and desplazamiento.winfo_manager():
                desplazamiento.grid_remove()
                tabla.xview_moveto(0)

        tabla.bind("<Configure>", ajustar, add="+")
        tabla.after_idle(ajustar)
    tabla.tag_configure("par", background=C["fondo"])
    tabla.tag_configure("impar", background=C["tabla_alt"])
    tabla.tag_configure("alerta", background=C["alerta"])
    return marco, tabla


def tarjeta(master):
    """Panel elevado con contorno sutil. Devuelve (marco exterior, interior)."""
    borde = tk.Frame(master, bg=C["borde"])
    interior = ttk.Frame(borde, padding=(24, 21, 24, 21))
    interior.pack(fill="both", expand=True, padx=1, pady=1)
    return borde, interior


def paso(master, numero, texto):
    fila = ttk.Frame(master)
    tk.Label(fila, text=numero, bg=C["rojo"], fg="#FFFFFF", font=F["seccion"], width=2).pack(side="left")
    ttk.Label(fila, text=texto, font=F["marca"]).pack(side="left", padx=(10, 0))
    return fila


def insignia(master):
    """Contador pequeño en una pastilla celeste."""
    return tk.Label(master, text="0", bg=C["acento_suave"], fg=C["acento"], font=F["seccion"],
                    padx=8, pady=1)


def mensaje_vacio(master, titulo, texto_boton, comando):
    """Mensaje centrado sobre una tabla vacía. Devuelve (marco, etiqueta de explicación)."""
    marco = ttk.Frame(master)
    ttk.Label(marco, text=titulo, font=F["marca"]).pack()
    explicacion = ttk.Label(marco, style="Tenue.TLabel", justify="center", wraplength=340)
    explicacion.pack(pady=(6, 16))
    ttk.Button(marco, text=texto_boton, style="Pequeno.TButton", command=comando).pack()
    return marco, explicacion


def encabezado(cab, titulo, subtitulo, volver=None, compacto=False,
               texto_volver="←  Todas las áreas"):
    """Jerarquía de página: marca breve, título y descripción opcional."""
    textos = ttk.Frame(cab)
    textos.pack(side="left")
    if volver:
        ttk.Button(textos, text=texto_volver, style="Enlace.TButton",
                   command=volver).pack(anchor="w", pady=(0, 12))
    subrayado(textos, 32).pack(anchor="w", pady=(0, 10))
    fila = ttk.Frame(textos)
    fila.pack(anchor="w")
    etiqueta = ttk.Label(fila, text=titulo, style="Titulo.TLabel")
    etiqueta.pack(side="left")
    if compacto and subtitulo:
        ttk.Label(fila, text=subtitulo, style="Subtitulo.TLabel").pack(side="left", padx=(18, 0))
    elif subtitulo:
        ttk.Label(textos, text=subtitulo, style="Subtitulo.TLabel").pack(anchor="w", pady=(4, 0))
    return etiqueta


def crear_pestanas(master, opciones, al_elegir):
    """Pestañas ligeras con indicador azul y acceso por teclado."""
    barra = ttk.Frame(master, padding=(32, 0, 32, 10))
    barra.pack(fill="x")
    pestanas = {}
    for clave, texto in opciones:
        marco = tk.Frame(barra, bg=C["fondo"], cursor="hand2", takefocus=1,
                         highlightthickness=1, highlightbackground=C["fondo"])
        marco.pack(side="left", padx=(0, 8))
        etiqueta = tk.Label(marco, text=texto, bg=C["fondo"], fg=C["texto2"], font=F["base"],
                            padx=16, pady=9, cursor="hand2")
        etiqueta.pack(side="top")
        marca = tk.Frame(marco, bg=C["fondo"], height=3)
        marca.pack(side="bottom", fill="x")
        for w in (marco, etiqueta, marca):
            w.bind("<Button-1>", lambda e, c=clave, m=marco: (m.focus_set(), al_elegir(c)))
        marco.bind("<Return>", lambda e, c=clave: al_elegir(c))
        marco.bind("<space>", lambda e, c=clave: al_elegir(c))
        marco.bind("<FocusIn>", lambda e, m=marco: m.configure(highlightbackground=C["acento"]))
        marco.bind("<FocusOut>", lambda e, m=marco: m.configure(highlightbackground=C["fondo"]))
        pestanas[clave] = (etiqueta, marca)
    return pestanas


def pintar_pestanas(pestanas, activa):
    for clave, (etiqueta, marca) in pestanas.items():
        es_activa = clave == activa
        fondo = C["activo"] if es_activa else C["fondo"]
        try:
            etiqueta.master.configure(bg=fondo)
            etiqueta.configure(bg=fondo, fg=C["texto"] if es_activa else C["texto2"],
                               font=F["negrita"] if es_activa else F["base"])
            marca.configure(bg=C["azul_marca"] if es_activa else fondo)
        except tk.TclError:      # la ventana se está cerrando y la pestaña ya no existe
            return


def mostrar_si(widget, visible):
    if visible:
        widget.place(relx=0.5, rely=0.42, anchor="center")
    else:
        widget.place_forget()


# ---------------------------------------------------------------- Páginas
class Pagina(ttk.Frame):
    """Encabezado, lista a la izquierda y ficha del registro a la derecha."""
    tabla = ""
    nombre_singular = ""
    titulo_pagina = ""
    subtitulo = ""
    texto_nuevo = ""
    campos = []
    columnas = []   # (clave, título, ancho)
    numericos = []
    fechas = []
    fila_triple = ()
    cabecera_compacta = False
    mostrar_boton_nuevo = True
    pestana_ficha_nueva = False
    ficha_ancha = False

    def __init__(self, master, app):
        super().__init__(master)
        self.app, self.db = app, app.db
        self.id_actual = None
        self._cambiando = False   # evita guardar dos veces lo mismo cuando cambia la selección
        self._datos_cargados = {}
        self.borrador = None      # lo escrito en un registro nuevo al que aún le faltan datos obligatorios
        self._lista_fuente = None
        self._lista_indice = ()
        self._lista_render_fuente = None
        self._lista_render_busqueda = None
        self._lista_rev = -1       # revisión de la tabla con la que se armó el índice de la lista
        self._lista_pos = {}       # id -> posición en el índice

        # Encabezado de la página
        cab = ttk.Frame(self, padding=(32, 20, 32, 10) if self.cabecera_compacta
                        else (32, 28, 32, 16))
        cab.pack(fill="x")
        encabezado(cab, self.titulo_pagina, self.subtitulo, compacto=self.cabecera_compacta)
        if self.mostrar_boton_nuevo:
            ttk.Button(cab, text=f"+   {self.texto_nuevo}", style="Rojo.TButton",
                       command=self.solicitar_nuevo).pack(side="right")
        if self.formulario_primero:
            texto_ficha = self.texto_nuevo if self.pestana_ficha_nueva else ""
            self.pestanas = crear_pestanas(self, [("ficha", texto_ficha), ("lista", "")],
                                           self.elegir_pestana)
        divisor(self).pack(fill="x")

        # El contenedor permite poner varias vistas en el mismo espacio
        self.contenedor = ttk.Frame(self)
        self.contenedor.pack(fill="both", expand=True)
        self.contenedor.rowconfigure(0, weight=1)
        self.contenedor.columnconfigure(0, weight=1)
        if self.formulario_primero:
            # Dos vistas: la lista completa y la ficha a lo ancho dentro de una tarjeta
            self.vista_lista = ttk.Frame(self.contenedor, style="Fondo.TFrame")
            self.vista_lista.grid(row=0, column=0, sticky="nsew")
            borde_lista = tk.Frame(self.vista_lista, bg=C["borde"])
            borde_lista.pack(fill="both", expand=True, padx=32, pady=18)
            izq = ttk.Frame(borde_lista, padding=(24, 22, 24, 18))
            izq.pack(fill="both", expand=True, padx=1, pady=1)
            self.vista_ficha = ttk.Frame(self.contenedor, style="Fondo.TFrame")
            self.vista_ficha.grid(row=0, column=0, sticky="nsew")
            self.vista_ficha.rowconfigure(0, weight=1)
            if self.ficha_ancha:
                self.vista_ficha.columnconfigure(0, weight=1)
                columna_ficha, margen_ficha = 0, 32
            else:
                self.vista_ficha.columnconfigure(0, weight=1)
                self.vista_ficha.columnconfigure(1, weight=6)
                self.vista_ficha.columnconfigure(2, weight=1)
                columna_ficha, margen_ficha = 1, 0
            borde = tk.Frame(self.vista_ficha, bg=C["borde"])
            if self.ficha_ancha:
                borde.grid(row=0, column=columna_ficha, sticky="nsew",
                           padx=margen_ficha, pady=18)
            else:
                borde.grid(row=0, column=columna_ficha, sticky="nsew", padx=margen_ficha, pady=24)
            der = ttk.Frame(borde)
            der.pack(fill="both", expand=True, padx=1, pady=1)
        else:
            # Lista a la izquierda y ficha a la derecha
            cuerpo = ttk.Frame(self.contenedor)
            cuerpo.grid(row=0, column=0, sticky="nsew")
            cuerpo.rowconfigure(0, weight=1)
            cuerpo.columnconfigure(0, weight=5, uniform="cuerpo")
            cuerpo.columnconfigure(2, weight=7, uniform="cuerpo")
            izq = ttk.Frame(cuerpo, padding=(36, 22, 20, 18))
            izq.grid(row=0, column=0, sticky="nsew")
            divisor(cuerpo, vertical=True).grid(row=0, column=1, sticky="ns")
            der = ttk.Frame(cuerpo)
            der.grid(row=0, column=2, sticky="nsew")

        # Lista
        self.busqueda = CampoBusqueda(izq, self.cargar_lista, f"Buscar {self.titulo_pagina.lower()}…")
        self.busqueda.pack(fill="x")
        marco, self.lista = crear_tabla(izq, self.columnas, horizontal=True)
        marco.pack(fill="both", expand=True, pady=(16, 0))
        self.lista.bind("<<TreeviewSelect>>", self.al_seleccionar)
        self.vacio, self.texto_vacio = mensaje_vacio(
            marco, "Todavía no hay registros", f"Crear {self.nombre_singular.lower()}", self.solicitar_nuevo)
        self.total = ttk.Label(izq, style="Pista.TLabel")
        self.total.pack(anchor="w", pady=(10, 0))

        # Ficha
        cab = ttk.Frame(der, padding=(28, 22, 28, 4) if self.cabecera_compacta
                        else (28, 26, 28, 4))
        cab.pack(side="top", fill="x")
        self.cab_ficha = cab
        self.titulo = ttk.Label(cab, style="Detalle.TLabel", wraplength=560)
        self.titulo.pack(anchor="w")
        self.meta = ttk.Label(cab, style="Tenue.TLabel")
        self.meta.pack(anchor="w", pady=(3, 0))
        acciones = ttk.Frame(cab)
        acciones.pack(fill="x", pady=(12, 0) if self.cabecera_compacta else (16, 0))
        self.acciones = acciones
        self.botones_extra(acciones)
        if not acciones.winfo_children():
            acciones.pack_forget()

        pie = ttk.Frame(der)
        pie.pack(side="bottom", fill="x")
        divisor(pie).pack(fill="x")
        barra = ttk.Frame(pie, padding=(28, 13, 28, 15))
        barra.pack(fill="x")
        self.btn_eliminar = ttk.Button(barra, text="Eliminar", style="Peligro.TButton",
                                       command=self.eliminar)
        self.btn_eliminar.pack(side="left")
        ttk.Button(barra, text="Guardar", style="Primario.TButton", width=14,
                   command=self.guardar).pack(side="right")
        self.aviso = ttk.Label(barra, style="Aviso.TLabel")
        self.aviso.pack(side="right", padx=14)

        self.desplazable = MarcoDesplazable(der)
        self.desplazable.pack(fill="both", expand=True)
        self.form = Formulario(self.desplazable.interior, self.campos, fila_triple=self.fila_triple)
        self.form.pack(fill="both", expand=True)
        self.desplazable.activar_rueda()

        self.configurar()
        self.nuevo()

    # --- puntos de extensión
    formulario_primero = False  # True: la ficha ocupa la pantalla y la lista va en otra pestaña
    texto_lista = ""            # título de la pestaña de la lista

    def elegir_pestana(self, clave):
        if self.resolver_cambios() is False:
            return
        if (clave == "ficha" and self.pestana_ficha_nueva and self.id_actual is not None
                and self.vista_actual == "lista"):
            self.nuevo()
        else:
            self.ver(clave)

    def cambios_sin_guardar(self):
        actual = self.form.obtener()
        return any(self.normalizar_campo(clave, valor) != self.normalizar_campo(clave, self._datos_cargados.get(clave))
                   for clave, valor in actual.items())

    def normalizar_campo(self, clave, valor):
        valor = "" if valor is None else str(valor).strip()
        return ("0" if valor == "" else valor) if self.form.tipos[clave] == "check" else valor

    def resolver_cambios(self):
        """Guarda ediciones reales; conserva el formulario si hay un conflicto."""
        if self.cambios_sin_guardar() and not self.guardar(silencioso=True):
            if self.id_actual is None:
                if self.guardar_borrador() is False:
                    return False
            else:
                self.mostrar_aviso("Revise los cambios pendientes antes de salir")
                return False
        return True

    def guardar_borrador(self):
        if self.id_actual is None:      # solo los registros nuevos: los que ya existen conservan su versión anterior
            self.borrador = self.form.obtener()
            return self.app.guardar_borradores()

    def ver(self, clave):
        if not self.formulario_primero:
            return
        if clave == "lista":
            self.vista_lista.tkraise()
            # sin selección previa, así un clic vuelve a abrir cualquier registro
            self.lista.selection_remove(self.lista.selection())
        else:
            self.vista_ficha.tkraise()
        pintar_pestanas(self.pestanas, clave)
        self.vista_actual = clave
        if self.pestana_ficha_nueva:
            titulo = self.titulo.cget("text") if clave == "ficha" and self.id_actual is not None else self.texto_nuevo
            self.pestanas["ficha"][0].configure(text=titulo)

    def botones_extra(self, barra):
        pass

    def configurar(self):
        pass

    def valores_defecto(self):
        return {}

    def valores_fila(self, fila):
        return [fila.get(c[0], "") for c in self.columnas]

    def etiqueta_fila(self, fila):
        return ()

    def titulo_registro(self, datos):
        return datos.get("nombre") or f"{self.nombre_singular} N° {self.id_actual}"

    def validar_extra(self, datos):
        tipo = datos.get("tipo_servicio")
        if tipo:      # lo escrito debe ser un área: se acepta sin importar mayúsculas ni tildes y se guarda su nombre
            area = area_de_texto(tipo)
            if area is None or not self.db.con.execute("SELECT 1 FROM areas WHERE nombre=?", (area,)).fetchone():
                return f"«{tipo}» no es un área. Elija una de la lista o cree el área nueva en la pantalla Áreas."
            datos["tipo_servicio"] = area
            self.form.poner_valor("tipo_servicio", area)
        return None

    def despues_de_guardar(self, datos):
        pass

    campo_enlace = ""  # columna de colocaciones que apunta a este registro

    def enlaces(self, id_):
        if not self.campo_enlace:
            return []
        return [c for c in self.db.todos("colocaciones") if c[self.campo_enlace] == str(id_)]

    # --- comportamiento común
    def refrescar(self):
        self.cargar_lista()

    @staticmethod
    def _sincronizar_tabla(tabla, estado, entradas, vivos=None):
        """Reutiliza filas y desprende las ocultas; conserva selección y desplazamiento."""
        guardadas = estado.setdefault("filas", {})
        primera = not guardadas
        anteriores = estado.get("visibles", ())
        desplazamiento = tabla.yview()
        if vivos is not None:
            eliminadas = guardadas.keys() - vivos
            if eliminadas:
                tabla.delete(*eliminadas)
                for iid in eliminadas:
                    del guardadas[iid]
        visibles = []
        for iid, valores, etiquetas in entradas:
            visibles.append(iid)
            fila = (tuple(valores), tuple(etiquetas))
            anterior = guardadas.get(iid)
            if anterior is None:
                # call convierte la tupla en una lista Tcl: conserva texto literal y
                # evita volver a escapar en Python cada celda al crear miles de filas.
                opciones = ("-values", fila[0]) + (("-tags", fila[1]) if fila[1] else ())
                tabla.tk.call(tabla._w, "insert", "", "end", "-id", iid, *opciones)
            elif anterior != fila:
                opciones = {}
                if anterior[0] != fila[0]:
                    opciones["values"] = fila[0]
                if anterior[1] != fila[1]:
                    opciones["tags"] = fila[1]
                tabla.item(iid, **opciones)
            guardadas[iid] = fila
        visibles = tuple(visibles)
        if visibles != anteriores:
            if not primera:
                tabla.set_children("", *visibles)
            permitidos = set(visibles)
            ocultos = [iid for iid in tabla.selection() if iid not in permitidos]
            if ocultos:
                tabla.selection_remove(*ocultos)
            if tabla.focus() and tabla.focus() not in permitidos:
                tabla.focus("")
            if desplazamiento:
                tabla.yview_moveto(desplazamiento[0])
        estado["visibles"] = visibles
        estado["visibles_set"] = set(visibles)

    def _entrada_de_lista(self, fila):
        valores = self.valores_fila(fila)
        buscable = " ".join(str(x) for x in list(valores) + list(fila.values())).lower()
        return (str(fila["id"]), [PAD + str(v) for v in valores], buscable, self.etiqueta_fila(fila))

    def _actualizar_filas_editadas(self, filas, texto):
        """Actualiza pocas ediciones; conserva la tabla si su filtro y orden siguen iguales."""
        if self._lista_render_fuente is None:
            return False
        cambios = self.db.cambios_desde(self.tabla, self._lista_rev)
        if cambios is None or len(cambios) > 20 or any(tipo != "act" for tipo, _ in cambios):
            return False
        nuevas = []
        for id_ in dict.fromkeys(id_ for _, id_ in cambios):
            fila, pos = self.db.uno(self.tabla, id_), self._lista_pos.get(str(id_))
            if fila is None or pos is None or pos >= len(self._lista_indice):
                return False
            nuevas.append((pos, self._entrada_de_lista(fila)))
        estado = getattr(self, "_lista_estado", {})
        visibles = estado.get("visibles_set", ())
        directa = self._lista_render_busqueda == texto and bool(estado)
        if directa:
            directa = all((entrada[0] in visibles) == (not texto or texto in entrada[2])
                          for _, entrada in nuevas)
        for pos, entrada in nuevas:
            self._lista_indice[pos] = entrada
            iid, valores, _, etiquetas = entrada
            if directa and iid in visibles:
                indice = estado["visibles"].index(iid) if texto else pos
                fila = (tuple(valores), tuple(etiquetas or (("impar",) if indice % 2 else ("par",))))
                anterior = estado["filas"][iid]
                opciones = {}
                if anterior[0] != fila[0]:
                    opciones["values"] = fila[0]
                if anterior[1] != fila[1]:
                    opciones["tags"] = fila[1]
                if opciones:
                    self.lista.item(iid, **opciones)
                estado["filas"][iid] = fila
        self._lista_fuente = filas
        self._lista_rev = self.db.revision(self.tabla)
        if directa:
            self._lista_render_fuente = filas
        return True

    def cargar_lista(self):
        filas = self.db.todos(self.tabla)
        texto = self.busqueda.texto().strip().lower()
        cambio_fuente = self._lista_fuente is not filas
        if cambio_fuente:
            if not self._actualizar_filas_editadas(filas, texto):
                self._lista_indice = [self._entrada_de_lista(fila) for fila in filas]
                self._lista_pos = {entrada[0]: i for i, entrada in enumerate(self._lista_indice)}
                self._lista_fuente = filas
                self._lista_rev = self.db.revision(self.tabla)
        if self._lista_render_fuente is filas and self._lista_render_busqueda == texto:
            return
        entradas = []
        for id_, valores, buscable, etiquetas in self._lista_indice:
            if not texto or texto in buscable:
                entradas.append((id_, valores, etiquetas or (("impar",) if len(entradas) % 2 else ("par",))))
        if not hasattr(self, "_lista_estado"):
            self._lista_estado = {}
        self._sincronizar_tabla(self.lista, self._lista_estado, entradas,
                               self._lista_pos.keys() if cambio_fuente else None)
        total = len(entradas)
        self.total.config(text=f"{total} registro{'' if total == 1 else 's'}"
                          + ("   ·   haga clic en uno para ver o editar sus datos" if total else ""))
        self.texto_vacio.configure(text=("Pruebe con otro nombre o teléfono."
                                         if texto else "Comience creando un registro en esta sección."))
        mostrar_si(self.vacio, total == 0)
        if self.formulario_primero:
            self.pestanas["lista"][0].configure(text=self.texto_lista)
        self._lista_render_fuente = filas
        self._lista_render_busqueda = texto

    def contar(self):
        return len(self.db.todos(self.tabla))

    def seleccionar(self, id_):
        if str(id_) in getattr(self, "_lista_estado", {}).get("visibles_set", ()):
            self.lista.selection_set(str(id_))
            self.lista.see(str(id_))

    def al_seleccionar(self, _evento=None):
        sel = self.lista.selection()
        if not sel:
            return
        if int(sel[0]) != self.id_actual and not self._cambiando:
            self._cambiando = True
            try:
                if self.resolver_cambios() is False:
                    if self.id_actual is not None:
                        self.lista.selection_set(str(self.id_actual))
                    return
            finally:
                self._cambiando = False
            if self.lista.selection() != sel:              # al guardar se cambió la selección: volver a la elegida
                self.lista.selection_set(*sel)
                return
        datos = self.db.uno(self.tabla, int(sel[0]))
        if datos:
            self.id_actual = datos["id"]
            self.form.poner(datos)
            self._datos_cargados = self.form.obtener()
            self.cabecera(datos)
            self.desplazable.arriba()
            self.ver("ficha")

    def cabecera(self, datos=None):
        if self.id_actual is None:
            titulo = self.texto_nuevo
            self.meta.config(text="Complete los datos. Los campos marcados son obligatorios.")
            self.btn_eliminar.pack_forget()
        else:
            titulo = self.titulo_registro(datos)
            self.meta.config(text=f"Registro N° {self.id_actual}   ·   {datos.get('estado') or 'Sin estado'}")
            if not self.btn_eliminar.winfo_manager():
                self.btn_eliminar.pack(side="left")
        self.titulo.config(text=titulo)
        if (self.formulario_primero and
                (not self.pestana_ficha_nueva or getattr(self, "vista_actual", "ficha") == "ficha")):
            self.pestanas["ficha"][0].configure(text=titulo)

    def solicitar_nuevo(self):
        if self.resolver_cambios() is not False:
            self.nuevo()

    def nuevo(self):
        self.id_actual = None
        self.lista.selection_remove(self.lista.selection())
        self.form.poner({**self.valores_defecto(), **(self.borrador or {})})
        # Lo escrito en un borrador sigue pendiente de convertirse en registro.
        self._datos_cargados = {clave: self.valores_defecto().get(clave, "") for clave in self.form.tipos}
        self.cabecera()
        self.desplazable.arriba()
        self.ver("ficha")

    def validar(self, datos):
        for campo in self.campos:
            if campo[0] != SECCION and campo[1].endswith("*") and not datos.get(campo[0]):
                return f"El campo «{partir_etiqueta(campo[1])[0]}» es obligatorio."
        for clave in self.numericos:
            if datos.get(clave) and leer_numero(datos[clave]) is None:
                return f"«{etiqueta_de(self.campos, clave)}» debe ser un número."
        for clave in self.fechas:
            if datos.get(clave) and leer_fecha(datos[clave]) is None:
                return f"«{etiqueta_de(self.campos, clave)}» debe ser una fecha dd/mm/aaaa."
        return self.validar_extra(datos)

    def guardar(self, silencioso=False):
        """Actualiza campos editados y detecta conflictos dentro de la transacción."""
        escritos = self.form.obtener()
        self.db.cambio_externo()
        try:
            if self.id_actual is None:
                with self.db.lote():
                    self.db.con.execute(f"UPDATE {self.tabla} SET id=id WHERE 0")
                    self.db.cambio_externo()
                    datos = dict(escritos)
                    error = self.validar(datos)
                    if error:
                        raise AccionRechazada("Revise los datos", error)
                    nuevo_id = self.db.insertar(self.tabla, {**self.valores_defecto(), **datos})
                self.id_actual = nuevo_id
                if self.borrador is not None:
                    self.borrador = None
                    self.app.guardar_borradores()
            else:
                cambios = {clave: valor for clave, valor in escritos.items()
                           if self.normalizar_campo(clave, valor) != self.normalizar_campo(clave, self._datos_cargados.get(clave))}
                self.db.cambio_externo()
                with self.db.lote():
                    self.db.con.execute(f"UPDATE {self.tabla} SET id=id WHERE 0")
                    self.db.cambio_externo()
                    fila = self.db.con.execute(f"SELECT * FROM {self.tabla} WHERE id = ?", (self.id_actual,)).fetchone()
                    if fila is None:
                        raise AccionRechazada("Registro no disponible", "El registro fue eliminado. Lo escrito se conserva en el formulario.")
                    actual = self.db._fila(fila)
                    conflictos = [clave for clave, valor in cambios.items()
                                  if self.normalizar_campo(clave, actual.get(clave)) != self.normalizar_campo(clave, self._datos_cargados.get(clave))
                                  and self.normalizar_campo(clave, actual.get(clave)) != self.normalizar_campo(clave, valor)]
                    if conflictos:
                        campos = ", ".join(etiqueta_de(self.campos, clave) for clave in conflictos)
                        raise AccionRechazada("Cambios simultáneos", f"También se modificó: {campos}. Lo escrito se conserva; revise el valor actual antes de guardarlo.")
                    datos = {clave: actual.get(clave, "") for clave in self.form.tipos}
                    datos.update(cambios)
                    error = self.validar(datos)
                    if error:
                        raise AccionRechazada("Revise los datos", error)
                    if cambios:
                        self.db.actualizar(self.tabla, self.id_actual, {clave: datos[clave] for clave in cambios})
        except AccionRechazada as error:
            if error.titulo != "Revise los datos" or not silencioso:
                messagebox.showwarning(error.titulo, str(error), parent=self)
            return False
        guardado = self.db.uno(self.tabla, self.id_actual)
        self.form.poner(guardado)
        self._datos_cargados = self.form.obtener()
        self.despues_de_guardar(datos)
        self.app.refrescar_todo()
        self.seleccionar(self.id_actual)
        self.cabecera(guardado)
        self.mostrar_aviso("Guardado ✓")
        return True

    def eliminar(self):
        if self.id_actual is None:
            return
        self.db.cambio_externo()
        persona = self.app._fila_actual(self.tabla, self.id_actual)
        if persona is None:
            messagebox.showwarning("Eliminar", "El registro ya fue eliminado. Revise la lista actual.", parent=self)
            self.app.refrescar_todo()
            return
        enlaces = self.enlaces(self.id_actual)
        pregunta = f"¿Eliminar {self.nombre_singular.lower()} N° {self.id_actual}?"
        if enlaces:
            pregunta += (f"\n\nTiene {len(enlaces)} asignación{'' if len(enlaces) == 1 else 'es'}: "
                         "se desharán sus vínculos. Las personas con otro trabajo conservarán su estado; "
                         "los antecedentes necesarios para reemplazos se conservarán." + describir_perdida(enlaces))
        if not messagebox.askyesno("Eliminar", pregunta + "\n\nAntes de borrar se guarda una copia de seguridad: "
                                   "si se equivoca, se puede recuperar.", parent=self):
            return
        if not self.app.copia_antes_de_borrar():
            return
        try:
            if not self.app.eliminar_persona(self.tabla, self.id_actual, enlaces, persona):
                messagebox.showwarning("Eliminar", "El registro ya fue eliminado. Revise la lista actual.", parent=self)
        except (ValueError, sqlite3.Error) as error:
            messagebox.showwarning("No se pudo eliminar", str(error), parent=self)
            self.app.refrescar_todo()
            return
        self.nuevo()
        self.app.refrescar_todo()

    def mostrar_aviso(self, texto):
        self.aviso.config(text=texto)
        self.after(3000, lambda: self.aviso.config(text=""))


class PaginaClientes(Pagina):
    tabla = "clientes"
    nombre_singular = "Cliente"
    titulo_pagina = "Clientes"
    texto_nuevo = "Nuevo cliente"
    texto_lista = "Clientes registrados"
    formulario_primero = True
    cabecera_compacta = True
    mostrar_boton_nuevo = False
    pestana_ficha_nueva = True
    ficha_ancha = True
    fila_triple = ("nombre", "dni", "telefono")
    campos = CAMPOS_CLIENTE
    columnas = [("nombre", "Nombre", 200), ("telefono", "Teléfono", 120), ("zona", "Zona", 140),
                ("tipo_servicio", "Servicio", 150), ("sueldo_ofrecido", "Ofrece", 100),
                ("estado", "Estado", 120)]

    def valores_fila(self, fila):
        valores = super().valores_fila(fila)
        valores[4] = dinero_corto(fila["sueldo_ofrecido"])
        return [v if v else "-" for v in valores]
    numericos = ["sueldo_ofrecido"]
    fechas = ["fecha_registro"]

    def valores_defecto(self):
        return {"fecha_registro": hoy(), "estado": "Pendiente"}

    def guardar(self, silencioso=False):
        if self.id_actual is None:
            self.form.poner_valor("fecha_registro", hoy())
        return super().guardar(silencioso)

    campo_enlace = "cliente_id"


class PaginaTrabajadoras(Pagina):
    def validar_extra(self, datos):
        error = super().validar_extra(datos)
        if error or self.id_actual is None:
            return error
        enlaces = self.app._vinculos_ocupantes("trabajadoras", self.id_actual)
        if enlaces:
            esperado = "Trabajando" if any(e in ("Activa", "Garantía cumplida") for e in enlaces.values()) else "En proceso"
            if datos.get("estado") != esperado:
                return (f"La trabajadora tiene una asignación pendiente o en curso y su estado debe ser «{esperado}». "
                        "Registre el inicio, solicite reemplazo o deshaga el vínculo antes de cambiar su disponibilidad.")
        return None

    tabla = "trabajadoras"
    nombre_singular = "Trabajadora"
    titulo_pagina = "Trabajadoras"
    texto_nuevo = "Nueva trabajadora"
    texto_lista = "Trabajadoras registradas"
    formulario_primero = True
    cabecera_compacta = True
    mostrar_boton_nuevo = False
    pestana_ficha_nueva = True
    ficha_ancha = True
    fila_triple = ("nombre", "dni", "telefono")
    campos = CAMPOS_TRABAJADORA
    columnas = [("nombre", "Nombre", 200), ("telefono", "Teléfono", 120), ("zona", "Zona", 130),
                ("tipo_servicio", "Especialidad", 150),
                ("docs", "Documentos", 110), ("estado", "Estado", 120)]
    numericos = ["edad", "experiencia"]

    def valores_fila(self, fila):
        valores = super().valores_fila(fila)
        valores[4] = f"{len(docs_presentados(fila))}/{len(DOCUMENTOS)}"
        return [v if v else "-" for v in valores]

    def valores_defecto(self):
        return {"estado": "Disponible"}

    campo_enlace = "trabajadora_id"


class PaginaEnlazar(ttk.Frame):
    """Dentro de un área: elegir un cliente y una trabajadora para asignarla."""

    def __init__(self, master, app):
        super().__init__(master)
        self.app, self.db = app, app.db
        self.clientes, self.trabajadoras = {}, {}
        self.filtro_area = None  # tipo de servicio del área abierta, o None para todas
        self._candidatas_pendientes = None

        cab = ttk.Frame(self, padding=(28, 24, 28, 18))
        cab.pack(fill="x")
        self.lbl_titulo = encabezado(cab, "Áreas", "",
                                     volver=lambda: app.mostrar(app.areas))
        ttk.Button(cab, text="Ver asignaciones", style="Pequeno.TButton",
                   command=app.abrir_asignaciones).pack(side="right")
        divisor(self).pack(fill="x")

        v = ttk.Frame(self, style="Fondo.TFrame")
        v.pack(fill="both", expand=True)
        v.rowconfigure(0, weight=1)
        v.columnconfigure(0, weight=5, uniform="enlazar")
        v.columnconfigure(1, weight=8, uniform="enlazar")

        # Tarjeta 1: clientes que esperan trabajadora
        borde, izq = tarjeta(v)
        self.borde_clientes = borde
        izq.configure(padding=(20, 20, 20, 18))
        borde.grid(row=0, column=0, sticky="nsew", padx=(28, 7), pady=(22, 18))
        cab = ttk.Frame(izq)
        cab.pack(fill="x")
        ttk.Label(cab, text="Elija el cliente", style="Detalle.TLabel").pack(side="left")
        self.num_clientes = insignia(cab)
        self.num_clientes.pack(side="right")
        self.info_clientes = ttk.Label(izq, style="Tenue.TLabel", wraplength=300)
        self.info_clientes.pack(anchor="w", pady=(5, 0))
        marco, self.t_clientes = crear_tabla(
            izq, [("nombre", "Cliente", 150), ("zona", "Zona", 90), ("ofrece", "Ofrece", 80)])
        marco.pack(fill="both", expand=True, pady=(20, 0))
        self.t_clientes.bind("<<TreeviewSelect>>", self._programar_candidatas)
        self.vacio_clientes, self.vacio_clientes_texto = mensaje_vacio(
            marco, "Sin clientes pendientes", "+  Registrar cliente",
            lambda: self.app.registrar("clientes", self.filtro_area))

        # Tarjeta 2: trabajadoras disponibles del área
        borde, der = tarjeta(v)
        self.borde_trabajadoras = borde
        der.configure(padding=(20, 20, 20, 18))
        borde.grid(row=0, column=1, sticky="nsew", padx=(7, 28), pady=(22, 18))
        cab = ttk.Frame(der)
        cab.pack(fill="x")
        ttk.Label(cab, text="Elija la trabajadora", style="Detalle.TLabel").pack(side="left")
        self.num_trab = insignia(cab)
        self.num_trab.pack(side="left", padx=(10, 0))
        self.otras_areas = tk.BooleanVar(value=False)
        ttk.Checkbutton(cab, text="Incluir otras áreas", variable=self.otras_areas,
                        command=self._programar_candidatas).pack(side="right")
        self.info_trab = ttk.Label(der, style="Tenue.TLabel", wraplength=520)
        self.info_trab.pack(anchor="w", pady=(5, 0))
        marco, self.t_trab = crear_tabla(
            der, [("nombre", "Nombre", 200), ("zona", "Zona", 95),
                  ("tipo", "Especialidad", 125), ("docs", "Docs", 65)])
        marco.pack(fill="both", expand=True, pady=(20, 0))
        self.t_trab.bind("<<TreeviewSelect>>", lambda e: self.actualizar_enlace())
        self.t_trab.bind("<Double-1>", lambda e: self.asignar())
        self.vacio_trab, self.vacio_trab_texto = mensaje_vacio(
            marco, "Sin trabajadoras disponibles", "+  Registrar trabajadora",
            lambda: self.app.registrar("trabajadoras", self.filtro_area))
        self.detalle_trab = ttk.Label(der, style="Pista.TLabel", wraplength=520)
        self.detalle_trab.pack(anchor="w", pady=(12, 0))
        der.bind("<Configure>", lambda e: self._ajustar_columnas_trab(e.width))

        # Barra inferior: quién se asigna a quién
        pie = ttk.Frame(v)
        pie.grid(row=1, column=0, columnspan=2, sticky="ew")
        divisor(pie).pack(fill="x")
        barra = ttk.Frame(pie, padding=(28, 14, 28, 18))
        barra.pack(fill="x")
        barra.columnconfigure(0, weight=1)
        barra.columnconfigure(2, weight=1)

        def casilla(texto, columna):
            marco = ttk.Frame(barra)
            marco.grid(row=0, column=columna, sticky="ew")
            ttk.Label(marco, text=texto, style="Seccion.TLabel").pack(anchor="w")
            nombre = ttk.Label(marco, font=F["marca"], wraplength=270)
            nombre.pack(anchor="w", pady=(2, 0))
            return nombre

        self.sel_cliente = casilla("CLIENTE", 0)
        ttk.Label(barra, text="→", font=F["numero"], foreground=C["acento"]).grid(
            row=0, column=1, padx=18)
        self.sel_trab = casilla("TRABAJADORA", 2)
        self.btn_asignar = ttk.Button(barra, text="Asignar trabajadora  →", style="Primario.TButton",
                                      command=self.asignar)
        self.btn_asignar.grid(row=0, column=3, sticky="e", padx=(24, 0))

    def _ajustar_columnas_trab(self, ancho):
        """Prioriza los datos de decisión sin perder los demás en ventanas estrechas."""
        self.info_trab.configure(wraplength=max(180, ancho - 40))
        self.detalle_trab.configure(wraplength=max(180, ancho - 40))
        if ancho < 480:
            columnas = ("nombre", "docs")
        elif ancho < 650:
            columnas = ("nombre", "tipo", "docs")
        else:
            columnas = ("nombre", "zona", "tipo", "docs")
        if tuple(self.t_trab["displaycolumns"]) != columnas:
            self.t_trab.configure(displaycolumns=columnas)

    def poner_area(self, tipo, cliente_id=None):
        self.filtro_area = tipo if tipo in AREAS else None
        self.lbl_titulo.config(text=AREAS[tipo][0] if self.filtro_area else "Todas las áreas")
        self.otras_areas.set(False)
        self.cargar_datos()
        self.cargar_enlazar(cliente_id)

    def cargar_datos(self):
        clientes = self.db.todos("clientes")
        trabajadoras = self.db.todos("trabajadoras")
        if getattr(self, "_clientes_fuente", None) is not clientes:
            self.clientes = {str(c["id"]): c for c in clientes}
            self._clientes_fuente = clientes
        if getattr(self, "_trabajadoras_fuente", None) is not trabajadoras:
            self.trabajadoras = {str(t["id"]): t for t in trabajadoras}
            self._trabajadoras_fuente = trabajadoras

    def refrescar(self):
        self.cargar_datos()
        self.cargar_enlazar()

    def cargar_enlazar(self, cliente_id=None):
        """Clientes pendientes del área; reutiliza las filas mientras los pedidos no cambian."""
        sel = self.t_clientes.selection()
        elegido = str(cliente_id) if cliente_id else (sel[0] if sel else None)
        clave = (self.db.revision("clientes"), self.db.revision("colocaciones"), self.filtro_area,
                 str(cliente_id) if cliente_id else None, tuple(AREAS.items()))
        if getattr(self, "_pedidos_clave", None) != clave:
            entradas = []
            for i, c in self.clientes.items():
                pendiente = c["estado"] in PEDIDOS_POR_ENLAZAR
                del_area = not self.filtro_area or c["tipo_servicio"] == self.filtro_area
                if (pendiente and del_area) or i == str(cliente_id):
                    nombre = c["nombre"] + ("   · reemplazo" if self.app.reemplazo_pendiente(i) else "")
                    entradas.append((i, [PAD + str(x) for x in (
                        nombre, c["zona"] or "-", dinero_corto(c["sueldo_ofrecido"]))], ()))
            if not hasattr(self, "_pedidos_estado"):
                self._pedidos_estado = {}
            Pagina._sincronizar_tabla(self.t_clientes, self._pedidos_estado, entradas, self.clientes.keys())
            area = AREAS[self.filtro_area][0] if self.filtro_area else "todas las áreas"
            self.num_clientes.config(text=str(len(entradas)))
            self.info_clientes.config(text=f"Clientes pendientes · {area}")
            self.vacio_clientes_texto.config(text=f"Cuando registre un cliente de {area}, aparecerá aquí.")
            mostrar_si(self.vacio_clientes, not entradas)
            self._pedidos_clave = clave
        if elegido and elegido in self._pedidos_estado["visibles"]:
            self.t_clientes.selection_set(elegido)
            if cliente_id:
                self.t_clientes.see(elegido)
        self._programar_candidatas()

    def _programar_candidatas(self, _evento=None):
        """Agrupa cambios de selección consecutivos en una sola reconstrucción."""
        if self._candidatas_pendientes is not None:
            self.after_cancel(self._candidatas_pendientes)
        self._candidatas_pendientes = self.after_idle(self._cargar_candidatas_pendientes)

    def _cargar_candidatas_pendientes(self):
        self._candidatas_pendientes = None
        self.cargar_candidatas()

    def cargar_candidatas(self):
        sel = self.t_clientes.selection()
        cli = self.clientes.get(sel[0]) if sel else None
        incluir_otras = self.otras_areas.get()
        clave = (self.db.revision("trabajadoras"), self.filtro_area, incluir_otras, tuple(AREAS.items()))
        if getattr(self, "_candidatas_clave", None) != clave:
            lista = [t for t in self.trabajadoras.values() if t["estado"] in ("Disponible", "")
                     and (not self.filtro_area or incluir_otras or trabaja_en(t, self.filtro_area))]
            lista.sort(key=lambda t: t["nombre"].casefold())
            entradas = [(str(t["id"]), [PAD + str(x) for x in (
                t["nombre"], t["zona"] or "-", t["tipo_servicio"] or "-",
                f"{len(docs_presentados(t))}/{len(DOCUMENTOS)}")], ()) for t in lista]
            if not hasattr(self, "_candidatas_estado"):
                self._candidatas_estado = {}
            Pagina._sincronizar_tabla(self.t_trab, self._candidatas_estado, entradas, self.trabajadoras.keys())
            self.num_trab.config(text=str(len(lista)))
            pista = "Registre una trabajadora"
            if self.filtro_area and not incluir_otras:
                pista += " o marque «Incluir otras áreas»"
            self.vacio_trab_texto.config(text=pista + ".")
            mostrar_si(self.vacio_trab, not lista)
            self._candidatas_clave = clave
        self.info_trab.config(text="Elija una trabajadora · doble clic para asignar"
                              if cli else "Elija primero un cliente y luego una trabajadora")
        self.actualizar_enlace()

    def elegidos(self):
        sc, st = self.t_clientes.selection(), self.t_trab.selection()
        return (self.clientes.get(sc[0]) if sc else None,
                self.trabajadoras.get(st[0]) if st else None)

    def actualizar_enlace(self):
        cli, t = self.elegidos()
        for etiqueta, persona in ((self.sel_cliente, cli), (self.sel_trab, t)):
            etiqueta.config(text=persona["nombre"] if persona else "Sin elegir",
                            foreground=C["texto"] if persona else C["tenue"])
        self.borde_clientes.configure(bg=C["azul_marca"] if cli else C["borde"])
        self.borde_trabajadoras.configure(bg=C["azul_marca"] if t else C["borde"])
        if t:
            perfil = (f"{t['zona'] or 'Zona sin registrar'}  ·  "
                      f"{t['tipo_servicio'] or 'Especialidad sin registrar'}  ·  "
                      f"Documentos {len(docs_presentados(t))}/{len(DOCUMENTOS)}")
            self.detalle_trab.configure(text=perfil)
        else:
            self.detalle_trab.configure(text="Seleccione una trabajadora para revisar su perfil.")
        self.btn_asignar.state(["!disabled"] if cli and t else ["disabled"])

    def asignar(self):
        cli, t = self.elegidos()
        if not (cli and t):
            messagebox.showwarning("Asignar", "Elija un cliente y una trabajadora.", parent=self)
            return
        nuevo = {clave: "" for clave in claves(CAMPOS_COLOCACION)}
        meses = meses_del_cliente(cli)
        nuevo.update(cliente_id=str(cli["id"]), trabajadora_id=str(t["id"]), fecha_enlace=hoy(),
                     estado="En proceso", sueldo_acordado=cli["sueldo_ofrecido"],
                     comision=monto_por_porcentaje(PORCENTAJE_DEFECTO, cli["sueldo_ofrecido"]) or COBRO_DEFECTO,
                     garantia="Sí" if meses else "No", meses_garantia=str(meses))
        anterior = self.app.reemplazo_pendiente(cli["id"])
        if anterior:  # cambio dentro de la garantía: sin costo y con la misma garantía
            nuevo.update(comision="0.00", reemplazo_de=str(anterior["id"]), garantia="Sí",
                         meses_garantia=str(meses_de_garantia(anterior) or MESES_GARANTIA),
                         notas=f"Reemplazo sin costo de la asignación N° {anterior['id']}.")

        def confirmar(datos):
            revisados = dict(datos)
            ocupacion = revisados.pop("ocupacion")
            registro = dict(nuevo, **revisados)
            registro["garantia"] = "Sí" if int(revisados["meses_garantia"]) else "No"
            registro.update(fecha_enlace=hoy(), porcentaje=porcentaje_de(revisados["comision"], revisados["sueldo_acordado"]))
            try:
                numero = self.app.crear_asignacion(registro, ocupacion, reemplazo_esperado=anterior)
            except (ValueError, sqlite3.Error) as error:
                messagebox.showwarning("No se pudo asignar", str(error), parent=self)
                self.app.refrescar_todo()
                return False
            self.app.refrescar_todo()
            self.after_idle(lambda: self.app.abrir_asignaciones(numero))
            return True

        valores = dict(datos_contrato(nuevo, cli), ocupacion=cli.get("ocupacion") or "")
        DialogoContrato(self, None, valores, confirmar, nombres=(cli["nombre"], t["nombre"]))


class PanelFirma(ttk.Frame):
    """Recuadro para firmar dibujando o eligiendo el nombre de la persona."""
    ANCHO, ALTO = 330, 150

    def __init__(self, master, titulo, nombre):
        super().__init__(master)
        self.nombre = nombre.strip()
        self.nombre_firma = ""
        self.fecha_nombre = ""
        cab = ttk.Frame(self)
        cab.pack(fill="x")
        ttk.Label(cab, text=titulo, style="Seccion.TLabel").pack(side="left")
        ttk.Button(cab, text="Borrar", style="Enlace.TButton", command=self.borrar).pack(side="right")
        self.lienzo = tk.Canvas(self, width=self.ANCHO, height=self.ALTO, bg=C["campo"],
                                highlightthickness=1, highlightbackground=C["barra"], cursor="pencil")
        self.lienzo.pack(pady=(8, 8))
        self.lienzo.create_line(20, self.ALTO - 30, self.ANCHO - 20, self.ALTO - 30,
                                fill=C["borde"], tags="guia")
        ttk.Button(self, text="Firmar con nombre", style="Pequeno.TButton",
                   command=self.usar_nombre).pack(fill="x", padx=12, pady=(0, 5))
        ttk.Label(self, text=self.nombre, style="Tenue.TLabel").pack()
        self.trazos = []
        self.lienzo.bind("<Button-1>", self._empezar)
        self.lienzo.bind("<B1-Motion>", self._mover)

    def usar_nombre(self):
        if not self.nombre:
            messagebox.showwarning("Firmar contrato", "Primero registre el nombre de quien firma.", parent=self)
            return
        self.borrar()
        self.nombre_firma = self.nombre
        self.fecha_nombre = datetime.now().isoformat(timespec="seconds")
        disponibles = {familia.lower(): familia for familia in tkfont.families(self)}
        preferidas = (("Segoe Script", "Snell Roundhand", "Apple Chancery")
                      if sys.platform == "win32" else
                      ("Snell Roundhand", "Apple Chancery", "Segoe Script"))
        familia = next((disponibles[f.lower()] for f in preferidas if f.lower() in disponibles),
                       "Times New Roman")
        opciones = {"family": familia, "size": 27}
        if familia == "Times New Roman":
            opciones["slant"] = "italic"
        self.fuente_nombre = tkfont.Font(root=self, **opciones)
        while self.fuente_nombre.measure(self.nombre) > self.ANCHO - 30 and self.fuente_nombre.cget("size") > 13:
            self.fuente_nombre.configure(size=self.fuente_nombre.cget("size") - 1)
        self.lienzo.create_text(self.ANCHO / 2, self.ALTO / 2, text=self.nombre,
                                fill=C["texto"], font=self.fuente_nombre, tags="firma")

    def _empezar(self, e):
        if self.nombre_firma:
            self.borrar()
        self.trazos.append([e.x, e.y])

    def _mover(self, e):
        trazo = self.trazos[-1]
        self.lienzo.create_line(trazo[-2], trazo[-1], e.x, e.y, fill=C["texto"], width=2.5,
                                capstyle="round", smooth=True, tags="firma")
        trazo.extend([e.x, e.y])

    def borrar(self):
        self.trazos = []
        self.nombre_firma = ""
        self.fecha_nombre = ""
        self.lienzo.delete("firma")

    def vacia(self):
        return not self.nombre_firma and not any(len(t) >= 4 for t in self.trazos)

    def datos(self):
        if self.nombre_firma:
            return json.dumps({"tipo": "nombre", "texto": self.nombre_firma,
                               "fecha": self.fecha_nombre}, ensure_ascii=False)
        return "" if self.vacia() else json.dumps(
            {"w": self.ANCHO, "h": self.ALTO, "trazos": [t for t in self.trazos if len(t) >= 4]})


class DialogoFirmas(tk.Toplevel):
    """Ventana para que cliente, trabajadora y agencia firmen el contrato."""

    def __init__(self, master, c, cliente, trabajadora, al_guardar):
        super().__init__(master)
        self.title("Firmar contrato")
        self.configure(bg=C["fondo"])
        self.transient(master.winfo_toplevel())
        centrar(self, 1180, 500, master.winfo_toplevel())
        self.al_guardar = al_guardar
        cont = ttk.Frame(self, padding=(32, 26, 32, 22))
        cont.pack(fill="both", expand=True)
        ttk.Label(cont, text=f"Contrato N° {c['id']}", style="Detalle.TLabel").pack(anchor="w")
        ttk.Label(cont, style="Tenue.TLabel",
                  text="Cada persona puede dibujar su firma o pulsar «Firmar con nombre» "
                       "en su propio recuadro.").pack(anchor="w", pady=(4, 18))
        fila = ttk.Frame(cont)
        fila.pack(fill="x")
        self.paneles = {
            "firma_cliente": PanelFirma(fila, "EL EMPLEADOR", cliente.get("nombre", "")),
            "firma_trabajadora": PanelFirma(fila, "LA TRABAJADORA", trabajadora.get("nombre", "")),
            "firma_agencia": PanelFirma(fila, "LA AGENCIA", AGENCIA_NOMBRE),
        }
        for panel in self.paneles.values():
            panel.pack(side="left", expand=True)
        botones = ttk.Frame(cont)
        botones.pack(side="bottom", fill="x", before=fila)   # si falta espacio se achican los recuadros, no los botones
        ttk.Button(botones, text="Guardar firmas", style="Primario.TButton",
                   command=self.guardar).pack(side="right")
        ttk.Button(botones, text="Cancelar", style="Secundario.TButton",
                   command=self.destroy).pack(side="right", padx=8)
        self.grab_set()

    def guardar(self):
        if self.paneles["firma_cliente"].vacia() or self.paneles["firma_trabajadora"].vacia():
            messagebox.showwarning("Firmar contrato",
                                   "Faltan firmas: el empleador y la trabajadora deben firmar.", parent=self)
            return
        if self.al_guardar({clave: panel.datos() for clave, panel in self.paneles.items()}) is not False:
            self.destroy()


MESES_NOMBRE = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                "septiembre", "octubre", "noviembre", "diciembre"]
MODALIDADES = ("Cama adentro", "Cama afuera", "Por días")


def datos_contrato(c, cli):
    """Lo que va en los espacios en blanco del contrato: lo guardado en el enlace o,
    si falta, lo que se deduce del pedido del cliente."""
    tipo = cli.get("tipo_servicio") or ""
    modalidad = ", ".join(x for x in (tipo if tipo in MODALIDADES else "", cli.get("horario") or "") if x)
    return {
        "fecha_contrato": c.get("fecha_contrato") or c.get("fecha_enlace") or hoy(),
        "comision": c.get("comision") or "0.00",
        "porcentaje": porcentaje_de(c.get("comision") or "0", c.get("sueldo_acordado") or ""),
        "meses_garantia": str(meses_de_garantia(c)),
        "sueldo_acordado": c.get("sueldo_acordado") or "",
        "puesto": c.get("puesto") or ("Todo servicio" if tipo in MODALIDADES or not tipo else tipo),
        "modalidad": c.get("modalidad") or modalidad,
        "descanso": c.get("descanso") or cli.get("dias_libres") or "",
    }


class DialogoContrato(tk.Toplevel):
    """Revisar lo que se imprime en los espacios en blanco del contrato."""
    CAMPOS = [
        (SECCION, "Contrato y garantía"),
        ("fecha_contrato", "Fecha del contrato (dd/mm/aaaa)"),
        ("porcentaje", "Comisión (% del sueldo mensual)"),               # primero el porcentaje...
        ("comision", f"Pago único a la agencia ({MONEDA})"),             # ...luego el pago único...
        ("meses_garantia", "Meses de garantía (0 = sin garantía)"),      # ...y después la garantía
        ("ocupacion", "Ocupación del empleador"),
        (SECCION, "Contrato de trabajo"),
        ("sueldo_acordado", f"Sueldo mensual ({MONEDA})"),
        ("puesto", "Puesto"),
        ("modalidad", "Modalidad (ej.: cama adentro, lunes a sábado)"),
        ("descanso", "Descanso los días"),
    ]

    def __init__(self, master, numero, valores, al_guardar, nombres=None, documento_firmado=False):
        super().__init__(master)
        nueva_asignacion = numero is None
        self.title("Asignar y preparar contrato" if nueva_asignacion else "Datos del contrato")
        self.configure(bg=C["fondo"])
        self.transient(master.winfo_toplevel())
        centrar(self, 820, min(740, self.winfo_screenheight() - 110), master.winfo_toplevel())
        self.al_guardar = al_guardar
        self._sincronizando = False
        cont = ttk.Frame(self, padding=(32, 26, 32, 22))
        cont.pack(fill="both", expand=True)
        titulo = f"{nombres[0]}  ↔  {nombres[1]}" if nueva_asignacion and nombres else f"Contrato N° {numero}"
        ttk.Label(cont, text=titulo, style="Detalle.TLabel", wraplength=740).pack(anchor="w")
        ayuda = ("El ejemplar firmado conserva sus datos y firmas. Estos cambios actualizan la asignación; "
                 "para emitir un nuevo ejemplar, vuelva a firmar el contrato." if documento_firmado else
                 "Estos datos se imprimen en los espacios en blanco del contrato. Revíselos antes de imprimir o firmar.")
        ttk.Label(cont, style="Tenue.TLabel", wraplength=740, text=ayuda).pack(anchor="w", pady=(4, 8))
        botones = ttk.Frame(cont)
        botones.pack(side="bottom", fill="x", pady=(12, 0))
        ttk.Button(botones, text="Confirmar asignación" if nueva_asignacion else "Guardar",
                   style="Primario.TButton", command=self.guardar).pack(side="right")
        ttk.Button(botones, text="Cancelar", style="Secundario.TButton",
                   command=self.destroy).pack(side="right", padx=8)
        self.desplazable = MarcoDesplazable(cont, padding=(0, 0, 10, 0))    # en pantallas bajas el formulario se desplaza
        self.desplazable.pack(fill="both", expand=True)
        self.form = Formulario(self.desplazable.interior, self.CAMPOS)
        self.form.pack(fill="both", expand=True)
        self.desplazable.activar_rueda()
        self._sincronizando = True
        self.form.poner(valores)
        self._sincronizando = False
        # el monto y el porcentaje se calculan uno a partir del otro; manda el último que se escribió
        self.manda = "porcentaje" if nueva_asignacion and PORCENTAJE_DEFECTO else "monto"
        for clave in ("porcentaje", "comision", "sueldo_acordado"):
            self.form.vars[clave].trace_add("write", lambda *_, c=clave: self.sincronizar(c))
        self.grab_set()

    def sincronizar(self, cambio):
        """Al escribir el porcentaje se calcula el monto; al escribir el monto, el porcentaje; al cambiar el
        sueldo se mantiene lo último que se escribió."""
        if self._sincronizando:
            return
        if cambio in ("porcentaje", "comision"):
            self.manda = "porcentaje" if cambio == "porcentaje" else "monto"
        self._sincronizando = True
        try:
            sueldo = self.form.valor("sueldo_acordado")
            if self.manda == "porcentaje":
                monto = monto_por_porcentaje(self.form.valor("porcentaje"), sueldo)
                if monto is not None:
                    self.form.poner_valor("comision", monto)
            elif leer_numero(self.form.valor("comision")) is not None:
                self.form.poner_valor("porcentaje", porcentaje_de(self.form.valor("comision"), sueldo))
        finally:
            self._sincronizando = False

    def guardar(self):
        d = self.form.obtener()
        error = validar_condiciones_financieras(d)
        if error:
            messagebox.showwarning("Datos del contrato", error, parent=self)
            return False
        d["meses_garantia"] = str(int(d["meses_garantia"] or 0))
        d["comision"] = importe_texto(d["comision"])
        d["porcentaje"] = porcentaje_de(d["comision"], d["sueldo_acordado"])
        if self.al_guardar(d) is not False:
            self.destroy()
            return True
        return False


def html_contrato(c, cli, t, imprimir=False):
    """Los dos contratos de la agencia, con el mismo formato que en papel:
    CONTRATO Y GARANTÍA (agencia y empleador) y CONTRATO DE TRABAJO (empleador y trabajadora)."""
    if c.get("contrato_firmado") == "1" and c.get("contrato_html"):
        documento = c["contrato_html"]
        if imprimir:
            documento = documento.replace("</body>", "<script>window.onload = () => setTimeout(() => window.print(), 400);</script></body>")
        return documento
    d = datos_contrato(c, cli)
    e = lambda x: html.escape(str(x or ""))
    agencia = f"“{AGENCIA_ESLOGAN.upper()}”"

    def campo(valor, clase=""):  # dato escrito sobre la línea punteada
        return f'<span class="campo {clase}">{e(valor) or "&nbsp;"}</span>'

    def fila(*partes):  # renglón con etiquetas en negrita y datos punteados
        return '<div class="fila">' + "".join(
            f"<b>{p[1]}</b>" if p[0] == "etiqueta" else campo(p[1], p[2]) for p in partes) + "</div>"

    def domicilio(p):
        return ", ".join(x for x in (p.get("direccion"), p.get("zona")) if x)

    def firma(clave, rol, nombre):
        return (f'<div class="firma"><div class="trazo">{html_firma(c.get(clave))}</div>'
                f'<div class="linea">{rol}</div><div class="quien">{e(nombre)}</div></div>')

    fecha = leer_fecha(d["fecha_contrato"]) or date.today()
    cierre = (f'<p class="cierre">En señal de conformidad con las cláusulas, en la ciudad de {e(CIUDAD_CONTRATO)}, '
              f'a los {campo(fecha.day, "corto")} días del mes de {campo(MESES_NOMBRE[fecha.month - 1], "medio")} '
              f'del {campo(fecha.year, "corto")}.</p>')
    nota = (f'<p class="nota">Firmas registradas en el sistema de la agencia el {e(c.get("fecha_firma"))}.</p>'
            if c.get("contrato_firmado") == "1" else "")
    numero = f'<div class="numero">Contrato N° {c["id"]}</div>'

    meses = int(d["meses_garantia"])
    monto = dinero(leer_decimal(d["comision"]) or 0)
    if c.get("reemplazo_de") and not leer_numero(d["comision"]):
        monto += f" (cambio de personal sin costo, garantía del contrato N° {e(c['reemplazo_de'])})"
    equivalencia = ""
    sueldo = leer_numero(d["sueldo_acordado"])
    porcentaje = porcentaje_de(d["comision"], d["sueldo_acordado"])
    if porcentaje and sueldo and (leer_numero(d["comision"]) or 0) > 0:
        equivalencia = (f", equivalente al {campo(porcentaje_en_letras(porcentaje), 'medio')} del sueldo mensual "
                        f"pactado de {campo(dinero(d['sueldo_acordado']), 'medio')}")
    if meses:
        plazo = f"{numero_en_letras(meses)} ({meses})"
        garantia = f"con una garantía de {campo(plazo, 'medio')} {'mes' if meses == 1 else 'meses'}"
        segunda = ("En caso de que LA TRABAJADORA contratada no cumpliera con los requerimientos que "
                   "“EL EMPLEADOR” solicitó, no se limita el cambio.")
        octava_fin = "no habrá devolución de dinero y procederemos al reemplazo de personal."
    else:
        garantia = "<b>sin garantía</b>, por decisión de “EL EMPLEADOR”"
        segunda = ("Por haber optado “EL EMPLEADOR” por el servicio sin garantía, LA AGENCIA no está obligada "
                   "a efectuar cambios del personal contratado.")
        octava_fin = "no habrá devolución de dinero."
    alojamiento = ", así como alojamiento y alimentación" if "adentro" in d["modalidad"].lower() else ""
    auto = "<script>window.onload = () => setTimeout(() => window.print(), 400);</script>" if imprimir else ""

    hoja1 = f"""<section class="hoja">{numero}
<h1>CONTRATO Y GARANTÍA</h1>
<p class="intro">Conste por el presente documento privado, el CONTRATO DE SERVICIO Y GARANTÍA que celebran,
de una parte, la agencia de empleos {e(agencia)}, con RUC N° {e(AGENCIA_RUC)} y domicilio fiscal en
{e(AGENCIA_DOMICILIO)}, en adelante LA AGENCIA; y de la otra parte, en adelante “EL EMPLEADOR”, bajo las
condiciones y cláusulas siguientes:</p>
{fila(("etiqueta", "SR(A)"), ("campo", cli.get("nombre"), "largo"),
      ("etiqueta", "Identificado con DNI N°"), ("campo", cli.get("dni"), "dni"))}
{fila(("etiqueta", "Domiciliado(a)"), ("campo", domicilio(cli), "largo"))}
{fila(("etiqueta", "Ocupación"), ("campo", cli.get("ocupacion"), "largo"),
      ("etiqueta", "Cel.:"), ("campo", cli.get("telefono"), "dni"))}
<p><b>PRIMERA:</b> “EL EMPLEADOR” abona un monto por la búsqueda y entrega de un personal calificado al momento de
firmar el presente contrato, cuyo pago será por única vez de {campo(monto, "medio")}{equivalencia}, {garantia}.</p>
<p><b>SEGUNDA:</b> {segunda}</p>
<p><b>TERCERA:</b> En caso de que “EL EMPLEADOR” no cumpliera con el pago del personal contratado y/o incurriera en
falta a las normas laborales según la Ley N° 31047 vigente, no tendrá opción a un siguiente reemplazo y/o se anulará
el presente contrato.</p>
<p><b>CUARTA:</b> Si “EL EMPLEADOR” decidiera finalizar la relación laboral, deberá cumplir con otorgar a LA
TRABAJADORA un preaviso de treinta (30) días calendario. En caso de CAMBIO del personal contratado, “EL EMPLEADOR”
se compromete a CANCELAR LOS DÍAS TRABAJADOS del personal contratado saliente, antes de efectuarse el cambio del
personal en nuestra oficina.</p>
<p><b>QUINTA:</b> “EL EMPLEADOR” facilitará a LA TRABAJADORA los materiales necesarios para que desarrolle sus
actividades. Asimismo, ambos, de mutuo acuerdo, podrán dar por finalizada la relación laboral; también se pueden
originar cambios no mencionados, pero sí verbales, dentro de la contratación por el presente documento.</p>
<p><b>SEXTA:</b> Si LA TRABAJADORA decidiera finalizar la presente relación laboral, deberá otorgar a
“EL EMPLEADOR” un plazo de preaviso de treinta (30) días calendario y esperar su reemplazo.</p>
<p><b>SÉPTIMA:</b> LA AGENCIA DE EMPLEOS {e(agencia)} no es responsable legal del comportamiento de LA
TRABAJADORA, quien será la única responsable. Asimismo, en caso de reconocerse perjuicios ocasionados a
“EL EMPLEADOR”, se procederá conforme a lo que por ley corresponda.</p>
<p><b>OCTAVA:</b> En caso de que “EL EMPLEADOR” desistiera de nuestros servicios dentro de las 24 horas de haber
suscrito el presente contrato, {octava_fin}</p>
{cierre}
<div class="firmas">{firma("firma_cliente", "EMPLEADOR", cli.get("nombre"))}
{firma("firma_agencia", "LA AGENCIA", f"{AGENCIA_NOMBRE} {agencia}")}</div>
{nota}</section>"""

    hoja2 = f"""<section class="hoja">{numero}
<h1>CONTRATO DE TRABAJO</h1>
<p class="intro">Conste por el presente documento privado, el CONTRATO DE TRABAJO que celebran, de una parte,
en adelante “EL EMPLEADOR”:</p>
{fila(("etiqueta", "SR(A)"), ("campo", cli.get("nombre"), "largo"),
      ("etiqueta", "Identificado con DNI N°"), ("campo", cli.get("dni"), "dni"))}
{fila(("etiqueta", "Domiciliado(a)"), ("campo", domicilio(cli), "largo"))}
{fila(("etiqueta", "Ocupación"), ("campo", cli.get("ocupacion"), "largo"))}
<p class="intro">y de la otra parte:</p>
{fila(("etiqueta", "SR(A)"), ("campo", t.get("nombre"), "largo"),
      ("etiqueta", "Identificado con DNI N°"), ("campo", t.get("dni"), "dni"))}
{fila(("etiqueta", "Domiciliado(a)"), ("campo", domicilio(t), "largo"))}
<p class="intro">en adelante LA TRABAJADORA, en los términos y condiciones siguientes:</p>
<p><b>PRIMERA:</b> “EL EMPLEADOR”, al estar de acuerdo, acepta y contrata al personal solicitado y se compromete
a pagar {campo(dinero(d["sueldo_acordado"]) if d["sueldo_acordado"] else "", "medio")} por los servicios prestados
en el puesto de {campo(d["puesto"], "medio")}. Modalidad: {campo(d["modalidad"], "medio")}.
Descanso los días: {campo(d["descanso"], "medio")}.</p>
<p><b>SEGUNDA:</b> La duración del contrato es por tiempo indefinido. Será celebrado en forma escrita. Si
“EL EMPLEADOR” decidiera finalizar la relación laboral, deberá cumplir con otorgar a LA TRABAJADORA un plazo de
preaviso de treinta (30) días calendario.</p>
<p><b>TERCERA:</b> LA TRABAJADORA del hogar está obligada a prestar sus servicios con diligencia y a guardar reserva
sobre la vida e incidentes en el hogar, salvo exigencia de la ley.</p>
<p><b>CUARTA:</b> “EL EMPLEADOR” deberá otorgar a LA TRABAJADORA los beneficios laborales según la Ley N° 31047
vigente. Formas de pago: por transferencia y/o boleta simple.</p>
<p><b>QUINTA:</b> “EL EMPLEADOR” facilitará a LA TRABAJADORA los materiales necesarios para que desarrolle sus
actividades{alojamiento}. Asimismo, ambos, de mutuo acuerdo, podrán dar por finalizada la relación laboral;
también se pueden originar cambios no mencionados, pero sí verbales, dentro de la contratación por el presente
documento.</p>
<p><b>SEXTA:</b> LA TRABAJADORA se compromete a respetar sus obligaciones derivadas de la Ley N° 31047, su
reglamentación y la legislación laboral vigente, así como las normas de seguridad del hogar. Asimismo, si decidiera
finalizar la presente relación laboral, deberá otorgar a “EL EMPLEADOR” un plazo de preaviso de treinta (30) días
calendario.</p>
<p><b>SÉPTIMA:</b> Por el presente contrato, LA TRABAJADORA cumplirá las labores señaladas en la cláusula primera,
de acuerdo con las directrices que emanen de “EL EMPLEADOR”, las que en todo momento deberán respetar sus derechos
y su dignidad.</p>
{cierre}
<div class="firmas">{firma("firma_cliente", "EMPLEADOR", cli.get("nombre"))}
{firma("firma_trabajadora", "TRABAJADORA", t.get("nombre"))}</div>
{nota}</section>"""

    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<title>Contrato N° {c['id']} · {e(cli.get('nombre'))}</title>
<style>
  @page {{ size: A4; margin: 12mm 16mm; }}
  body {{ margin: 0; background: #e8ecf2; color: #111;
         font-family: Calibri, Carlito, "Segoe UI", Arial, sans-serif; }}
  .barra {{ position: sticky; top: 0; background: #1B4DB1; color: #fff; padding: 10px 18px;
           display: flex; justify-content: space-between; align-items: center; font-size: 14px; }}
  .barra button {{ background: #E0282E; color: #fff; border: 0; padding: 8px 20px; font-size: 14px;
                  font-weight: bold; cursor: pointer; }}
  .hoja {{ background: #fff; width: 210mm; min-height: 297mm; margin: 18px auto;
          padding: 12mm 16mm; box-sizing: border-box; box-shadow: 0 2px 12px rgba(0,0,0,.18); }}
  .numero {{ text-align: right; font-size: 8pt; color: #888; margin: 0 0 2px; }}
  h1 {{ font-family: Cambria, Georgia, "Times New Roman", serif; font-size: 20pt; text-align: center;
       color: #3b3b3b; letter-spacing: .5px; margin: 0 0 10px; }}
  p {{ font-size: 10.5pt; line-height: 1.38; text-align: justify; margin: 0 0 6px; }}
  .intro {{ font-weight: bold; }}
  .fila {{ display: flex; align-items: baseline; gap: 6px; font-size: 10.5pt; margin: 0 0 7px; }}
  .fila b {{ white-space: nowrap; }}
  .campo {{ display: inline-block; border-bottom: 1.6px dotted #444; color: #1d3a8a; padding: 0 6px;
           min-width: 30px; text-align: center; font-weight: normal; }}
  .fila .largo {{ flex: 1; text-align: left; }}
  .fila .dni {{ min-width: 110px; }}
  .corto {{ min-width: 36px; }} .medio {{ min-width: 120px; }}
  .cierre {{ font-weight: bold; margin-top: 10px; }}
  .firmas {{ display: flex; justify-content: space-between; gap: 70px; margin-top: 28px;
            break-inside: avoid; }}
  .firma {{ flex: 1; text-align: center; }}
  .trazo {{ height: 62px; display: flex; align-items: flex-end; justify-content: center; }}
  .trazo svg {{ width: 100%; height: 62px; }}
  .nombre-firma {{ color: #13213F; font-family: "Segoe Script", "Snell Roundhand", "Apple Chancery",
                   "Brush Script MT", cursive; font-weight: normal; line-height: 1.1; white-space: nowrap; }}
  .linea {{ border-top: 1px solid #000; padding-top: 5px; font-weight: bold; font-size: 10.5pt; }}
  .quien {{ font-size: 8.5pt; color: #555; margin-top: 1px; }}
  .nota {{ text-align: center; font-size: 8.5pt; color: #777; margin-top: 12px; }}
  @media print {{
    body {{ background: #fff; }}
    .barra {{ display: none; }}
    .hoja {{ margin: 0; width: auto; min-height: 0; padding: 0; box-shadow: none; }}
    .hoja + .hoja {{ break-before: page; page-break-before: always; }}
  }}
</style>{auto}</head><body>
<div class="barra"><span>Contrato N° {c['id']} · {e(cli.get('nombre'))} y {e(t.get('nombre'))} · 2 hojas</span>
<button onclick="window.print()">Imprimir</button></div>
{hoja1}
{hoja2}
</body></html>"""


def trabaja_en(t, tipo):
    """Muestra en cada área solo su especialidad; otras se incluyen a petición."""
    return t.get("tipo_servicio") == tipo


class Tarjeta(tk.Frame):
    """Acceso a un área, disponible con el mouse y el teclado."""

    def __init__(self, master, titulo, descripcion, comando):
        factor = escala_pantalla(master)
        super().__init__(master, bg=C["fondo"], width=round(248 * factor), height=round(174 * factor),
                         highlightthickness=1, highlightbackground=C["borde"],
                         highlightcolor=C["acento"], cursor="hand2", takefocus=1)
        self.comando = comando
        self.pack_propagate(False)
        self.contenido = tk.Frame(self, bg=C["fondo"])
        self.contenido.pack(fill="both", expand=True, padx=22, pady=18)
        cabecera = tk.Frame(self.contenido, bg=C["fondo"])
        cabecera.pack(fill="x")
        self.acento = tk.Frame(cabecera, bg=C["azul_marca"], width=30, height=3)
        self.acento.pack(side="left")
        self.flecha = tk.Label(cabecera, text="→", bg=C["fondo"], fg=C["acento"],
                               font=F["numero"], anchor="e")
        self.flecha.pack(side="right")
        self.etiqueta = tk.Label(self.contenido, text=titulo, bg=C["fondo"],
                                 fg=C["texto"], font=F["detalle"], anchor="w")
        self.etiqueta.pack(fill="x", pady=(15, 4))
        self.descripcion = tk.Label(self.contenido, text=descripcion, bg=C["fondo"],
                                    fg=C["tenue"], font=F["pequena"], anchor="w",
                                    justify="left")
        self.descripcion.pack(fill="x")
        self.bind("<Configure>", lambda e: self.descripcion.configure(
            wraplength=max(140, e.width - 48)))
        self._enlazar(self)
        self.bind("<Return>", self._abrir)
        self.bind("<space>", self._abrir)
        self.bind("<FocusIn>", lambda e: self._pintar())
        self.bind("<FocusOut>", lambda e: self.after_idle(self._pintar))

    def _abrir(self, _evento=None):
        self.focus_set()
        self.comando()
        return "break"

    def _enlazar(self, w):
        w.configure(cursor="hand2")
        w.bind("<Button-1>", self._abrir)
        w.bind("<Enter>", lambda e: self._pintar())
        w.bind("<Leave>", lambda e: self.after(10, self._pintar))
        for hijo in w.winfo_children():
            self._enlazar(hijo)

    def _contiene(self, widget):
        while widget is not None:
            if widget is self:
                return True
            widget = widget.master
        return False

    def _pintar(self):
        x, y = self.winfo_pointerxy()
        activo = self._contiene(self.winfo_containing(x, y)) or self.focus_get() is self
        fondo = C["hover"] if activo else C["fondo"]
        self.configure(bg=fondo, highlightbackground=C["acento"] if activo else C["borde"])
        for widget in (self.contenido, self.acento.master, self.flecha,
                       self.etiqueta, self.descripcion):
            widget.configure(bg=fondo)
        self.acento.configure(bg=C["rojo"] if activo else C["azul_marca"])
        self.flecha.configure(fg=C["acento_osc"] if activo else C["acento"])


class PaginaAreas(ttk.Frame):
    """Un cuadro por cada área de trabajo; cada uno abre la vista para asignar. La agencia crea y elimina áreas."""
    titulo_pagina = "Áreas"

    def __init__(self, master, app):
        super().__init__(master)
        self.app, self.db = app, app.db
        cab = ttk.Frame(self, padding=(32, 26, 32, 18))
        cab.pack(fill="x")
        encabezado(cab, "Áreas", "Elija un área para asignar trabajadoras a clientes")
        ttk.Button(cab, text="Ver asignaciones", style="Secundario.TButton",
                   command=app.abrir_asignaciones).pack(side="right")
        ttk.Button(cab, text="Eliminar área…", style="Secundario.TButton",
                   command=lambda: DialogoAreas(app.root, app)).pack(side="right", padx=(0, 12))
        ttk.Button(cab, text="Nueva área", style="Primario.TButton",
                   command=app.nueva_area).pack(side="right", padx=(0, 12))
        divisor(self).pack(fill="x")
        self.grilla = ttk.Frame(self, padding=(32, 24, 32, 32), style="Fondo.TFrame")
        self.grilla.pack(fill="both", expand=True)
        self.tarjetas = None
        self.construir()

    def construir(self):
        """Dibuja un cuadro por cada área actual (se vuelve a llamar cuando se crea o elimina una)."""
        if self.tarjetas is not None:
            self.tarjetas.destroy()
        self.tarjetas = ttk.Frame(self.grilla, style="Fondo.TFrame")
        self.tarjetas.pack(fill="x")
        for columna in range(3):
            self.tarjetas.columnconfigure(columna, weight=1, uniform="areas")
        for i, (tipo, (titulo, descripcion)) in enumerate(AREAS.items()):
            tarjeta = Tarjeta(self.tarjetas, titulo, descripcion, lambda t=tipo: self.app.abrir_area(t))
            col = i % 3
            tarjeta.grid(row=i // 3, column=col, sticky="ew", pady=(0, 16),
                         padx=(0, 16) if col < 2 else 0)

    def refrescar(self):
        pass

    def contar(self):
        return sum(1 for c in self.db.todos("clientes") if c["estado"] in PEDIDOS_POR_ENLAZAR)


class DialogoAreas(tk.Toplevel):
    """Elegir qué área eliminar. Solo se pueden eliminar las que no tienen clientes ni trabajadoras."""

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.title("Eliminar área")
        self.configure(bg=C["fondo"])
        self.transient(master.winfo_toplevel())
        centrar(self, 720, 520, master.winfo_toplevel())
        cont = ttk.Frame(self, padding=(32, 26, 32, 22))
        cont.pack(fill="both", expand=True)
        ttk.Label(cont, text="Eliminar un área", style="Detalle.TLabel").pack(anchor="w")
        ttk.Label(cont, style="Tenue.TLabel", wraplength=650, justify="left", text=(
            "Solo se puede eliminar un área que no tenga clientes ni trabajadoras registrados. "
            "Antes de eliminar se guarda una copia de seguridad.")).pack(anchor="w", pady=(4, 14))
        marco, self.lista = crear_tabla(cont, [("area", "Área", 300), ("clientes", "Clientes", 110),
                                               ("trab", "Trabajadoras", 130)])
        marco.pack(fill="both", expand=True)
        pie = ttk.Frame(cont)
        # Antes que la lista en el orden de empaque: con poco espacio (pantalla chica o escala 125-150 %) se
        # achica la lista y los botones de abajo siguen visibles.
        pie.pack(side="bottom", fill="x", pady=(14, 0), before=marco)
        ttk.Button(pie, text="Cerrar", style="Secundario.TButton", command=self.destroy).pack(side="right")
        ttk.Button(pie, text="Eliminar el área elegida", style="Peligro.TButton",
                   command=self.eliminar).pack(side="right", padx=8)
        self.refrescar()
        self.grab_set()

    def refrescar(self):
        self.lista.delete(*self.lista.get_children())
        clientes, trabajadoras = self.app.db.todos("clientes"), self.app.db.todos("trabajadoras")
        for i, (nombre, (titulo, _)) in enumerate(AREAS.items()):
            self.lista.insert("", "end", iid=nombre, tags=("impar" if i % 2 else "par",), values=[PAD + str(v) for v in (
                titulo, sum(1 for c in clientes if c["tipo_servicio"] == nombre),
                sum(1 for t in trabajadoras if t["tipo_servicio"] == nombre))])

    def eliminar(self):
        sel = self.lista.selection()
        if not sel:
            messagebox.showinfo("Eliminar área", "Primero elija un área de la lista.", parent=self)
            return
        if self.app.eliminar_area(sel[0], parent=self):
            self.refrescar()


class PaginaEnlaces(ttk.Frame):
    """Lista de asignaciones (cliente ↔ trabajadora) con filtros y acciones."""
    titulo_pagina = ""
    subtitulo = ""
    filtros = []        # [(clave, texto)]; el primero es el que se cuenta en el menú
    columnas = []       # (clave, título, ancho)
    volver_a_areas = False
    mostrar_cantidad_pestanas = True
    mostrar_encabezado = True

    def __init__(self, master, app):
        super().__init__(master)
        self.app, self.db = app, app.db
        self.clientes, self.trabajadoras, self.atendidos = {}, {}, set()
        self.filtro = self.filtros[0][0]

        if self.mostrar_encabezado:
            cab = ttk.Frame(self, padding=(32, 26, 32, 16))
            cab.pack(fill="x")
            encabezado(cab, self.titulo_pagina, self.subtitulo,
                       volver=app.volver_de_asignaciones if self.volver_a_areas else None,
                       texto_volver="←  Volver a Áreas")
        elif self.volver_a_areas:
            cab = ttk.Frame(self, padding=(32, 12, 32, 8))
            cab.pack(fill="x")
            ttk.Button(cab, text="←  Volver a Áreas", style="Enlace.TButton",
                       command=app.volver_de_asignaciones).pack(side="left")
        else:
            ttk.Frame(self, height=20).pack(fill="x")
        self.pestanas = crear_pestanas(self, self.filtros, self.poner_filtro)
        divisor(self).pack(fill="x")

        cuerpo = ttk.Frame(self, style="Fondo.TFrame", padding=(32, 24, 32, 28))
        cuerpo.pack(fill="both", expand=True)
        self.cifras = {}
        definicion = self.definir_cifras()
        if definicion:
            fila = ttk.Frame(cuerpo, style="Fondo.TFrame")
            fila.pack(fill="x", pady=(0, 20))
            for i, (clave, texto, color) in enumerate(definicion):
                fila.columnconfigure(i, weight=1, uniform="indicador")
                borde, dentro = tarjeta(fila)
                borde.grid(row=0, column=i, sticky="nsew",
                           padx=(0 if i == 0 else 7, 0 if i == len(definicion) - 1 else 7))
                dentro.configure(padding=(20, 17, 20, 18))
                tk.Frame(dentro, bg=color, width=30, height=3).pack(anchor="w", pady=(0, 13))
                etiqueta = ttk.Label(dentro, text=texto, style="Tenue.TLabel", justify="left")
                etiqueta.pack(anchor="w")
                dentro.bind("<Configure>", lambda e, w=etiqueta: w.configure(
                    wraplength=max(100, e.width - 40)))
                numero = ttk.Label(dentro, text="0", font=F["titulo"], foreground=color)
                numero.pack(anchor="w", pady=(8, 0))
                self.cifras[clave] = numero

        borde, tabla = tarjeta(cuerpo)
        borde.pack(fill="both", expand=True)
        tabla.configure(padding=(24, 20, 24, 20))
        cab_tabla = ttk.Frame(tabla)
        cab_tabla.pack(fill="x")
        ttk.Label(cab_tabla, text="Asignaciones", font=F["marca"]).pack(side="left")

        self.botones_accion = []
        acciones = self.definir_acciones()
        secundarias = ttk.Frame(tabla)
        for texto, comando, estilo in acciones:
            destino = cab_tabla if estilo == "Primario.TButton" else secundarias
            boton = ttk.Button(destino, text=texto, style=estilo, state="disabled",
                               command=lambda c=comando: self.con_seleccion(c))
            if destino is cab_tabla:
                boton.pack(side="right")
            else:
                boton.pack(side="left", padx=(0, 8))
            self.botones_accion.append(boton)

        contexto = tk.Frame(tabla, bg=C["campo"], highlightthickness=1,
                           highlightbackground=C["borde"])
        contexto.pack(fill="x", pady=(18, 0))
        self.marca_seleccion = tk.Frame(contexto, bg=C["borde"], width=3)
        self.marca_seleccion.pack(side="left", fill="y")
        self.info = tk.Label(contexto, text="Seleccione una asignación para activar las acciones",
                             bg=C["campo"], fg=C["tenue"], font=F["base"], anchor="w",
                             justify="left", padx=14, pady=12)
        self.info.pack(side="left", fill="x", expand=True)
        contexto.bind("<Configure>", lambda e: self.info.configure(
            wraplength=max(150, e.width - 40)))
        if acciones and secundarias.winfo_children():
            secundarias.pack(fill="x", pady=(14, 0))
        marco, self.lista = crear_tabla(tabla, self.columnas)
        marco.pack(fill="both", expand=True, pady=(18, 0))
        self.barra_horizontal = ttk.Scrollbar(tabla, orient="horizontal", command=self.lista.xview)
        self.lista.configure(xscrollcommand=self.barra_horizontal.set)
        self.lista.bind("<Configure>", self._ajustar_barra_horizontal, add="+")
        self.after_idle(self._ajustar_barra_horizontal)
        self.lista.bind("<<TreeviewSelect>>", lambda e: self.actualizar_info())
        pintar_pestanas(self.pestanas, self.filtro)

    # --- lo que cada sección define
    def definir_cifras(self):
        return []           # [(clave, texto, color)]

    def definir_acciones(self):
        return []           # [(texto, función que recibe el enlace, estilo)]

    def incluir(self, c):
        return True

    def en_filtro(self, c, filtro):
        return True

    def valores(self, c):
        return []

    def etiqueta(self, c):
        return ()

    def actualizar_cifras(self, enlaces):
        pass

    # --- comportamiento común
    def poner_filtro(self, clave):
        self.filtro = clave
        pintar_pestanas(self.pestanas, clave)
        self.refrescar()

    def _ajustar_barra_horizontal(self, _evento=None):
        ancho_columnas = sum(self.lista.column(clave, "width") for clave, _, _ in self.columnas)
        visible = ancho_columnas > self.lista.winfo_width() + 2
        if visible and not self.barra_horizontal.winfo_manager():
            self.barra_horizontal.pack(fill="x", pady=(6, 0))
        elif not visible and self.barra_horizontal.winfo_manager():
            self.barra_horizontal.pack_forget()
            self.lista.xview_moveto(0)

    def nombre(self, c, quien):
        if quien == "cliente":
            return self.clientes.get(c["cliente_id"], {}).get("nombre", "(borrado)")
        return self.trabajadoras.get(c["trabajadora_id"], {}).get("nombre", "(borrada)")

    def _preparar_enlaces(self):
        todos = self.db.todos("colocaciones")
        fecha_hoy = date.today()
        if getattr(self, "_enlaces_fuente", None) is not todos or getattr(self, "_enlaces_fecha", None) != fecha_hoy:
            self.atendidos = self.app.reemplazos_atendidos(todos)
            self._enlaces = [c for c in todos if self.incluir(c)]
            self._enlaces_filtros = {clave: [c for c in self._enlaces if self.en_filtro(c, clave)]
                                     for clave, _ in self.filtros}
            self._enlaces_fuente, self._enlaces_fecha = todos, fecha_hoy
        return self._enlaces

    def refrescar(self):
        clientes = self.db.todos("clientes")
        trabajadoras = self.db.todos("trabajadoras")
        if getattr(self, "_clientes_fuente", None) is not clientes:
            self.clientes = {str(c["id"]): c for c in clientes}
            self._clientes_fuente = clientes
        if getattr(self, "_trabajadoras_fuente", None) is not trabajadoras:
            self.trabajadoras = {str(t["id"]): t for t in trabajadoras}
            self._trabajadoras_fuente = trabajadoras
        enlaces = self._preparar_enlaces()
        firma_areas = tuple(AREAS.items())
        clave = (self.db.revision("colocaciones"), self.db.revision("clientes"),
                 self.db.revision("trabajadoras"), self._enlaces_fecha, firma_areas)
        if getattr(self, "_enlaces_render", None) == (clave, self.filtro):
            self.actualizar_info()
            return
        for filtro, texto in self.filtros:
            etiqueta = f"{texto}  {len(self._enlaces_filtros[filtro])}" if self.mostrar_cantidad_pestanas else texto
            if self.pestanas[filtro][0].cget("text") != etiqueta:
                self.pestanas[filtro][0].configure(text=etiqueta)
        if not hasattr(self, "_enlaces_valores"):
            self._enlaces_valores, self._enlaces_estado = {}, {}
        entradas = []
        for indice, c in enumerate(self._enlaces_filtros[self.filtro]):
            iid = str(c["id"])
            cli, trab = self.clientes.get(c["cliente_id"]), self.trabajadoras.get(c["trabajadora_id"])
            dependencias = (c, cli, trab, self._enlaces_fecha, firma_areas,
                            iid in self.atendidos)
            anterior = self._enlaces_valores.get(iid)
            if (anterior is None or any(a is not b for a, b in zip(anterior[0][:3], dependencias[:3]))
                    or anterior[0][3:] != dependencias[3:]):
                anterior = (dependencias, [PAD + str(v) for v in self.valores(c)], self.etiqueta(c))
                self._enlaces_valores[iid] = anterior
            entradas.append((iid, anterior[1], anterior[2] or (("impar",) if indice % 2 else ("par",))))
        vivos = {str(c["id"]) for c in self._enlaces_fuente}
        Pagina._sincronizar_tabla(self.lista, self._enlaces_estado, entradas, vivos)
        if getattr(self, "_cifras_clave", None) != clave:
            self.actualizar_cifras(enlaces)
            self._cifras_clave = clave
        for iid in self._enlaces_valores.keys() - vivos:
            del self._enlaces_valores[iid]
        self._enlaces_render = (clave, self.filtro)
        self.actualizar_info()

    def contar(self):
        """Comparte los filtros ya calculados entre el menú y la lista."""
        self._preparar_enlaces()
        return len(self._enlaces_filtros[self.filtros[0][0]])

    def actualizar_info(self):
        sel = self.lista.selection()
        c = self.db.uno("colocaciones", int(sel[0])) if sel else None
        self.info.config(text=f"{self.nombre(c, 'cliente')}   ↔   {self.nombre(c, 'trabajadora')}"
                         if c else "Seleccione una asignación para activar las acciones",
                         fg=C["texto"] if c else C["tenue"],
                         font=F["negrita"] if c else F["base"])
        self.marca_seleccion.configure(bg=C["azul_marca"] if c else C["borde"])
        for boton in self.botones_accion:
            boton.configure(state="normal" if c else "disabled")

    def con_seleccion(self, accion):
        sel = self.lista.selection()
        if not sel:
            messagebox.showinfo(self.titulo_pagina, "Primero elija una asignación de la lista.", parent=self)
            return
        version_antes = self.db.version
        accion(self.db.uno("colocaciones", int(sel[0])))
        if self.db.version != version_antes:
            self.app.refrescar_todo()

    # --- acciones compartidas
    def registrar_inicio(self, c):
        if c["estado"] != "En proceso":
            messagebox.showinfo("Inicio de trabajo",
                                f"Esta asignación ya tiene inicio registrado: {c['fecha_inicio'] or '-'}.",
                                parent=self)
            return
        texto = pedir_texto(
            self, "Inicio de trabajo", f"¿Qué día empieza {self.nombre(c, 'trabajadora')} a trabajar?\n"
            "(dd/mm/aaaa)", hoy())
        if texto is None:
            return
        inicio = leer_fecha(texto)
        if not inicio:
            messagebox.showwarning("Inicio de trabajo", "Escriba la fecha así: dd/mm/aaaa.", parent=self)
            return
        try:
            if not self.app.iniciar_asignacion(c, inicio):
                messagebox.showwarning("Inicio no registrado", "La asignación o la disponibilidad cambió. "
                                       "Revise el cliente y la trabajadora antes de registrar el inicio.", parent=self)
        except (ValueError, OverflowError, sqlite3.Error) as error:
            messagebox.showwarning("Inicio no registrado", str(error), parent=self)

    def imprimir_contrato(self, c):
        cli = leer_registro_actual(self.db, "clientes", c["cliente_id"])
        t = leer_registro_actual(self.db, "trabajadoras", c["trabajadora_id"])
        if not (c.get("contrato_firmado") == "1" and c.get("contrato_html")) and not (cli and t):
            messagebox.showwarning("Contrato", "El cliente o la trabajadora de esta asignación fue borrado.", parent=self)
            return
        os.makedirs(CARPETA_CONTRATOS, exist_ok=True)
        ruta = Path(CARPETA_CONTRATOS) / f"contrato_{c['id']}.html"
        documento = html_contrato(c, cli or {}, t or {}, imprimir=True)
        try:
            with archivo_atomico(ruta) as archivo:
                archivo.write(documento)
        except PermissionError:
            # En Windows no se puede reemplazar un archivo abierto en otro programa (Word, el navegador...):
            # se imprime una copia con otro nombre en vez de fallar.
            ruta = ruta.with_name(f"contrato_{c['id']}_{datetime.now():%Y%m%d-%H%M%S}.html")
            with archivo_atomico(ruta) as archivo:
                archivo.write(documento)
        if ES_WINDOWS:
            os.startfile(str(ruta))    # el programa predeterminado para .html, sin pasar por una URL file://
        else:
            import webbrowser
            webbrowser.open(ruta.as_uri())


class AccionRechazada(ValueError):
    def __init__(self, titulo, mensaje):
        super().__init__(mensaje)
        self.titulo = titulo


def leer_registro_actual(db, tabla, id_):
    """Lee dentro de la transacción actual sin reutilizar una ficha anterior."""
    if tabla not in TABLAS and tabla != "areas":
        raise ValueError("Tabla desconocida.")
    fila = db.con.execute(f"SELECT * FROM {tabla} WHERE id=?", (id_,)).fetchone()
    return db._fila(fila) if fila is not None else None


class PaginaContratos(PaginaEnlaces):
    titulo_pagina = "Asignaciones"
    subtitulo = "Contrato y garantía + contrato de trabajo: datos, firmas e impresión"
    volver_a_areas = True
    mostrar_encabezado = False
    filtros = [("por_firmar", "Por firmar"), ("firmados", "Firmados")]
    columnas = [("n", "N°", 50), ("cliente", "Cliente", 180), ("trab", "Trabajadora", 180),
                ("area", "Área", 130), ("fecha", "Asignado", 110), ("garantia", "Garantía", 90),
                ("contrato", "Contrato", 190)]

    def definir_acciones(self):
        return [("Deshacer asignación", self.deshacer, "Peligro.TButton"),
                ("Registrar inicio", self.registrar_inicio, "Accion.TButton"),
                ("Datos del contrato", self.editar_datos, "Accion.TButton"),
                ("Imprimir", self.imprimir_contrato, "Accion.TButton"),
                ("Firmar contrato", self.firmar, "Primario.TButton")]

    def en_filtro(self, c, filtro):
        firmado = c["contrato_firmado"] == "1"
        if filtro == "por_firmar":
            return not firmado and c["estado"] in ("En proceso", "Activa")
        if filtro == "firmados":
            return firmado
        return False

    def valores(self, c):
        tipo = self.clientes.get(c["cliente_id"], {}).get("tipo_servicio")
        return [c["id"], self.nombre(c, "cliente"), self.nombre(c, "trabajadora"),
                AREAS.get(tipo, ("-",))[0], c["fecha_enlace"] or "-",
                f"{meses_de_garantia(c)} meses" if con_garantia(c) else "No",
                f"Firmado  {c['fecha_firma'][:10]}" if c["contrato_firmado"] == "1" else "Sin firmar"]

    def editar_datos(self, c):
        self.db.cambio_externo()
        c = leer_registro_actual(self.db, "colocaciones", c["id"])
        cli = leer_registro_actual(self.db, "clientes", c["cliente_id"]) if c else None
        if not (c and cli):
            messagebox.showwarning("Contrato", "La asignación o su cliente fue eliminado.", parent=self)
            return
        originales = dict(datos_contrato(c, cli), ocupacion=cli.get("ocupacion") or "")

        def guardar(datos):
            d = dict(datos)
            ocupacion = d.pop("ocupacion")
            error = validar_condiciones_financieras(d)
            if error:
                messagebox.showwarning("Datos del contrato", error, parent=self)
                return False
            if "dias_garantia" in d:
                normalizar_plazo(d)
            else:
                d["garantia"] = "Sí" if int(d["meses_garantia"]) else "No"
            d["porcentaje"] = porcentaje_de(d["comision"], d["sueldo_acordado"])
            try:
                with self.db.lote():
                    self.db.con.execute("UPDATE colocaciones SET estado=estado WHERE 0")
                    actual = leer_registro_actual(self.db, "colocaciones", c["id"])
                    cliente = leer_registro_actual(self.db, "clientes", cli["id"])
                    if actual != c or cliente != cli:
                        raise AccionRechazada("Cambios simultáneos",
                            "La asignación o el cliente cambió mientras revisaba el contrato. "
                            "Lo escrito se conserva; cierre y abra los datos actualizados antes de guardar.")
                    if actual["comision_pagada"] == "1" and leer_decimal(d["comision"]) != leer_decimal(actual["comision"]):
                        raise AccionRechazada("Comisión cobrada",
                            "Este importe ya está cobrado. Deshaga el cobro antes de corregirlo y regístrelo de nuevo.")
                    inicio = leer_fecha(actual["fecha_inicio"])
                    if inicio:
                        acuerdo = dict(actual, **d)
                        try:
                            fin = vencimiento_garantia(origen_garantia(acuerdo, inicio), acuerdo)
                        except (ValueError, OverflowError):
                            raise AccionRechazada("Datos del contrato", "El plazo produce una fecha fuera del rango admitido.")
                        d["fin_garantia"] = fin.strftime(FMT_FECHA) if fin else ""
                    cambios = {k: v for k, v in d.items() if actual.get(k) != v}
                    if cambios:
                        self.db.actualizar("colocaciones", actual["id"], cambios)
                    if ocupacion != (cliente.get("ocupacion") or ""):
                        self.db.actualizar("clientes", cliente["id"], {"ocupacion": ocupacion})
            except AccionRechazada as error:
                messagebox.showwarning(error.titulo, str(error), parent=self)
                return False
            self.app.refrescar_todo()
            return True

        DialogoContrato(self, c["id"], originales, guardar,
                        documento_firmado=c["contrato_firmado"] == "1")

    def firmar(self, c):
        self.db.cambio_externo()
        c = leer_registro_actual(self.db, "colocaciones", c["id"])
        cli = leer_registro_actual(self.db, "clientes", c["cliente_id"]) if c else None
        t = leer_registro_actual(self.db, "trabajadoras", c["trabajadora_id"]) if c else None
        if not (c and cli and t):
            messagebox.showwarning("Firmar", "La asignación, el cliente o la trabajadora fue eliminado.", parent=self)
            return
        error = validar_condiciones_financieras(datos_contrato(c, cli))
        if error:
            messagebox.showwarning("Firmar", error + "\nRevise los datos del contrato antes de firmar.", parent=self)
            return
        if c["contrato_firmado"] == "1" and not messagebox.askyesno(
                "Firmar", "Este contrato ya está firmado.\n¿Firmarlo de nuevo? "
                          "Las firmas anteriores se reemplazarán.", parent=self):
            return

        def guardar(firmas):
            if not all(html_firma(firmas.get(k)) for k in ("firma_cliente", "firma_trabajadora")):
                messagebox.showwarning("Firmar", "Faltan firmas válidas del empleador y de la trabajadora.", parent=self)
                return False
            firmado = dict(firmas, contrato_firmado="1",
                           fecha_firma=datetime.now().strftime(FMT_FECHA + " %H:%M"))
            try:
                with self.db.lote():
                    self.db.con.execute("UPDATE colocaciones SET estado=estado WHERE 0")
                    actual = leer_registro_actual(self.db, "colocaciones", c["id"])
                    cliente = leer_registro_actual(self.db, "clientes", cli["id"])
                    trabajadora = leer_registro_actual(self.db, "trabajadoras", t["id"])
                    if actual != c or cliente != cli or trabajadora != t:
                        raise AccionRechazada("Cambios simultáneos",
                            "Los datos del contrato cambiaron mientras se firmaba. Las firmas no se guardaron. "
                            "Cierre esta ventana y revise el contrato actualizado antes de firmarlo.")
                    self.db.actualizar("colocaciones", actual["id"], firmado)
                    self.app.iniciar_contratos_firmados()
                    actual = self.db.uno("colocaciones", c["id"])
                    documento = html_contrato(dict(actual, contrato_html=""), cliente, trabajadora)
                    self.db.actualizar("colocaciones", c["id"], {"contrato_html": documento})
            except AccionRechazada as error:
                messagebox.showwarning(error.titulo, str(error), parent=self)
                return False
            self.app.refrescar_todo()
            if messagebox.askyesno("Firmas guardadas", "¿Imprimir el contrato ahora?", parent=self):
                self.imprimir_contrato(self.db.uno("colocaciones", c["id"]))
            return True

        DialogoFirmas(self, c, cli, t, guardar)

    def deshacer(self, c):
        if messagebox.askyesno(
                "Deshacer asignación",
                f"¿Deshacer la asignación de {self.nombre(c, 'trabajadora')} a "
                f"{self.nombre(c, 'cliente')}?"
                "\n\nSe liberarán sus vínculos. Las personas con otra asignación conservarán su estado; "
                "los antecedentes necesarios para reemplazos se conservarán." + describir_perdida([c])
                + "\n\nAntes se guarda una copia de seguridad, por si se equivoca.", parent=self):
            if self.app.copia_antes_de_borrar():
                try:
                    if not self.app.deshacer_enlace(c):
                        messagebox.showwarning("Deshacer", "La asignación ya fue eliminada.", parent=self)
                except (ValueError, sqlite3.Error) as error:
                    messagebox.showwarning("No se pudo deshacer", str(error), parent=self)


class PaginaComisiones(PaginaEnlaces):
    titulo_pagina = "Comisiones"
    subtitulo = "Lo que cada cliente paga a la agencia"
    mostrar_encabezado = False
    mostrar_cantidad_pestanas = False
    filtros = [("por_cobrar", "Por cobrar"), ("cobradas", "Cobradas")]
    columnas = [("n", "N°", 50), ("cliente", "Cliente", 180), ("trab", "Trabajadora", 180),
                ("sueldo", "Sueldo", 110), ("pct", "%", 60), ("comision", "Comisión", 120),
                ("estado", "Estado", 190)]

    def definir_cifras(self):
        return [("por_cobrar", "por cobrar", C["peligro"]),
                ("cobrado_total", "cobrado en total", C["acento"]),
                ("cobrado_mes", "cobrado este mes", C["texto"])]

    def actualizar_cifras(self, enlaces):
        resumen = self.app.resumen_financiero()
        for clave, etiqueta in self.cifras.items():
            etiqueta.configure(text=dinero(resumen[clave]))

    def definir_acciones(self):
        return [("Marcar como no pagada", self.no_pagada, "Accion.TButton"),
                ("Cambiar sueldo o monto", self.cambiar_monto, "Accion.TButton"),
                ("Marcar como pagada", self.pagada, "Primario.TButton")]

    def en_filtro(self, c, filtro):
        if filtro == "por_cobrar":
            return (leer_numero(c["comision"]) or 0) > 0 and c["comision_pagada"] != "1"
        if filtro == "cobradas":
            return c["comision_pagada"] == "1"
        return True

    def valores(self, c):
        monto = leer_numero(c["comision"]) or 0
        if c["comision_pagada"] == "1":
            estado = f"Pagada  {c['fecha_pago']}"
        elif c["reemplazo_de"] and monto == 0:
            estado = "Sin costo (reemplazo)"
        else:
            estado = "Por cobrar"
        return [c["id"], self.nombre(c, "cliente"), self.nombre(c, "trabajadora"),
                dinero_corto(c["sueldo_acordado"]), f"{c['porcentaje'] or '-'}%",
                dinero(c["comision"]) if c["comision"] else "-", estado]

    def etiqueta(self, c):
        return ("alerta",) if self.en_filtro(c, "por_cobrar") else ()

    _campos_financieros = ("sueldo_acordado", "comision", "porcentaje", "comision_pagada", "fecha_pago")

    def _comision_actual(self, c, avisar=True):
        """Lee SQLite directamente: una selección antigua nunca decide sobre un cobro nuevo."""
        self.db.cambio_externo()
        fila = self.db.con.execute("SELECT * FROM colocaciones WHERE id = ?", (c["id"],)).fetchone() if c else None
        actual = self.db._fila(fila) if fila is not None else None
        coincide = actual is not None and all(
            actual.get(clave, "") == str(c.get(clave) or "") for clave in self._campos_financieros)
        if not coincide:
            if avisar:
                messagebox.showwarning("Comisión", "La asignación o sus datos de cobro cambiaron. "
                                       "Vuelva a seleccionarla y revise los valores antes de continuar.", parent=self)
            return None
        return actual

    def _guardar_finanzas(self, c, datos):
        """Compara y escribe dentro de la misma transacción, después de cerrar los diálogos."""
        error = None
        try:
            with self.db.lote():
                self.db.con.execute("UPDATE colocaciones SET comision=comision WHERE 0")
                actual = self._comision_actual(c, avisar=False)
                if actual is None:
                    error = "La asignación o sus datos de cobro cambiaron. No se guardó la operación."
                elif actual["comision_pagada"] == "1" and any(
                        clave in datos and str(datos[clave]) != actual[clave]
                        for clave in ("comision", "sueldo_acordado", "porcentaje")):
                    error = "Esta comisión ya está cobrada. El importe registrado del cobro se conserva."
                else:
                    self.db.actualizar("colocaciones", actual["id"], datos)
        except sqlite3.Error as problema:
            messagebox.showwarning("Comisión", f"No se pudo guardar la operación: {problema}", parent=self)
            return False
        if error:
            messagebox.showwarning("Comisión", error, parent=self)
            return False
        return True

    def pagada(self, c):
        actual = self._comision_actual(c)
        if actual is None:
            return False
        if actual["comision_pagada"] == "1":
            messagebox.showinfo("Comisión", f"Ya está pagada ({actual['fecha_pago']}).", parent=self)
            return False
        monto = leer_decimal(actual["comision"])
        if monto is None or monto <= 0:
            messagebox.showinfo("Comisión", "Esta asignación no tiene una comisión válida pendiente de cobro.", parent=self)
            return False
        return self._guardar_finanzas(actual, {"comision_pagada": "1", "fecha_pago": hoy()})

    def no_pagada(self, c):
        actual = self._comision_actual(c)
        if actual is None or actual["comision_pagada"] != "1":
            return False
        if messagebox.askyesno("Comisión", "¿Marcar esta comisión como NO pagada?", parent=self):
            return self._guardar_finanzas(actual, {"comision_pagada": "0", "fecha_pago": ""})
        return False

    def cambiar_monto(self, c):
        actual = self._comision_actual(c)
        if actual is None:
            return False
        if actual["comision_pagada"] == "1":
            messagebox.showinfo("Comisión", "Esta comisión ya está cobrada. "
                                "El importe registrado del cobro se conserva.", parent=self)
            return False
        sueldo = pedir_texto(self, "Sueldo acordado", f"Sueldo mensual acordado ({MONEDA}):",
                             actual["sueldo_acordado"])
        if sueldo is None:
            return False
        porcentaje = pedir_texto(
            self, "Porcentaje", "Comisión como porcentaje del sueldo (por ejemplo 20).\n"
            "Déjelo vacío para escribir el monto directamente:", porcentaje_de(actual["comision"], sueldo))
        if porcentaje is None:
            return False
        monto = monto_por_porcentaje(porcentaje, sueldo) if porcentaje.strip() else None
        if monto is None and porcentaje.strip():
            messagebox.showwarning("Comisión", "Escriba un porcentaje no negativo y un sueldo positivo, ambos finitos, "
                                   "que produzcan un importe válido.", parent=self)
            return False
        if monto is None:
            monto = pedir_texto(self, "Monto", f"Monto que paga el empleador a la agencia ({MONEDA}):",
                                actual["comision"])
            if monto is None:
                return False
        datos = dict(sueldo_acordado=sueldo.strip(), comision=monto, porcentaje=porcentaje.strip())
        error = validar_condiciones_financieras(datos)
        if not datos["sueldo_acordado"]:
            error = "Escriba el sueldo acordado como un número finito positivo."
        if error:
            messagebox.showwarning("Comisión", error, parent=self)
            return False
        normalizado = importe_texto(monto)
        datos.update(comision=normalizado, porcentaje=porcentaje_de(normalizado, sueldo))
        return self._guardar_finanzas(actual, datos)


class PaginaGarantias(PaginaEnlaces):
    titulo_pagina = "Garantías"
    subtitulo = "Los meses que acordó cada cliente, desde la fecha del contrato, con cambio de personal sin costo"
    mostrar_encabezado = False
    mostrar_cantidad_pestanas = False
    filtros = [("pendientes", "Pendientes"), ("cerradas", "Cerradas"), ("sin_garantia", "Sin garantía")]
    columnas = [("n", "N°", 50), ("cliente", "Cliente", 180), ("trab", "Trabajadora", 180),
                ("meses", "Garantía", 100), ("inicio", "Inicio", 110), ("vence", "Vence", 110),
                ("situacion", "Situación", 200)]

    def definir_cifras(self):
        return [("sin_iniciar", "sin iniciar", C["texto"]), ("vigentes", "vigentes", C["acento"]),
                ("por_vencer", "vencen en 7 días o menos", C["peligro"]),
                ("reemplazos", "reemplazos por atender", C["peligro"])]

    def definir_acciones(self):
        return [("Dar por cumplida", self.cumplida, "Accion.TButton"),
                ("Solicitar reemplazo", self.solicitar_reemplazo, "Accion.TButton"),
                ("Buscar reemplazante", self.buscar_reemplazante, "Accion.TButton"),
                ("Registrar inicio", self.registrar_inicio, "Primario.TButton")]

    def situacion(self, c):
        return situacion_garantia(c, self.atendidos)

    def en_filtro(self, c, filtro):
        if filtro == "sin_garantia":
            return not con_garantia(c)
        if not con_garantia(c):
            return False
        return self.situacion(c)[1] == (filtro == "pendientes")

    def dias(self, c):
        fin = leer_fecha(c["fin_garantia"])
        return (fin - date.today()).days if fin and c["estado"] == "Activa" else None

    def valores(self, c):
        return [c["id"], self.nombre(c, "cliente"), self.nombre(c, "trabajadora"),
                texto_meses(meses_de_garantia(c)) if con_garantia(c) else "-",
                c["fecha_inicio"] or "-", c["fin_garantia"] or "-", self.situacion(c)[0]]

    def etiqueta(self, c):
        dias = self.dias(c)
        urgente = (dias is not None and 0 <= dias <= 7) or self.situacion(c)[0] == "Reemplazo por atender"
        return ("alerta",) if urgente else ()

    def actualizar_cifras(self, enlaces):
        enlaces = [c for c in enlaces if con_garantia(c)]
        situaciones = [self.situacion(c)[0] for c in enlaces]
        vigentes = [c for c in enlaces if self.dias(c) is not None and self.dias(c) >= 0]
        self.cifras["sin_iniciar"].config(text=str(situaciones.count("Sin iniciar")))
        self.cifras["vigentes"].config(text=str(len(vigentes)))
        self.cifras["por_vencer"].config(text=str(sum(1 for c in vigentes if self.dias(c) <= 7)))
        self.cifras["reemplazos"].config(text=str(situaciones.count("Reemplazo por atender")))

    def solicitar_reemplazo(self, c):
        if not con_garantia(c):
            messagebox.showinfo("Reemplazo", "Este cliente no tiene garantía, así que no incluye reemplazo.",
                                parent=self)
            return
        if c["estado"] not in ("En proceso", "Activa"):
            messagebox.showinfo("Reemplazo", f"Esta asignación está en «{self.situacion(c)[0]}».", parent=self)
            return
        cliente, trab = self.nombre(c, "cliente"), self.nombre(c, "trabajadora")
        fin = leer_fecha(c["fin_garantia"])
        aviso = f"OJO: la garantía venció el {c['fin_garantia']}.\n\n" if fin and date.today() > fin else ""
        if not messagebox.askyesno(
                "Solicitar reemplazo",
                f"{aviso}¿Solicitar reemplazo para {cliente}?\n\nSe liberarán los vínculos de esta asignación. "
                f"{trab} y {cliente} conservarán su estado si tienen otra asignación. "
                "La próxima asignación de reemplazo no cobra comisión.", parent=self):
            return
        try:
            self.app.solicitar_reemplazo(c)
        except (ValueError, sqlite3.Error) as error:
            messagebox.showwarning("No se pudo solicitar", str(error), parent=self)
            return
        if messagebox.askyesno("Reemplazo", "¿Buscar ahora a la reemplazante?", parent=self):
            self.app.nueva_colocacion(c["cliente_id"])

    def buscar_reemplazante(self, c):
        self.db.cambio_externo()
        actual = self.app.reemplazo_pendiente(c["cliente_id"])
        if not actual or actual["id"] != c["id"]:
            messagebox.showinfo("Reemplazo", "Revise la solicitud pendiente; use «Solicitar reemplazo» "
                                "si esta asignación todavía no tiene una solicitud.", parent=self)
            return
        self.app.nueva_colocacion(actual["cliente_id"])

    def cumplida(self, c):
        if not con_garantia(c):
            messagebox.showinfo("Garantía", "Este cliente no tiene garantía.", parent=self)
            return
        if c["estado"] != "Activa":
            messagebox.showinfo("Garantía", "Solo se puede dar por cumplida una garantía vigente.",
                                parent=self)
            return
        if messagebox.askyesno("Garantía", f"¿Dar por cumplida la garantía de {self.nombre(c, 'cliente')}?",
                               parent=self):
            try:
                self.app.cumplir_garantia(c)
            except (ValueError, sqlite3.Error) as error:
                messagebox.showwarning("No se pudo completar", str(error), parent=self)


class PaginaGanancias(ttk.Frame):
    """Vista general de los ingresos de la agencia por comisiones."""
    titulo_pagina = "Ganancias"

    def __init__(self, master, app):
        super().__init__(master)
        self.app, self.db = app, app.db
        self.resumen = None

        cab = ttk.Frame(self, padding=(32, 12, 32, 12))
        cab.pack(fill="x")
        ttk.Button(cab, text="Ver comisiones", style="Pequeno.TButton",
                   command=lambda: app.mostrar(app.comisiones)).pack(side="right")
        divisor(self).pack(fill="x")

        self.desplazable = MarcoDesplazable(self, padding=(32, 24, 32, 30))
        self.desplazable.pack(fill="both", expand=True)
        self.desplazable.configure(style="Fondo.TFrame")
        self.desplazable.canvas.configure(bg=C["suave"])
        cuerpo = self.desplazable.interior
        cuerpo.configure(style="Fondo.TFrame")

        indicadores = ttk.Frame(cuerpo, style="Fondo.TFrame")
        indicadores.pack(fill="x")
        self.cifras = {}
        definicion = (("cobrado_total", "Cobrado en total", C["acento"]),
                      ("cobrado_semana", "Cobrado esta semana", C["texto"]),
                      ("cobrado_mes", "Cobrado este mes", C["texto"]),
                      ("por_cobrar", "Pendiente de cobro", C["peligro"]))
        for columna, (clave, titulo, color) in enumerate(definicion):
            indicadores.columnconfigure(columna, weight=1, uniform="cifras")
            borde, interior = tarjeta(indicadores)
            borde.grid(row=0, column=columna, sticky="nsew",
                       padx=(0 if columna == 0 else 7, 0 if columna == len(definicion) - 1 else 7))
            tk.Frame(interior, bg=C["rojo"] if columna == 0 else C["azul_marca"],
                     width=28, height=3).pack(anchor="w", pady=(0, 15))
            cifra = ttk.Label(interior, text=dinero(0), font=F["titulo"], foreground=color)
            cifra.pack(anchor="w")
            ttk.Label(interior, text=titulo, style="Tenue.TLabel").pack(anchor="w", pady=(5, 0))
            self.cifras[clave] = cifra

        paneles = ttk.Frame(cuerpo, style="Fondo.TFrame")
        paneles.pack(fill="both", expand=True, pady=(16, 0))
        paneles.columnconfigure(0, weight=4, uniform="resumen")
        paneles.columnconfigure(1, weight=7, uniform="resumen")
        paneles.rowconfigure(0, weight=1)

        panel_areas, areas = tarjeta(paneles)
        panel_areas.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        ttk.Label(areas, text="Ingresos por área", style="Detalle.TLabel").pack(anchor="w")
        ttk.Label(areas, text="Comisiones cobradas en total", style="Tenue.TLabel").pack(
            anchor="w", pady=(7, 14))
        self.lista_areas = ttk.Frame(areas)
        self.lista_areas.pack(fill="x")
        self.lista_areas.columnconfigure(0, weight=1)

        panel_historial, historial = tarjeta(paneles)
        panel_historial.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        distribucion = ["columnas"]

        def ajustar_paneles(evento):
            nueva = "filas" if evento.width < 980 else "columnas"
            if nueva == distribucion[0]:
                return
            distribucion[0] = nueva
            if nueva == "filas":
                paneles.columnconfigure(0, weight=1, uniform="")
                paneles.columnconfigure(1, weight=0, uniform="")
                paneles.rowconfigure(0, weight=0)
                paneles.rowconfigure(1, weight=0)
                panel_areas.grid_configure(row=0, column=0, padx=0, pady=(0, 16))
                panel_historial.grid_configure(row=1, column=0, padx=0, pady=0)
            else:
                paneles.columnconfigure(0, weight=4, uniform="resumen")
                paneles.columnconfigure(1, weight=7, uniform="resumen")
                paneles.rowconfigure(0, weight=1)
                paneles.rowconfigure(1, weight=0)
                panel_areas.grid_configure(row=0, column=0, padx=(0, 8), pady=0)
                panel_historial.grid_configure(row=0, column=1, padx=(8, 0), pady=0)

        paneles.bind("<Configure>", ajustar_paneles)
        fila_historial = ttk.Frame(historial)
        fila_historial.pack(fill="x")
        ttk.Label(fila_historial, text="Últimos cobros", style="Detalle.TLabel").pack(side="left")
        ttk.Label(fila_historial, text="Ordenados por fecha de pago",
                  style="Tenue.TLabel").pack(side="right")
        marco, self.lista_pagos = crear_tabla(historial, [
            ("fecha", "Fecha", 120), ("cliente", "Cliente", 190),
            ("area", "Área", 150), ("monto", "Cobrado", 120)], horizontal=True)
        self.lista_pagos.configure(height=10)
        marco.pack(fill="both", expand=True, pady=(15, 0))
        self.sin_pagos = ttk.Label(historial, text="Todavía no hay cobros registrados.",
                                    style="Tenue.TLabel")
        self.desplazable.activar_rueda()

    def contar(self):
        return len(self.db.todos("colocaciones"))

    def refrescar(self):
        resumen = self.app.resumen_financiero()
        if self.resumen is resumen:
            return
        self.resumen = resumen
        for clave, etiqueta in self.cifras.items():
            texto = dinero(self.resumen[clave])
            if etiqueta.cget("text") != texto:
                etiqueta.configure(text=texto)
        self.actualizar_areas()
        if not hasattr(self, "_pagos_estado"):
            self._pagos_estado = {}
        entradas = [(str(pago["id"]), (
            PAD + pago["fecha_pago"], PAD + pago["cliente"], PAD + pago["area"], PAD + dinero(pago["monto"])),
            ("impar" if indice % 2 else "par",)) for indice, pago in enumerate(self.resumen["historial"])]
        Pagina._sincronizar_tabla(self.lista_pagos, self._pagos_estado, entradas, {e[0] for e in entradas})
        if entradas:
            self.sin_pagos.pack_forget()
        elif not self.sin_pagos.winfo_manager():
            self.sin_pagos.pack(anchor="w", pady=(18, 8))

    def actualizar_areas(self):
        importes = sorted(self.resumen["por_area"].items(), key=lambda dato: (-dato[1], dato[0]))
        if getattr(self, "_areas_importes", None) == importes:
            return
        self._areas_importes = importes
        if not hasattr(self, "_areas_celdas"):
            self._areas_celdas = {}
            self._areas_vacias = ttk.Label(self.lista_areas, text="Todavía no hay comisiones cobradas.",
                                          style="Tenue.TLabel")
        existentes = {area for area, _ in importes}
        for area in self._areas_celdas.keys() - existentes:
            self._areas_celdas.pop(area)[0].destroy()
        mayor = max((importe for _, importe in importes), default=0)
        if mayor == 0:
            for celda, _, _ in self._areas_celdas.values():
                celda.grid_remove()
            self._areas_vacias.grid(row=0, column=0, sticky="w", pady=(8, 0))
            return
        self._areas_vacias.grid_remove()
        for indice, (area, importe) in enumerate(importes):
            if area not in self._areas_celdas:
                celda = ttk.Frame(self.lista_areas)
                fila = ttk.Frame(celda)
                fila.pack(fill="x")
                ttk.Label(fila, text=area).pack(side="left")
                cifra = ttk.Label(fila, style="Tenue.TLabel")
                cifra.pack(side="right")
                pista = tk.Frame(celda, bg=C["campo"], height=4)
                pista.pack(fill="x", pady=(0, 7))
                barra = tk.Frame(pista, bg=C["azul_marca"])
                self._areas_celdas[area] = celda, cifra, barra
            celda, cifra, barra = self._areas_celdas[area]
            celda.grid(row=indice, column=0, sticky="ew", pady=(0, 12))
            cifra.configure(text=dinero_corto(importe))
            if importe > 0:
                barra.place(relx=0, rely=0, relwidth=importe / mayor, relheight=1)
            else:
                barra.place_forget()


# ---------------------------------------------------------------- Aplicación
class ItemMenu(tk.Frame):
    """Opción del menú lateral."""

    def __init__(self, master, texto, comando):
        super().__init__(master, bg=C["lateral"], cursor="hand2", takefocus=1,
                         highlightthickness=1, highlightbackground=C["lateral"],
                         highlightcolor=C["acento"])
        self.activo = False
        self.marcador = tk.Frame(self, bg=C["lateral"], width=3)
        self.marcador.pack(side="left", fill="y")
        self.etiqueta = tk.Label(self, text=texto, bg=C["lateral"], fg=C["texto2"],
                                 font=F["base"], anchor="w")
        self.etiqueta.pack(side="left", fill="x", expand=True, padx=(15, 8), pady=11)
        for w in (self, self.marcador, self.etiqueta):
            w.bind("<Button-1>", lambda e: (self.focus_set(), comando()))
            w.bind("<Enter>", lambda e: self._pintar())
            w.bind("<Leave>", lambda e: self.after(10, self._pintar))
        self.bind("<Return>", lambda e: comando())
        self.bind("<space>", lambda e: comando())
        self.bind("<FocusIn>", lambda e: self._pintar())
        self.bind("<FocusOut>", lambda e: self._pintar())

    def activar(self, activo):
        self.activo = activo
        self._pintar()

    def _pintar(self):
        x, y = self.winfo_pointerxy()
        encima = self.winfo_containing(x, y) in (self, self.marcador, self.etiqueta)
        fondo = C["activo"] if self.activo else C["hover"] if encima else C["lateral"]
        for w in (self, self.etiqueta):
            w.configure(bg=fondo)
        self.marcador.configure(bg=C["azul_marca"] if self.activo else fondo)
        self.configure(highlightbackground=C["acento"] if self.focus_get() is self else fondo)
        self.etiqueta.configure(fg=C["texto"] if self.activo or encima else C["texto2"],
                                font=F["negrita"] if self.activo else F["base"])


class BarraLateral(tk.Frame):
    def __init__(self, master):
        factor = escala_pantalla(master)
        super().__init__(master, bg=C["lateral"], width=round(238 * factor))
        self.pack_propagate(False)
        self.items = {}
        self.grupo_actual = None

        # El logo conserva su fondo celeste dentro de un bloque de marca compacto.
        marca = tk.Frame(self, bg=C["activo"], highlightthickness=1,
                         highlightbackground=C["borde"])
        marca.pack(fill="x", padx=16, pady=(20, 22))
        identidad = tk.Frame(marca, bg=C["activo"])
        identidad.pack(fill="x", padx=13, pady=(14, 10))
        try:
            self.logo = tk.PhotoImage(file=LOGO_PATH).subsample(3, 3)
            tk.Label(identidad, image=self.logo, bg=C["logo_fondo"],
                     padx=4, pady=4).pack(side="left")
        except tk.TclError:
            self.logo = None
        tk.Label(identidad, text=AGENCIA_NOMBRE, bg=C["activo"], fg=C["texto"],
                 font=F["marca"], anchor="w", justify="left", wraplength=round(122 * factor)).pack(
                     side="left", padx=(10, 0))
        tk.Frame(marca, bg=C["borde"], height=1).pack(fill="x", padx=13)
        tk.Label(marca, text=AGENCIA_ESLOGAN, bg=C["activo"], fg=C["acento"],
                 font=F["pequena"], anchor="w").pack(fill="x", padx=13, pady=(9, 12))

        self.menu = tk.Frame(self, bg=C["lateral"])
        self.menu.pack(fill="x", padx=11)

    def agregar(self, pagina, texto, comando):
        grupos = {"Clientes": "PERSONAS", "Trabajadoras": "PERSONAS",
                  "Áreas": "ASIGNACIONES", "Comisiones": "FINANZAS",
                  "Ganancias": "FINANZAS", "Garantías": "SEGUIMIENTO"}
        grupo = grupos.get(texto, "NAVEGACIÓN")
        if grupo != self.grupo_actual:
            tk.Label(self.menu, text=grupo, bg=C["lateral"], fg=C["tenue"],
                     font=F["seccion"], anchor="w").pack(fill="x", padx=12,
                                                           pady=(13 if self.grupo_actual else 0, 7))
            self.grupo_actual = grupo
        item = ItemMenu(self.menu, texto, comando)
        item.pack(fill="x", pady=1)
        self.items[pagina] = item

    def activar(self, pagina):
        for p, item in self.items.items():
            item.activar(p is pagina)


def abrir_carpeta(ruta):
    """Abre una carpeta en el explorador del sistema."""
    os.makedirs(ruta, exist_ok=True)
    if ES_WINDOWS:
        os.startfile(ruta)
    else:
        import subprocess
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", ruta])


def ultima_copia_externa(carpeta):
    """Fecha de la copia diaria más reciente de una carpeta externa, o None."""
    if not os.path.isdir(carpeta):
        return None
    fechas = [os.path.getmtime(os.path.join(carpeta, n)) for n in os.listdir(carpeta) if PATRON_EXTERNA.fullmatch(n)]
    return datetime.fromtimestamp(max(fechas)) if fechas else None


class DialogoCopias(tk.Toplevel):
    """Estado de las copias de seguridad, hacer una ahora, elegir una carpeta adicional y restaurar."""

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.title("Copias de seguridad")
        self.configure(bg=C["fondo"])
        self.transient(master.winfo_toplevel())
        centrar(self, 980, 700, master.winfo_toplevel())
        cont = ttk.Frame(self, padding=(32, 26, 32, 22))
        cont.pack(fill="both", expand=True)
        ttk.Label(cont, text="Copias de seguridad", style="Detalle.TLabel").pack(anchor="w")
        ttk.Label(cont, style="Tenue.TLabel", wraplength=900, justify="left", text=(
            "Sus datos se copian solos: al abrir el programa, cada 10 minutos si hubo cambios, al cerrarlo y antes "
            "de borrar algo. Cada copia se verifica. Además se guarda una copia fuera de la carpeta del programa "
            "(en Documentos) con los datos también en archivos que se abren con Excel.")).pack(anchor="w", pady=(4, 14))
        self.estado = ttk.Label(cont, justify="left", wraplength=900)
        self.estado.pack(anchor="w")
        fila = ttk.Frame(cont)
        fila.pack(fill="x", pady=(14, 14))
        ttk.Button(fila, text="Hacer una copia ahora", style="Primario.TButton",
                   command=self.copiar_ahora).pack(side="left")
        ttk.Button(fila, text="Elegir carpeta adicional…", style="Accion.TButton",
                   command=self.elegir_carpeta).pack(side="left", padx=8)
        self.btn_quitar = ttk.Button(fila, text="Quitar la adicional", style="Accion.TButton",
                                     command=self.quitar_carpeta)
        self.btn_quitar.pack(side="left")
        ttk.Button(fila, text="Abrir carpeta de copias", style="Accion.TButton",
                   command=lambda: abrir_carpeta(CARPETA_RESPALDOS)).pack(side="right")
        ttk.Label(cont, text="COPIAS DISPONIBLES", style="Seccion.TLabel").pack(anchor="w", pady=(4, 8))
        marco, self.lista = crear_tabla(cont, [
            ("fecha", "Fecha", 160), ("tipo", "Tipo", 160), ("donde", "Dónde", 110),
            ("clientes", "Clientes", 90), ("trab", "Trabajadoras", 120), ("asig", "Asignaciones", 120)])
        marco.pack(fill="both", expand=True)
        pie = ttk.Frame(cont)
        # Antes que la lista en el orden de empaque: con poco espacio (pantalla chica o escala 125-150 %) se
        # achica la lista y los botones de abajo siguen visibles.
        pie.pack(side="bottom", fill="x", pady=(14, 0), before=marco)
        ttk.Button(pie, text="Traer datos de otro archivo…", style="Accion.TButton",
                   command=self.traer_de_archivo).pack(side="left")
        ttk.Button(pie, text="Cerrar", style="Secundario.TButton", command=self.destroy).pack(side="right")
        self.btn_restaurar = ttk.Button(pie, text="Restaurar la copia elegida", style="Peligro.TButton",
                                        command=self.restaurar, state="disabled")
        self.btn_restaurar.pack(side="right", padx=8)
        self.lista.bind("<<TreeviewSelect>>", lambda e: self.btn_restaurar.state(
            ["!disabled"] if self.lista.selection() else ["disabled"]))
        self.copias = []
        self.refrescar()
        self.grab_set()

    def refrescar(self):
        externas = carpetas_externas()
        self.copias = listar_copias(carpetas_de_copias(externas))
        self.lista.delete(*self.lista.get_children())
        for i, c in enumerate(self.copias):
            self.lista.insert("", "end", iid=str(i), tags=("impar" if i % 2 else "par",), values=[PAD + str(v) for v in (
                f"{c['fecha']:%d/%m/%Y %H:%M}", c["tipo"], c["donde"], c["clientes"], c["trabajadoras"],
                c["colocaciones"])])
        lineas = [f"Última copia: {self.copias[0]['fecha']:%d/%m/%Y a las %H:%M}" if self.copias
                  else "Todavía no hay copias: se harán en cuanto haya datos."]
        for i, carpeta in enumerate(externas):
            ultima = ultima_copia_externa(carpeta)
            marca = f"✓ al {ultima:%d/%m/%Y %H:%M}" if ultima else "✗ todavía sin copia"
            lineas.append(f"{'Copia en Documentos' if i == 0 else 'Carpeta adicional'}: {carpeta}   {marca}")
        if len(externas) == 1:
            lineas.append("Carpeta adicional: ninguna. Se recomienda una (un USB o una carpeta de OneDrive o Google Drive).")
        self.estado.configure(text="\n".join(lineas))
        self.btn_quitar.state(["!disabled"] if len(externas) > 1 else ["disabled"])
        self.btn_restaurar.state(["disabled"])

    def informar(self, resultado):
        if resultado["omitido"]:
            messagebox.showinfo("Copia de seguridad", "Todavía no hay datos que copiar.", parent=self)
        else:
            texto = "Copia hecha y verificada ✓\n\nEn el programa: " + os.path.basename(resultado["archivo"] or "-")
            texto += "".join(f"\nFuera del programa: {c} ✓" for c in resultado["externas"])
            if resultado["errores"]:
                texto += "\n\nProblemas:\n" + "\n".join(resultado["errores"])
            messagebox.showinfo("Copia de seguridad", texto, parent=self)
        self.refrescar()

    def copiar_ahora(self):
        self.informar(self.app.hacer_copia("manual", avisar=False))

    def elegir_carpeta(self):
        from tkinter import filedialog
        ruta = filedialog.askdirectory(parent=self, mustexist=True,
                                       title="Elija la carpeta (por ejemplo un USB o una carpeta de OneDrive)")
        if not ruta:
            return
        guardar_configuracion({**leer_configuracion(), "copia_adicional": ruta})
        self.informar(self.app.hacer_copia("manual", avisar=False))

    def traer_de_archivo(self):
        """Traer los datos de una agencia.db elegida a mano (por ejemplo, la que usaba Iniciar.bat o Agencia.exe
        en otra carpeta o en un USB). Se hace como cualquier restauración: con copia previa y verificada."""
        from tkinter import filedialog
        ruta = filedialog.askopenfilename(parent=self, title="Elija el archivo agencia.db con sus datos",
                                          filetypes=[("Datos de la agencia", "*.db"), ("Todos los archivos", "*.*")])
        if not ruta:
            return
        if misma_ruta(ruta, DB_PATH):
            messagebox.showinfo("Traer datos", "Ese es el archivo que el programa ya está usando.", parent=self)
            return
        datos = contar_datos(ruta)
        if not datos or not any(datos.values()):
            messagebox.showwarning("Traer datos", "Ese archivo no tiene clientes, trabajadoras ni asignaciones "
                                                  "de la agencia.", parent=self)
            return
        copia = {"ruta": ruta, "fecha": datetime.fromtimestamp(os.path.getmtime(ruta)), **datos}
        if self.app.restaurar_copia(copia):
            messagebox.showinfo("Traer datos", "Listo: los datos de ese archivo ya están en el programa.", parent=self)
        self.refrescar()

    def quitar_carpeta(self):
        guardar_configuracion({k: v for k, v in leer_configuracion().items() if k != "copia_adicional"})
        self.refrescar()

    def restaurar(self):
        sel = self.lista.selection()
        if sel and self.app.restaurar_copia(self.copias[int(sel[0])]):
            messagebox.showinfo("Copia restaurada", "Listo: los datos de esa copia ya están en el programa.", parent=self)
            self.refrescar()


class App:
    def __init__(self, root):
        self.root = root
        root.title(AGENCIA_NOMBRE)
        aplicar_tema(root)
        poner_icono(root)
        centrar(root, 1320, 820)  # tamaño al salir de maximizado
        factor = escala_pantalla(root)   # con la escala de Windows al 125 % o 150 % el mínimo crece igual que el texto
        _, _, ancho_util, alto_util = area_de_trabajo(root)     # sin pasar debajo de la barra de tareas al maximizar
        root.minsize(min(round(1100 * factor), ancho_util - 20),
                     min(round(660 * factor), alto_util - _marco_de_ventana(root)))
        maximizar(root)
        # F11: pantalla completa total (sin barra de título). Esc: salir de ella.
        root.bind("<F11>", lambda e: root.attributes(
            "-fullscreen", not root.attributes("-fullscreen")))
        root.bind("<Escape>", lambda e: root.attributes("-fullscreen", False))
        self.db = BaseDatos(DB_PATH)
        root.bind("<Destroy>", self._liberar_recursos, add="+")
        cargar_areas(self.db)
        self._firma_areas = tuple(AREAS.items())      # para saber si cambiaron las áreas y redibujar listas y cuadros
        self._version_copiada = -1        # versión de la base en la última copia (para no copiar si no hubo cambios)
        self._copiando = False            # hay una copia en segundo plano en marcha
        self._errores_avisados = set()    # problemas de copia ya mostrados: se avisa una sola vez
        self._reemplazos = (-1, {})  # (versión de la base, cálculo) para no repetirlo
        self._origen_asignaciones = None
        self._area_asignaciones = None

        self.lateral = BarraLateral(root)
        self.lateral.pack(side="left", fill="y")
        divisor(root, vertical=True).pack(side="left", fill="y")
        contenido = ttk.Frame(root)
        contenido.pack(side="left", fill="both", expand=True)
        contenido.rowconfigure(0, weight=1)
        contenido.columnconfigure(0, weight=1)

        self.clientes = PaginaClientes(contenido, self)
        self.trabajadoras = PaginaTrabajadoras(contenido, self)
        self.areas = PaginaAreas(contenido, self)
        self.contratos = PaginaContratos(contenido, self)
        self.comisiones = PaginaComisiones(contenido, self)
        self.ganancias = PaginaGanancias(contenido, self)
        self.garantias = PaginaGarantias(contenido, self)
        self.enlazar = PaginaEnlazar(contenido, self)  # se abre desde un área
        self.enlazar.grid(row=0, column=0, sticky="nsew")
        self.contratos.grid(row=0, column=0, sticky="nsew")  # vista interna de Áreas
        self.menu = (self.clientes, self.trabajadoras, self.areas,
                     self.comisiones, self.ganancias, self.garantias)
        for pagina in self.menu:
            pagina.grid(row=0, column=0, sticky="nsew")
            self.lateral.agregar(pagina, pagina.titulo_pagina,
                                 lambda p=pagina: self.mostrar(p))
        self.visible = self.clientes
        self.refrescar_todo()
        self.mostrar(self.clientes)
        self.vigilar_cambios()
        atajo = "Command" if sys.platform == "darwin" else "Control"     # las copias se manejan solas; esto es solo para restaurar
        root.bind_all(f"<{atajo}-Shift-Key-B>", lambda e: self.abrir_copias())
        root.bind_all(f"<{atajo}-Shift-Key-b>", lambda e: self.abrir_copias())   # con Bloq Mayús activado
        self.cargar_borradores()
        root.protocol("WM_DELETE_WINDOW", self.cerrar)         # al cerrar: avisar de lo no guardado y hacer una copia
        if sys.platform == "darwin":                            # Cmd+Q también debe pasar por el mismo cuidado
            root.createcommand("::tk::mac::Quit", self.cerrar)
        root.after(1500, lambda: self.hacer_copia_en_segundo_plano("auto"))   # copia al abrir, con la ventana ya visible
        root.after(COPIA_CADA_MS, self.vigilar_copias)

    def hacer_copia(self, motivo="auto", avisar=True):
        """Copia verificada de los datos (en el programa y fuera de él), esperando a que termine."""
        version = self.db.version
        return self._tomar_copia(respaldar(motivo), version, avisar)

    def _tomar_copia(self, resultado, version, avisar):
        if resultado["archivo"] or resultado["externas"]:
            self._version_copiada = version      # la copia tiene al menos lo que había cuando empezó
        self._errores_avisados.intersection_update(resultado["errores"])
        nuevos = [e for e in resultado["errores"] if e not in self._errores_avisados]
        if avisar and nuevos:
            self._errores_avisados.update(nuevos)
            messagebox.showwarning(
                "Copia de seguridad", "No se pudo completar toda la copia de seguridad:\n\n" + "\n".join(nuevos)
                + "\n\nSus datos siguen guardados en el programa.", parent=self.root)
        return resultado

    def hacer_copia_en_segundo_plano(self, motivo="auto"):
        """Copia de seguridad sin detener la ventana: se hace en otro hilo y el resultado se recoge después.
        (Tk solo se toca desde el hilo principal: el hilo de fondo deja el resultado en una cola.)"""
        if self._copiando:
            return
        import queue
        self._copiando = True
        respuestas, version = queue.Queue(), self.db.version

        def trabajo():
            try:
                respuestas.put(respaldar(motivo))
            except BaseException as error:       # nada debe perderse en silencio dentro de un hilo
                respuestas.put(error)
        self._hilo_copia = threading.Thread(target=trabajo, name="copia-de-seguridad", daemon=True)
        self._hilo_copia.start()
        self.root.after(80, lambda: self._recoger_copia(respuestas, version))

    def _recoger_copia(self, respuestas, version):
        import queue
        try:
            resultado = respuestas.get_nowait()
        except queue.Empty:
            self.root.after(80, lambda: self._recoger_copia(respuestas, version))
            return
        self._copiando = False
        if isinstance(resultado, BaseException):
            registrar_error((type(resultado), resultado, resultado.__traceback__))
            resultado = {"archivo": None, "externas": [], "omitido": None,
                         "errores": [str(resultado) or type(resultado).__name__]}
        self._tomar_copia(resultado, version, avisar=True)

    def copia_antes_de_borrar(self):
        """Copia previa a una acción que borra datos. False si no se pudo y la persona prefiere no continuar."""
        resultado = self.hacer_copia("antes-de-borrar", avisar=False)
        if resultado["archivo"] or resultado["omitido"]:
            return True
        return messagebox.askyesno(
            "Copia de seguridad", "No se pudo guardar la copia previa:\n\n" + "\n".join(resultado["errores"])
            + "\n\n¿Desea borrar de todos modos?", default="no", parent=self.root)

    def vigilar_copias(self):
        """Cada 24 horas, si hubo cambios desde la última copia, guarda otra."""
        try:
            if self.db.version != self._version_copiada:
                self.hacer_copia_en_segundo_plano("auto")
        finally:
            self.root.after(COPIA_CADA_MS, self.vigilar_copias)

    def _liberar_recursos(self, evento):
        """Al destruir la ventana principal, libera SQLite y las tareas Tcl/Tk pendientes."""
        if evento.widget is not self.root or getattr(self, "_cerrada", False):
            return
        self._cerrada = True
        try:
            tareas = self.root.tk.call("after", "info")
        except tk.TclError:
            tareas = ()
        for tarea in tareas:
            try:
                # Los hijos ya destruidos eliminaron sus comandos Python: cancelar
                # directamente en Tcl evita borrarlos una segunda vez.
                self.root.tk.call("after", "cancel", tarea)
            except tk.TclError:
                pass
        self.db.con.close()

    def cerrar(self):
        """Antes de cerrar: lo escrito se guarda solo (o queda como borrador) y se deja una copia al día."""
        for pagina in (self.clientes, self.trabajadoras):
            if pagina.resolver_cambios() is False:
                return
        try:
            hilo = getattr(self, "_hilo_copia", None)
            if hilo is not None and hilo.is_alive():
                # Una copia en segundo plano a medias (p. ej. la del arranque): terminarla antes de salir, para no
                # dejar archivos temporales ni una copia externa sin sus datos legibles.
                hilo.join(timeout=120)
            if self.db.version != self._version_copiada:
                self.hacer_copia("auto")
        finally:
            self.root.destroy()

    def abrir_copias(self):
        DialogoCopias(self.root, self)

    def guardar_borradores(self):
        """Un fallo al conservar lo escrito impide abandonar el formulario."""
        ruta = ruta_borradores()
        borradores = {p.tabla: p.borrador for p in (self.clientes, self.trabajadoras) if p.borrador}
        try:
            if borradores:
                with archivo_atomico(ruta) as archivo:
                    json.dump(borradores, archivo, ensure_ascii=False)
            else:
                try:
                    os.remove(ruta)
                except FileNotFoundError:
                    pass
        except OSError as error:
            messagebox.showwarning("Borrador pendiente",
                "No se pudo guardar el borrador. Lo escrito permanece en la pantalla; "
                "mantenga el programa abierto hasta guardarlo.\n\n" + str(error), parent=self.root)
            return False
        return True

    def cargar_borradores(self):
        try:
            with open(ruta_borradores(), encoding="utf-8") as archivo:
                borradores = json.load(archivo)
        except (OSError, ValueError):
            return
        if not isinstance(borradores, dict):
            return
        for pagina in (self.clientes, self.trabajadoras):
            borrador = borradores.get(pagina.tabla)
            if isinstance(borrador, dict):
                pagina.borrador = {k: str(v) for k, v in borrador.items() if k in pagina.form.tipos}
                pagina.nuevo()

    def restaurar_copia(self, copia):
        """Reemplaza los datos por los de una copia, guardando antes lo que hay ahora. True si se restauró."""
        ahora = contar_datos(DB_PATH) or {t: 0 for t in TABLAS}
        if not messagebox.askyesno(
                "Restaurar copia",
                f"¿Restaurar la copia del {copia['fecha']:%d/%m/%Y a las %H:%M}?\n\n"
                f"La copia tiene {copia['clientes']} clientes, {copia['trabajadoras']} trabajadoras y "
                f"{copia['colocaciones']} asignaciones.\nAhora el programa tiene {ahora['clientes']} clientes, "
                f"{ahora['trabajadoras']} trabajadoras y {ahora['colocaciones']} asignaciones.\n\n"
                "Antes se guardará una copia de lo que hay ahora, así podrá volver atrás si se equivoca.",
                parent=self.root):
            return False
        import tempfile
        with carpeta_temporal("agencia-restauracion-") as carpeta:
            fuente_segura = os.path.join(carpeta, "fuente.db")
            copiar_base(copia["ruta"], fuente_segura)
            for pagina in (self.clientes, self.trabajadoras):
                if pagina.resolver_cambios() is False:
                    return False
            previa = self.hacer_copia("antes-de-restaurar", avisar=False)
            if not (previa["archivo"] or previa["omitido"]) and not messagebox.askyesno(
                    "Copia de seguridad", "No se pudo guardar la copia previa:\n\n" + "\n".join(previa["errores"])
                    + "\n\n¿Restaurar de todos modos?", default="no", parent=self.root):
                return False
            self.db.restaurar_desde(fuente_segura)
            for pagina in (self.clientes, self.trabajadoras):
                pagina.nuevo()
        self.refrescar_todo()
        return True

    def ofrecer_recuperacion(self, copia):
        """El programa se abrió sin datos pero hay copias (o los datos de una versión anterior): ofrece traerlos."""
        if hay_datos(DB_PATH):      # mientras tanto se escribió algo (o la base estaba ocupada): no se toca nada
            return
        cantidades = (f"{copia['clientes']} clientes, {copia['trabajadoras']} trabajadoras y "
                      f"{copia['colocaciones']} asignaciones")
        if copia.get("anterior"):
            titulo = "Traer sus datos"
            pregunta = (f"Este programa no tiene datos, pero se encontraron los datos que usaba antes en:\n\n"
                        f"{copia['ruta']}\n\n({cantidades}; último cambio el {copia['fecha']:%d/%m/%Y a las %H:%M}).\n\n"
                        "¿Desea traerlos a esta instalación? El archivo original no se modifica.")
        else:
            titulo = "Recuperar sus datos"
            pregunta = (f"Este programa no tiene datos, pero se encontró una copia de seguridad del "
                        f"{copia['fecha']:%d/%m/%Y a las %H:%M} ({copia['donde'].lower()}) con {cantidades}.\n\n"
                        "¿Desea recuperarla ahora?")
        if messagebox.askyesno(titulo, pregunta, parent=self.root):
            self.hacer_copia("antes-de-restaurar", avisar=False)
            self.db.restaurar_desde(copia["ruta"])
            self.refrescar_todo()
            messagebox.showinfo("Datos recuperados", "Listo: sus datos ya están de vuelta.", parent=self.root)
        elif copia.get("anterior"):
            # No volver a preguntar por el mismo archivo (se puede traer después desde Ctrl+Shift+B).
            try:
                configuracion = leer_configuracion()
                descartados = [d for d in configuracion.get("datos_anteriores_descartados") or [] if isinstance(d, str)]
                guardar_configuracion({**configuracion, "datos_anteriores_descartados": descartados + [copia["ruta"]]})
            except OSError:
                pass

    def vigilar_cambios(self):
        """Cada 3 segundos revisa si otra copia abierta del programa cambió los datos."""
        if getattr(self, "_cerrada", False):
            return
        if self.db.cambio_externo() or getattr(self, "_dia_refresco", None) != date.today():
            self.refrescar_todo()
        self.root.after(3000, self.vigilar_cambios)

    def mostrar(self, pagina):
        anterior = getattr(self, "visible", None)
        if anterior is not pagina and isinstance(anterior, Pagina) and anterior.resolver_cambios() is False:
            return False
        self.visible = pagina
        # las pantallas están apiladas: sin esto el campo de la pantalla anterior seguiría recibiendo el teclado
        # (y sus sugerencias quedarían flotando sobre la nueva)
        self.root.focus_set()
        if self.db.cambio_externo() or getattr(self, "_dia_refresco", None) != date.today():
            self.refrescar_todo()
        self.refrescar_visible()
        pagina.tkraise()
        # El selector y los contratos son vistas internas de «Áreas».
        self.lateral.activar(self.areas if pagina in (self.enlazar, self.contratos) else pagina)

    def registrar(self, tabla, tipo_servicio=None):
        """Abre el formulario de un cliente o trabajadora nuevo, con el área ya marcada."""
        pagina = self.clientes if tabla == "clientes" else self.trabajadoras
        if pagina.resolver_cambios() is False or self.mostrar(pagina) is False:
            return
        pagina.nuevo()
        if tipo_servicio:
            pagina.form.poner_valor("tipo_servicio", tipo_servicio)

    def abrir_area(self, tipo, cliente_id=None):
        self.enlazar.poner_area(tipo, cliente_id)  # ya carga los datos al día
        self.por_refrescar.discard(self.enlazar)
        self.mostrar(self.enlazar)

    def abrir_asignaciones(self, asignacion_id=None):
        """Muestra los contratos dentro de Áreas, con la asignación nueva seleccionada."""
        if self.visible is not self.contratos:
            self._origen_asignaciones = self.visible
            self._area_asignaciones = self.enlazar.filtro_area if self.visible is self.enlazar else None
        asignacion = self.db.uno("colocaciones", asignacion_id) if asignacion_id is not None else None
        filtro = "firmados" if asignacion and asignacion["contrato_firmado"] == "1" else "por_firmar"
        self.contratos.filtro = filtro
        pintar_pestanas(self.contratos.pestanas, filtro)
        self.por_refrescar.add(self.contratos)
        if self.mostrar(self.contratos) is False:
            return
        if asignacion_id is not None and str(asignacion_id) in self.contratos.lista.get_children():
            self.contratos.lista.selection_set(str(asignacion_id))
            self.contratos.lista.see(str(asignacion_id))
            self.contratos.actualizar_info()

    def volver_de_asignaciones(self):
        if self._origen_asignaciones is self.enlazar:
            self.abrir_area(self._area_asignaciones)
        else:
            self.mostrar(self.areas)

    def resumen_financiero(self, fecha_hoy=None):
        """Ganancias y Comisiones comparten el mismo cálculo hasta que cambian sus datos o el día."""
        fecha_hoy = fecha_hoy or date.today()
        clave = (self.db.revision("colocaciones"), self.db.revision("clientes"),
                 fecha_hoy, tuple(AREAS.items()))
        anterior = getattr(self, "_resumen_financiero", None)
        if anterior is None or anterior[0] != clave:
            resumen = resumen_ganancias(self.db.todos("colocaciones"), self.db.todos("clientes"), fecha_hoy)
            self._resumen_financiero = (clave, resumen)
        return self._resumen_financiero[1]

    @contextmanager
    def cambio_de_estados(self):
        """Reserva la escritura antes de leer disponibilidad, sin cambiar ninguna fila."""
        with self.db.lote():
            self.db.con.execute("UPDATE colocaciones SET estado = estado WHERE 0")
            self.db.cambio_externo()
            yield

    def _fila_actual(self, tabla, id_):
        fila = self.db.con.execute(f"SELECT * FROM {tabla} WHERE id = ?", (id_,)).fetchone()
        return self.db._fila(fila) if fila is not None else None

    def _indice_ocupaciones(self):
        """Índices pequeños por persona; las ediciones de un lote se incorporan por ID."""
        revision = self.db.revision("colocaciones")
        indice = getattr(self, "_ocupaciones", None)
        cambios = self.db.cambios_desde("colocaciones", indice["revision"]) if indice else None
        if indice is None or cambios is None or any(tipo == "todo" for tipo, _ in cambios):
            indice = {"revision": revision, "filas": {}, "clientes": {}, "trabajadoras": {}}
            registros = self.db.con.execute("SELECT id, cliente_id, trabajadora_id, estado FROM colocaciones")
            filas = [(str(f[0]), str(f[1] or ""), str(f[2] or ""), f[3]) for f in registros]
        else:
            filas = []
            for id_ in dict.fromkeys(id_ for _, id_ in cambios):
                iid = str(id_)
                anterior = indice["filas"].pop(iid, None)
                if anterior:
                    for tabla, persona in (("clientes", anterior[0]), ("trabajadoras", anterior[1])):
                        grupo = indice[tabla].get(persona, {})
                        grupo.pop(iid, None)
                        if not grupo:
                            indice[tabla].pop(persona, None)
                f = self.db.con.execute("SELECT cliente_id, trabajadora_id, estado FROM colocaciones WHERE id = ?",
                                        (id_,)).fetchone()
                if f is not None:
                    filas.append((iid, str(f[0] or ""), str(f[1] or ""), f[2]))
        for iid, cliente, trabajadora, estado in filas:
            if estado not in ("En proceso", "Activa", "Garantía cumplida"):
                continue
            indice["filas"][iid] = (cliente, trabajadora, estado)
            for tabla, persona in (("clientes", cliente), ("trabajadoras", trabajadora)):
                if persona:
                    indice[tabla].setdefault(persona, {})[iid] = estado
        indice["revision"] = revision
        self._ocupaciones = indice
        return indice

    def _vinculos_ocupantes(self, tabla, id_, excluir=None):
        grupo = self._indice_ocupaciones()[tabla].get(str(id_), {})
        return {iid: estado for iid, estado in grupo.items() if iid != str(excluir)}

    def _reconciliar_persona(self, tabla, id_, liberar=False):
        persona = self._fila_actual(tabla, id_) if id_ else None
        if not persona:
            return
        enlaces = self._vinculos_ocupantes(tabla, id_)
        if any(estado in ("Activa", "Garantía cumplida") for estado in enlaces.values()):
            estado = "Trabajando" if tabla == "trabajadoras" else "Colocado"
        elif enlaces:
            estado = "En proceso" if tabla == "trabajadoras" else "En entrevista"
        elif liberar and persona["estado"] in ("En proceso", "Trabajando", "En entrevista", "Colocado"):
            estado = "Disponible" if tabla == "trabajadoras" else "Buscando"
        else:
            return  # Una cancelación histórica no cambia estados manuales sin otro vínculo.
        if persona["estado"] != estado:
            self.db.actualizar(tabla, persona["id"], {"estado": estado})

    @staticmethod
    def reemplazos_atendidos(enlaces):
        por_id = {str(c["id"]): c for c in enlaces}
        return {str(c["reemplazo_de"]) for c in enlaces
                if str(c.get("reemplazo_de") or "") in por_id and str(c["reemplazo_de"]) != str(c["id"])
                and c.get("cliente_id") and c.get("cliente_id") == por_id[str(c["reemplazo_de"])].get("cliente_id")}

    def crear_asignacion(self, datos, ocupacion="", reemplazo_esperado=None):
        """Comprueba y reserva las dos personas dentro de la misma transacción."""
        with self.cambio_de_estados():
            nuevo = dict(datos)
            cliente = self._fila_actual("clientes", nuevo.get("cliente_id"))
            trabajadora = self._fila_actual("trabajadoras", nuevo.get("trabajadora_id"))
            if (not cliente or cliente["estado"] not in PEDIDOS_POR_ENLAZAR or not trabajadora
                    or trabajadora["estado"] not in ("Disponible", "")
                    or self._vinculos_ocupantes("clientes", cliente["id"])
                    or self._vinculos_ocupantes("trabajadoras", trabajadora["id"])):
                raise ValueError("La disponibilidad cambió. Revise de nuevo el cliente y la trabajadora antes de asignar.")
            anterior = self.reemplazo_pendiente(cliente["id"])
            anterior = self._fila_actual("colocaciones", anterior["id"]) if anterior else None
            if str(nuevo.get("reemplazo_de") or "") != str(anterior["id"] if anterior else ""):
                raise ValueError("El reemplazo pendiente cambió. Abra de nuevo las condiciones de la asignación.")
            if reemplazo_esperado and (not anterior or any(anterior.get(k) != v for k, v in reemplazo_esperado.items())):
                raise ValueError("Las condiciones del reemplazo cambiaron. Revise la asignación antes de guardarla.")
            numero = self.db.insertar("colocaciones", nuevo)
            if ocupacion != (cliente.get("ocupacion") or ""):
                self.db.actualizar("clientes", cliente["id"], {"ocupacion": ocupacion})
            self.sincronizar(dict(nuevo, id=numero))
            return numero

    def eliminar_persona(self, tabla, id_, enlaces_esperados, persona_esperada):
        """Revalida el borrado; la historia retenida queda sin referencias a personas eliminadas."""
        if tabla not in ("clientes", "trabajadoras"):
            raise ValueError("Tipo de registro no válido.")
        clave = "cliente_id" if tabla == "clientes" else "trabajadora_id"
        with self.cambio_de_estados():
            actual = self._fila_actual(tabla, id_)
            if not actual:
                return False
            filas = [self.db._fila(f) for f in self.db.con.execute(
                f"SELECT * FROM colocaciones WHERE {clave} = ? ORDER BY id DESC", (str(id_),))]
            esperados = {str(c["id"]): c for c in enlaces_esperados}
            if (actual != persona_esperada or {str(c["id"]) for c in filas} != set(esperados)
                    or any(any(c.get(k) != v for k, v in esperados[str(c["id"])].items()) for c in filas)):
                raise ValueError("El registro o sus asignaciones cambiaron. Revise de nuevo el borrado.")
            for c in filas:
                self.deshacer_enlace(c)
            retenidos = self.db.con.execute(f"SELECT id FROM colocaciones WHERE {clave} = ?", (str(id_),)).fetchall()
            for fila in retenidos:
                self.db.actualizar("colocaciones", fila["id"], {clave: ""})
            self.db.eliminar(tabla, id_)
            return True

    def iniciar_asignacion(self, c, inicio=None):
        """Inicia solamente el vínculo actual con sus dos personas todavía reservadas."""
        with self.cambio_de_estados():
            actual = self._fila_actual("colocaciones", c["id"])
            if not actual or actual["estado"] != "En proceso":
                return False
            cliente = self._fila_actual("clientes", actual["cliente_id"])
            trabajadora = self._fila_actual("trabajadoras", actual["trabajadora_id"])
            if (actual["cliente_id"] != c.get("cliente_id") or actual["trabajadora_id"] != c.get("trabajadora_id")
                    or not cliente or cliente["estado"] not in ("Pendiente", "Buscando", "En entrevista", "Colocado")
                    or not trabajadora or trabajadora["estado"] not in ("Disponible", "", "En proceso", "Trabajando")
                    or self._vinculos_ocupantes("clientes", actual["cliente_id"], actual["id"])
                    or self._vinculos_ocupantes("trabajadoras", actual["trabajadora_id"], actual["id"])):
                return False
            datos = ({"fecha_inicio": inicio.strftime(FMT_FECHA), "estado": "Activa"}
                     if inicio else inicio_por_firma(actual))
            if not datos:
                return False
            if con_garantia(actual):
                origen = origen_garantia(actual, inicio)
                datos["fin_garantia"] = vencimiento_garantia(origen, actual).strftime(FMT_FECHA)
            self.db.actualizar("colocaciones", actual["id"], datos)
            self.sincronizar(dict(actual, **datos))
            return True

    def solicitar_reemplazo(self, c):
        with self.cambio_de_estados():
            actual = self._fila_actual("colocaciones", c["id"])
            if (not actual or any(actual.get(k) != v for k, v in c.items())
                    or actual["estado"] not in ("En proceso", "Activa") or not con_garantia(actual)):
                raise ValueError("La asignación o su garantía cambió. Revise los datos antes de solicitar reemplazo.")
            self.db.actualizar("colocaciones", actual["id"], {"estado": "Reemplazo solicitado"})
            self.sincronizar(dict(actual, estado="Reemplazo solicitado"))
            return True

    def cumplir_garantia(self, c):
        with self.cambio_de_estados():
            actual = self._fila_actual("colocaciones", c["id"])
            if (not actual or any(actual.get(k) != v for k, v in c.items())
                    or actual["estado"] != "Activa" or not con_garantia(actual)):
                raise ValueError("La asignación o su garantía cambió. Revise los datos antes de darla por cumplida.")
            self.db.actualizar("colocaciones", actual["id"], {"estado": "Garantía cumplida"})
            return True

    def iniciar_contratos_firmados(self):
        """Inicia en lote los contratos actuales; salta históricos o referencias no disponibles."""
        bloqueados = getattr(self, "_inicios_bloqueados", False)
        clave = (self.db.revision("colocaciones"), date.today(),
                 self.db.revision("clientes") if bloqueados else None,
                 self.db.revision("trabajadoras") if bloqueados else None)
        if getattr(self, "_revision_inicios", None) == clave:
            return
        pendientes = [c for c in self.db.todos("colocaciones")
                      if c["estado"] == "En proceso" and c["contrato_firmado"] == "1"]
        bloqueados = False
        if pendientes:
            with self.cambio_de_estados():
                pendientes = [c for c in self.db.todos("colocaciones")
                              if c["estado"] == "En proceso" and c["contrato_firmado"] == "1"]
                for c in pendientes:
                    try:
                        if not self.iniciar_asignacion(c):
                            actual = self._fila_actual("colocaciones", c["id"])
                            bloqueados |= bool(actual and actual["estado"] == "En proceso"
                                               and actual["contrato_firmado"] == "1")
                    except (ValueError, OverflowError):
                        bloqueados = True  # Un dato antiguo inválido no bloquea otros contratos.
        self._inicios_bloqueados = bloqueados
        self._revision_inicios = (self.db.revision("colocaciones"), date.today(),
                                  self.db.revision("clientes") if bloqueados else None,
                                  self.db.revision("trabajadoras") if bloqueados else None)

    def cerrar_garantias_vencidas(self):
        hoy_ = date.today()
        clave = (self.db.revision("colocaciones"), hoy_)
        if getattr(self, "_revision_garantias", None) == clave:
            return
        vencidas = [c for c in self.db.todos("colocaciones") if c["estado"] == "Activa"
                    and con_garantia(c) and (leer_fecha(c["fin_garantia"]) or hoy_) < hoy_]
        if vencidas:
            with self.cambio_de_estados():
                vencidas = [c for c in self.db.todos("colocaciones") if c["estado"] == "Activa"
                            and con_garantia(c) and (leer_fecha(c["fin_garantia"]) or hoy_) < hoy_]
                for c in vencidas:
                    actual = self._fila_actual("colocaciones", c["id"])
                    if (actual and actual["estado"] == "Activa" and con_garantia(actual)
                            and (leer_fecha(actual["fin_garantia"]) or hoy_) < hoy_):
                        self.db.actualizar("colocaciones", actual["id"], {"estado": "Garantía cumplida"})
        self._revision_garantias = (self.db.revision("colocaciones"), hoy_)

    def sincronizar(self, c):
        """Deriva la ocupación desde los vínculos sobrevivientes, incluso al modificar historia."""
        with self.cambio_de_estados():
            actual = self._fila_actual("colocaciones", c["id"]) if c.get("id") else c
            if not actual or actual.get("estado") not in SINCRONIZAR_ESTADOS:
                return
            liberar = actual["estado"] in ("Reemplazo solicitado", "Cancelada")
            self._reconciliar_persona("trabajadoras", actual.get("trabajadora_id"), liberar)
            self._reconciliar_persona("clientes", actual.get("cliente_id"), liberar)

    def reemplazo_pendiente(self, cliente_id):
        """Solicitudes no atendidas por una asignación del mismo cliente."""
        anterior = getattr(self, "_reemplazos", (-1, {}))
        if anterior[0] != self.db.revision("colocaciones"):
            enlaces = self.db.todos("colocaciones")
            atendidos = self.reemplazos_atendidos(enlaces)
            pendientes = {}
            for c in enlaces:
                if c["estado"] == "Reemplazo solicitado" and str(c["id"]) not in atendidos:
                    pendientes.setdefault(c["cliente_id"], c)
            self._reemplazos = (self.db.revision("colocaciones"), pendientes)
        return self._reemplazos[1].get(str(cliente_id))

    def sincronizar_areas(self):
        """Si cambiaron las áreas (una nueva, una eliminada o una copia restaurada), actualiza listas y cuadros."""
        revision = self.db.revision("areas")
        if getattr(self, "_revision_areas", None) == revision:
            return
        cargar_areas(self.db)
        self._revision_areas = revision
        firma = tuple(AREAS.items())
        if firma == self._firma_areas:
            return
        self._firma_areas = firma
        for pagina in (self.clientes, self.trabajadoras):
            pagina.form.widgets["tipo_servicio"]["values"] = list(TIPOS_SERVICIO)
        self.areas.construir()

    def nueva_area(self):
        """Valida el nombre contra las áreas actuales dentro de la misma escritura."""
        nombre = pedir_texto(self.areas, "Nueva área", "Nombre del área (por ejemplo: Jardinería):")
        if nombre is None:
            return
        nombre = " ".join(nombre.split())
        if not nombre or len(nombre) > 40:
            error = "Escriba el nombre del área." if not nombre else "El nombre del área es muy largo (máximo 40 letras)."
            messagebox.showwarning("Nueva área", error, parent=self.areas)
            return False
        error = None
        with self.db.lote():
            self.db.con.execute("UPDATE areas SET nombre=nombre WHERE 0")
            existentes = {sin_acentos(valor) for fila in self.db.con.execute("SELECT nombre,titulo FROM areas")
                          for valor in fila if valor}
            if sin_acentos(nombre) in existentes:
                error = f"Ya existe un área llamada «{nombre}»."
            else:
                self.db.insertar("areas", {"nombre": nombre, "titulo": nombre, "descripcion": ""})
        if error:
            messagebox.showwarning("Nueva área", error, parent=self.areas)
            return False
        self.refrescar_todo()
        return True

    def eliminar_area(self, nombre, parent=None):
        """Comprueba de nuevo los usos después de confirmar y hacer la copia previa."""
        parent = parent or self.areas

        def comprobar():
            filas = self.db.con.execute("SELECT id,nombre,titulo FROM areas").fetchall()
            elegidas = [f for f in filas if f["nombre"] == nombre]
            if not elegidas:
                return "Esta área ya fue eliminada.", []
            clientes = self.db.con.execute("SELECT count(*) FROM clientes WHERE tipo_servicio=?", (nombre,)).fetchone()[0]
            trabajadoras = self.db.con.execute("SELECT count(*) FROM trabajadoras WHERE tipo_servicio=?", (nombre,)).fetchone()[0]
            if clientes or trabajadoras:
                return (f"No se puede eliminar «{elegidas[0]['titulo'] or nombre}» porque hay "
                        f"{plural(clientes, 'cliente', 'clientes')} y "
                        f"{plural(trabajadoras, 'trabajadora', 'trabajadoras')} registrados en esa área. "
                        "Cambie el área de esas personas y vuelva a intentarlo."), []
            if len({f["nombre"] for f in filas if f["nombre"]}) <= 1:
                return "Debe quedar al menos un área.", []
            return None, elegidas

        error, elegidas = comprobar()
        if error:
            messagebox.showwarning("Eliminar área", error, parent=parent)
            return False
        titulo = elegidas[0]["titulo"] or nombre
        if not messagebox.askyesno("Eliminar área", f"¿Eliminar el área «{titulo}»?\n\nAntes se guarda una copia de "
                                   "seguridad.", parent=parent) or not self.copia_antes_de_borrar():
            return False
        with self.db.lote():
            self.db.con.execute("UPDATE areas SET nombre=nombre WHERE 0")
            error, elegidas = comprobar()
            if not error:
                for fila in elegidas:
                    self.db.eliminar("areas", fila["id"])
        if error:
            messagebox.showwarning("Eliminar área", error, parent=parent)
            return False
        self.refrescar_todo()
        return True

    def refrescar_todo(self):
        """Tras un cambio, redibuja la sección visible; las demás al abrirse."""
        self._dia_refresco = date.today()
        self.sincronizar_areas()
        self.iniciar_contratos_firmados()
        self.cerrar_garantias_vencidas()
        self.por_refrescar = set(self.menu) | {self.enlazar, self.contratos}
        self.refrescar_visible()

    def refrescar_visible(self):
        if self.visible in self.por_refrescar:
            self.por_refrescar.discard(self.visible)
            self.visible.refrescar()

    def deshacer_enlace(self, c):
        """Conserva ancestros referenciados y respeta trabajos sobrevivientes al deshacer."""
        with self.cambio_de_estados():
            actual = self._fila_actual("colocaciones", c["id"])
            if actual is None:
                return False
            if any(actual.get(k) != v for k, v in c.items()):
                raise ValueError("La asignación cambió mientras se confirmaba. Revise sus datos antes de deshacerla.")
            hijos = self.db.con.execute("SELECT 1 FROM colocaciones WHERE reemplazo_de = ? LIMIT 1",
                                        (str(actual["id"]),)).fetchone()
            if hijos:
                self.db.actualizar("colocaciones", actual["id"], {"estado": "Cancelada"})
            else:
                self.db.eliminar("colocaciones", actual["id"])
            self._reconciliar_persona("trabajadoras", actual.get("trabajadora_id"), liberar=True)
            self._reconciliar_persona("clientes", actual.get("cliente_id"), liberar=True)
            return True

    def nueva_colocacion(self, cliente_id):
        """Abre la vista Enlazar del área del cliente, con el cliente ya elegido."""
        cliente = self.db.uno("clientes", cliente_id) or {}
        self.abrir_area(cliente.get("tipo_servicio"), cliente_id)


# ---------------------------------------------------------------- Copias de seguridad
# Los datos son lo más valioso del programa: se copian con frecuencia, cada copia se verifica antes de darla
# por buena y hay una copia fuera de la carpeta del programa (en Documentos, más una carpeta opcional).
PATRON_COPIA = re.compile(r"agencia-(auto|antes-de-borrar|antes-de-restaurar|antes-de-actualizar|manual)-(\d{8})(?:-(\d{6})(?:-[0-9a-f]{8})?)?\.db")
PATRON_EXTERNA = re.compile(r"agencia-(\d{8})\.db")
TIPOS_COPIA = {"auto": "Automática", "antes-de-borrar": "Antes de borrar",
               "antes-de-restaurar": "Antes de restaurar", "antes-de-actualizar": "Antes de actualizar",
               "manual": "Manual"}
DIAS_EXTERNAS = 30          # copias diarias que se guardan en cada carpeta externa
COPIA_CADA_MS = 24 * 60 * 60 * 1000   # copia automática cada 24 horas (además de al abrir, al cerrar y antes de borrar)
CONFIG_PATH = os.path.join(CARPETA, "configuracion.json")


def uri_sqlite(ruta):
    """URI «file:» que SQLite acepta para la ruta, también en unidades de red de Windows.

    En Windows no se usa Path.resolve(): convierte una unidad asignada (Z:\\) en \\\\servidor\\recurso y as_uri()
    daría «file://servidor/...», que SQLite rechaza («invalid uri authority»). Las rutas UNC se escriben con la
    autoridad vacía (file:////servidor/recurso/...), la forma que SQLite admite."""
    if sys.platform != "win32":
        return Path(ruta).resolve().as_uri()
    from urllib.parse import quote
    ruta = os.path.abspath(os.fspath(ruta)).replace("\\", "/")
    if ruta.startswith("//?/UNC/"):
        ruta = "//" + ruta[8:]
    elif ruta.startswith("//?/"):
        ruta = ruta[4:]
    if ruta.startswith("//"):
        return "file:////" + quote(ruta[2:], safe="/:")
    return "file:///" + quote(ruta, safe="/:")


def conexion_lectura(ruta, timeout=1):
    """Abre un archivo existente sin crearlo ni permitir escrituras."""
    return sqlite3.connect(uri_sqlite(ruta) + "?mode=ro", uri=True, timeout=timeout)


def reintentar_si_windows_bloquea(funcion, *argumentos, intentos=8, espera=0.1):
    """Ejecuta os.replace/os.remove reintentando si Windows lo impide por un momento.

    En Windows el antivirus, el indexador de búsqueda, OneDrive o una vista previa abren los archivos recién
    escritos durante un instante, y mover o borrar uno en ese momento falla con «acceso denegado» (5) o
    «archivo en uso» (32). En Mac y Linux no ocurre: allí se ejecuta una sola vez."""
    import time
    total = intentos if sys.platform == "win32" else 1
    for intento in range(total):
        try:
            return funcion(*argumentos)
        except PermissionError as error:
            if intento >= total - 1 or getattr(error, "winerror", None) not in (5, 32, 33):
                raise
            time.sleep(espera * (intento + 1))


def base_sana(ruta):
    """False solo si SQLite confirma que el archivo está dañado; una base ocupada por otra copia cuenta como sana."""
    try:
        if not os.path.isfile(ruta):
            return False
        # Un journal pendiente puede impedir quick_check en modo de solo lectura;
        # una cabecera inválida sigue siendo evidencia cierta de corrupción.
        with open(ruta, "rb") as archivo:
            cabecera = archivo.read(16)
        if cabecera and cabecera != b"SQLite format 3\x00":
            return False
        con = conexion_lectura(ruta, timeout=1)   # si otra copia está guardando, no hacer esperar al abrir
        try:
            return con.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        finally:
            con.close()
    except (sqlite3.OperationalError, OSError):
        return True     # bloqueada, sin permiso...: no es corrupción y no se debe tocar
    except sqlite3.DatabaseError:
        return False


def contar_datos(ruta):
    """Cuántos clientes, trabajadoras y asignaciones tiene una base; None si no existe o no se puede leer."""
    if not os.path.exists(ruta):
        return None
    try:
        con = conexion_lectura(ruta, timeout=1)
        try:
            datos = {}
            for tabla in TABLAS:
                try:
                    datos[tabla] = con.execute(f"SELECT count(*) FROM {tabla}").fetchone()[0]
                except sqlite3.OperationalError as error:
                    if "no such table" not in str(error):
                        raise                      # ocupada u otro problema: no se sabe cuánto hay
                    datos[tabla] = 0               # tabla que una versión anterior todavía no tenía
            return datos
        finally:
            con.close()
    except sqlite3.Error:
        return None


def hay_datos(ruta):
    datos = contar_datos(ruta)
    if datos is None:
        return os.path.exists(ruta)  # si la lectura es desconocida, nunca asumir que está vacía
    if any(datos.values()):
        return True
    try:
        con = conexion_lectura(ruta)
        try:
            filas = con.execute("SELECT nombre,titulo,descripcion FROM areas").fetchall()
        finally:
            con.close()
    except sqlite3.OperationalError as error:
        return os.path.exists(ruta) and "no such table" not in str(error)
    except sqlite3.Error:
        return os.path.exists(ruta)
    iniciales = {(nombre, titulo, descripcion) for nombre, (titulo, descripcion) in AREAS_INICIALES.items()}
    return set(filas) != iniciales


CERROJO_COPIAS = threading.Lock()   # una sola copia a la vez: el hilo de fondo y una copia pedida no se pisan

def _copiar_sqlite(fuente, destino, limite=30):
    """La espera por una base ocupada tiene límite; una copia terminada se acepta."""
    import time
    plazo = time.monotonic() + limite

    def progreso(estado, restantes, total):
        if estado != sqlite3.SQLITE_DONE and time.monotonic() >= plazo:
            raise sqlite3.OperationalError("La copia excedió el tiempo de espera; no se publicó.")

    fuente.backup(destino, pages=512, sleep=0.01, progress=progreso)


@contextmanager
def carpeta_temporal(prefix, dir=None):
    """Carpeta temporal que se borra al terminar sin fallar si Windows retiene un archivo un instante (antivirus).
    Equivale a TemporaryDirectory(ignore_cleanup_errors=True), que no existe antes de Python 3.10."""
    import shutil
    import tempfile
    ruta = tempfile.mkdtemp(prefix=prefix, dir=dir)
    try:
        yield ruta
    finally:
        shutil.rmtree(ruta, ignore_errors=True)


@contextmanager
def archivo_atomico(ruta, encoding="utf-8", newline=None):
    """Un temporal exclusivo evita truncar archivos buenos y pisar otras escrituras."""
    import tempfile
    ruta = Path(ruta)
    descriptor, temporal = tempfile.mkstemp(prefix=ruta.name + ".", suffix=".tmp", dir=ruta.parent)
    try:
        with os.fdopen(descriptor, "w", encoding=encoding, newline=newline) as archivo:
            descriptor = None
            yield archivo
            archivo.flush()
            os.fsync(archivo.fileno())
        reintentar_si_windows_bloquea(os.replace, temporal, ruta)
        temporal = None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporal is not None:
            try:
                os.remove(temporal)
            except FileNotFoundError:
                pass


@contextmanager
def cerrojo_carpeta(carpeta, limite=30):
    """Serializa publicación y retención entre procesos de Mac y Windows."""
    import time
    archivo = open(os.path.join(carpeta, ".copias.lock"), "a+b")
    tomado = False
    try:
        if os.fstat(archivo.fileno()).st_size == 0:
            archivo.write(b"0")
            archivo.flush()
        plazo = time.monotonic() + limite
        while True:
            try:
                archivo.seek(0)
                if sys.platform == "win32":
                    import msvcrt
                    msvcrt.locking(archivo.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(archivo.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                tomado = True
                break
            except (BlockingIOError, PermissionError):
                if time.monotonic() >= plazo:
                    raise TimeoutError("Otra instancia está haciendo una copia; inténtelo de nuevo.")
                time.sleep(0.05)
        yield
    finally:
        try:
            if tomado:
                archivo.seek(0)
                if sys.platform == "win32":
                    import msvcrt
                    msvcrt.locking(archivo.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(archivo.fileno(), fcntl.LOCK_UN)
        finally:
            archivo.close()


def misma_ruta(origen, destino):
    try:
        return os.path.samefile(origen, destino)
    except (FileNotFoundError, OSError):
        return Path(origen).resolve() == Path(destino).resolve()



def copiar_base(origen, destino):
    """SQLite copia a un temporal único; verificarlo nunca crea otro archivo."""
    if misma_ruta(origen, destino):
        raise ValueError("La copia debe guardarse en una ruta distinta de la base original.")
    import tempfile
    fuente = conexion_lectura(origen, timeout=10)
    temporal = None
    try:
        tablas = {r[0] for r in fuente.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not tablas.intersection(TABLAS):
            raise sqlite3.DatabaseError("La fuente no contiene datos de una agencia.")
        descriptor, temporal = tempfile.mkstemp(prefix=Path(destino).name + ".", suffix=".tmp", dir=Path(destino).parent)
        os.close(descriptor)
        copia = sqlite3.connect(temporal)
        try:
            _copiar_sqlite(fuente, copia)
            # Un respaldo debe poder abrirse por sí solo, sin archivos WAL/SHM laterales.
            if copia.execute("PRAGMA journal_mode=DELETE").fetchone()[0].lower() != "delete":
                raise sqlite3.DatabaseError("No se pudo preparar una copia independiente de la base.")
        finally:
            copia.close()
        verificacion = conexion_lectura(temporal)
        try:
            if verificacion.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise sqlite3.DatabaseError("La copia no pasó la verificación de integridad.")
            copiadas = {r[0] for r in verificacion.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not tablas.issubset(copiadas):
                raise sqlite3.DatabaseError("La copia no conserva las tablas de la fuente.")
        finally:
            verificacion.close()
        # Se conserva la comprobación usada por el diagnóstico y las pruebas de errores.
        if not base_sana(temporal) or contar_datos(temporal) is None:
            raise sqlite3.DatabaseError("La copia no pasó la verificación.")
        reintentar_si_windows_bloquea(os.replace, temporal, destino)
        temporal = None
    finally:
        fuente.close()
        if temporal and os.path.exists(temporal):
            os.remove(temporal)


def restaurar_archivo(origen, destino):
    """Valida la copia antes de abrir el destino para escritura."""
    if misma_ruta(origen, destino):
        raise ValueError("La copia y el destino no pueden ser el mismo archivo.")
    if not os.path.exists(destino):
        copiar_base(origen, destino)  # publicar sólo una base completamente verificada
        return
    fuente = conexion_lectura(origen, timeout=10)
    try:
        tablas = {r[0] for r in fuente.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not tablas.intersection(TABLAS) or fuente.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise sqlite3.DatabaseError("La copia no contiene una base de la agencia válida.")
        base = sqlite3.connect(destino, timeout=10)
        try:
            _copiar_sqlite(fuente, base)
        finally:
            base.close()
    finally:
        fuente.close()


def carpeta_documentos():
    if sys.platform == "win32":
        try:
            import ctypes
            ruta = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, ruta) == 0 and ruta.value:  # 5 = Documentos
                return ruta.value
        except Exception:
            pass
    return os.path.join(os.path.expanduser("~"), "Documents")


def leer_configuracion(ruta=None):
    try:
        with open(ruta or CONFIG_PATH, encoding="utf-8") as archivo:
            datos = json.load(archivo)
        return datos if isinstance(datos, dict) else {}
    except (OSError, ValueError):
        return {}


def ruta_borradores():
    """Junto a la base de datos (así siempre está en la carpeta de datos que se esté usando)."""
    return os.path.join(os.path.dirname(DB_PATH), "borradores.json")


def guardar_configuracion(datos, ruta=None):
    ruta = ruta or CONFIG_PATH
    with archivo_atomico(ruta) as archivo:
        json.dump(datos, archivo, ensure_ascii=False, indent=2)


def carpetas_externas(configuracion=None):
    """Carpetas fuera del programa donde se guarda una copia: Documentos y, si se eligió, otra (USB, nube...)."""
    configuracion = leer_configuracion() if configuracion is None else configuracion
    carpetas = [os.path.join(carpeta_documentos(), f"Respaldos {AGENCIA_NOMBRE}")]
    adicional = configuracion.get("copia_adicional") if isinstance(configuracion, dict) else None
    if isinstance(adicional, str) and adicional.strip() and adicional not in carpetas:
        carpetas.append(adicional)
    return carpetas


def celda_csv(valor):
    if isinstance(valor, str) and (valor.startswith(("\t", "\r", "\n"))
            or valor.lstrip(" \t\r\n").startswith(("=", "+", "-", "@"))):
        return "'" + valor
    return valor


def _revertir_csvs(carpeta, resguardo, anteriores, nombres):
    """Restaura todos los nombres sin consumir las copias previas, incluso si alguno falla."""
    import shutil
    errores = []
    restauracion = os.path.join(os.path.dirname(resguardo), "restauracion")
    os.makedirs(restauracion, exist_ok=True)
    for nombre in nombres:
        destino = os.path.join(carpeta, nombre)
        try:
            if nombre in anteriores:
                preparado = os.path.join(restauracion, nombre)
                shutil.copy2(os.path.join(resguardo, nombre), preparado, follow_symlinks=False)
                os.replace(preparado, destino)
            elif os.path.lexists(destino):
                os.unlink(destino)
        except BaseException as error:
            errores.append(f"{nombre}: {error}")
    return errores


class CSVOcupados(OSError):
    """Algún CSV de «Datos legibles» está abierto en otro programa y Windows no deja reemplazarlo."""

    def __init__(self, nombres):
        self.nombres = list(nombres)
        super().__init__(
            f"No se actualizó{'' if len(self.nombres) == 1 else 'n'} {', '.join(self.nombres)} en «Datos legibles» "
            "porque está abierto en otro programa (por ejemplo Excel). Ciérrelo y se actualizará en la próxima "
            "copia. La copia de seguridad de los datos sí se guardó.")


def _publicar_csvs(preparados, carpeta, resguardo, nombres):
    """Guarda los anteriores antes del primer reemplazo y revierte una publicación fallida.

    En Windows, Excel no deja reemplazar un CSV que tiene abierto: ese archivo se conserva como estaba, los
    demás se actualizan y al final se avisa con CSVOcupados (un mensaje que no cambia de una copia a otra)."""
    import shutil
    anteriores = []
    for nombre in nombres:
        destino = os.path.join(carpeta, nombre)
        if os.path.lexists(destino):
            shutil.copy2(destino, os.path.join(resguardo, nombre), follow_symlinks=False)
            anteriores.append(nombre)
    with open(os.path.join(resguardo, "restauracion.json"), "w", encoding="utf-8") as archivo:
        json.dump({"destino": carpeta, "anteriores": anteriores,
                   "ausentes": [n for n in nombres if n not in anteriores]}, archivo, ensure_ascii=False, indent=2)
        archivo.flush()
        os.fsync(archivo.fileno())
    publicados, ocupados, actual = [], [], None
    try:
        for nombre in nombres:
            actual = nombre      # si falla a medias, este también se revierte
            try:
                # Excel retiene el archivo mientras esté abierto: basta un intento breve antes de dejarlo como estaba.
                reintentar_si_windows_bloquea(os.replace, os.path.join(preparados, nombre), os.path.join(carpeta, nombre),
                                              intentos=3)
            except PermissionError:
                if sys.platform != "win32":
                    raise
                ocupados.append(nombre)   # Windows no lo reemplazó: sigue el anterior, intacto
            else:
                publicados.append(nombre)
            actual = None
    except BaseException as error:
        try:
            errores = _revertir_csvs(carpeta, resguardo, anteriores, publicados + ([actual] if actual else []))
        except BaseException as fallo:
            errores = [str(fallo)]
        if errores:
            # El llamador conserva este directorio; las copias anteriores siguen completas.
            fallo = OSError("La publicación de CSV y su recuperación fallaron. "
                            f"Se conservan los archivos anteriores en: {resguardo}. "
                            "Errores de recuperación: " + "; ".join(errores))
            fallo._resguardo_csv = resguardo
            raise fallo from error
        raise
    if ocupados:
        raise CSVOcupados(ocupados)


class _SinDocumento:
    """Recorre las asignaciones cambiando el documento HTML del contrato por «Sí» (o vacío si no hay)."""

    def __init__(self, cursor, posicion):
        self.description, self._cursor, self._posicion = cursor.description, cursor, posicion

    def __iter__(self):
        for fila in self._cursor:
            fila = list(fila)
            fila[self._posicion] = "Sí" if fila[self._posicion] else ""
            yield fila


def exportar_legible(ruta, carpeta):
    """Prepara una instantánea completa de CSV y conserva la exportación anterior si falla."""
    import csv
    import shutil
    import tempfile
    carpeta = os.path.abspath(os.fspath(carpeta))
    os.makedirs(carpeta, exist_ok=True)
    temporal = tempfile.mkdtemp(prefix=".exportacion-csv-", dir=carpeta)
    preparados, resguardo = os.path.join(temporal, "nuevos"), os.path.join(temporal, "anteriores")
    conservar = False
    try:
        os.mkdir(preparados)
        os.mkdir(resguardo)
        nombres = []
        con = conexion_lectura(ruta, timeout=10)
        try:
            con.execute("BEGIN")  # las cuatro tablas corresponden a la misma instantánea de solo lectura
            tablas = {f[0] for f in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")}
            for tabla, nombre in (("clientes", "Clientes"), ("trabajadoras", "Trabajadoras"),
                                  ("colocaciones", "Asignaciones"), ("areas", "Areas")):
                cursor = con.execute(f"SELECT * FROM {tabla} ORDER BY id") if tabla in tablas else None
                if cursor is not None and tabla == "colocaciones":
                    # contrato_html guarda el documento firmado completo (decenas de miles de caracteres): no cabe en
                    # una celda de Excel. Queda en la copia .db; en el CSV solo se indica si existe.
                    columnas = [columna[0] for columna in cursor.description]
                    if "contrato_html" in columnas:
                        cursor = _SinDocumento(cursor, columnas.index("contrato_html"))
                cabeceras = ([columna[0] for columna in cursor.description] if cursor is not None else
                             ["id", "nombre", "titulo", "descripcion"] if tabla == "areas" else ["id"] + claves(TABLAS[tabla]))
                nombre += ".csv"
                nombres.append(nombre)
                with open(os.path.join(preparados, nombre), "w", encoding="utf-8-sig", newline="") as archivo:
                    escritor = csv.writer(archivo)
                    escritor.writerow(cabeceras)
                    if cursor is not None:
                        escritor.writerows([celda_csv(valor) for valor in fila] for fila in cursor)
                    archivo.flush()
                    os.fsync(archivo.fileno())
        finally:
            con.close()
        try:
            _publicar_csvs(preparados, carpeta, resguardo, nombres)
        except BaseException as error:
            conservar = getattr(error, "_resguardo_csv", None) == resguardo
            raise
    finally:
        if not conservar:
            shutil.rmtree(temporal, ignore_errors=True)


def copia_externa(ruta, carpeta, ahora=None):
    """Una copia por día (se renueva durante el día) más los datos legibles, en una carpeta fuera del programa.
    Devuelve un aviso si algún CSV no pudo actualizarse porque estaba abierto; None si todo quedó al día."""
    ahora = ahora or datetime.now()
    os.makedirs(carpeta, exist_ok=True)
    with cerrojo_carpeta(carpeta):
        destino = os.path.join(carpeta, f"agencia-{ahora:%Y%m%d}.db")
        copiar_base(ruta, destino)
        diarias = sorted(n for n in os.listdir(carpeta) if PATRON_EXTERNA.fullmatch(n))
        for vieja in diarias[:-DIAS_EXTERNAS]:
            try:
                reintentar_si_windows_bloquea(os.remove, os.path.join(carpeta, vieja))
            except OSError:
                pass   # abierta en otro programa o sincronizándose: se borrará en la próxima copia
        leame = os.path.join(carpeta, "LEEME.txt")
        if not os.path.exists(leame):
            with archivo_atomico(leame) as archivo:
                archivo.write(f"Copias de seguridad de {AGENCIA_NOMBRE}\n\n"
                              "agencia-AAAAMMDD.db   copia de todos los datos de ese día.\n"
                              "Datos legibles        los mismos datos en archivos .csv (se abren con Excel).\n\n"
                              "Los textos que podrían interpretarse como fórmulas llevan un apóstrofo protector.\n"
                              "Para recuperar: abra el programa y pulse Cmd+Shift+B (Mac) o Ctrl+Shift+B (Windows) > Restaurar una copia.\n"
                              "No borre esta carpeta: es su respaldo si algo le pasa a la computadora.\n")
        try:
            exportar_legible(destino, os.path.join(carpeta, "Datos legibles"))
        except CSVOcupados as aviso:
            return str(aviso)     # la copia .db está hecha; solo quedó algún CSV sin actualizar
    return None


def nombre_copia(motivo, ahora):
    return f"agencia-{motivo}-{ahora:%Y%m%d-%H%M%S}.db"


def _fecha_de_copia(nombre):
    m = PATRON_COPIA.fullmatch(nombre)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(2) + (m.group(3) or "000000"), "%Y%m%d%H%M%S")
    except ValueError:
        return None


def podar_respaldos(carpeta, ahora=None):
    """Retención: automáticas todas las de las últimas 3 horas, una por hora hasta 2 días y una por día hasta 60
    días; «antes de borrar» las últimas 30 y «antes de restaurar» las últimas 10. Nunca toca lo que no crea el
    programa (copias manuales de la persona, «danadas»...)."""
    ahora = ahora or datetime.now()
    grupos, automaticas = {"antes-de-borrar": [], "antes-de-restaurar": [], "antes-de-actualizar": []}, []
    for nombre in os.listdir(carpeta):
        m, fecha = PATRON_COPIA.fullmatch(nombre), _fecha_de_copia(nombre)
        if not m or fecha is None or m.group(1) == "manual":
            continue
        (automaticas if m.group(1) == "auto" else grupos[m.group(1)]).append((fecha, nombre))
    borrar, por_franja = [], {}
    for fecha, nombre in automaticas:
        edad = ahora - fecha
        if edad <= timedelta(hours=3):
            continue
        if edad > timedelta(days=60):
            borrar.append(nombre)
        else:
            franja = fecha.strftime("%Y%m%d%H") if edad <= timedelta(days=2) else fecha.strftime("%Y%m%d")
            por_franja.setdefault(franja, []).append((fecha, nombre))
    for franja, lista in por_franja.items():
        borrar += [nombre for _, nombre in sorted(lista)[:-1]]     # queda la más reciente de cada franja
    for tipo, limite in (("antes-de-borrar", 30), ("antes-de-restaurar", 10), ("antes-de-actualizar", 10)):
        borrar += [nombre for _, nombre in sorted(grupos[tipo])[:-limite]]
    for nombre in borrar:
        try:
            reintentar_si_windows_bloquea(os.remove, os.path.join(carpeta, nombre))
        except OSError:
            pass   # abierta en otro programa (p. ej. la lista de copias): se borrará en la próxima copia


def respaldar(motivo="auto", ruta=None, carpeta=None, externas=None, ahora=None):
    """Hace una copia verificada en la carpeta de respaldos y otra en cada carpeta externa.
    Devuelve {"archivo", "externas", "errores", "omitido"}; un fallo de una copia no impide las demás."""
    ruta = DB_PATH if ruta is None else ruta
    carpeta = CARPETA_RESPALDOS if carpeta is None else carpeta
    ahora = ahora or datetime.now()
    resultado = {"archivo": None, "externas": [], "errores": [], "omitido": None}
    with CERROJO_COPIAS:
        if contar_datos(ruta) is None:
            resultado["errores"].append("No se puede leer la base para hacer la copia; no se asumió que estuviera vacía.")
            return resultado
        if not hay_datos(ruta):
            resultado["omitido"] = "no hay datos que copiar"    # una base vacía no debe desplazar copias buenas
            return resultado
        try:
            os.makedirs(carpeta, exist_ok=True)
            with cerrojo_carpeta(carpeta):
                destino = os.path.join(carpeta, nombre_copia(motivo, ahora))
                if os.path.exists(destino):
                    import uuid
                    destino = str(Path(destino).with_suffix("")) + "-" + uuid.uuid4().hex[:8] + ".db"
                copiar_base(ruta, destino)
                resultado["archivo"] = destino
                podar_respaldos(carpeta, ahora)
        except (OSError, sqlite3.Error) as error:
            resultado["errores"].append(f"Copia en la carpeta del programa: {error}")
        for externa in (carpetas_externas() if externas is None else externas):
            try:
                aviso = copia_externa(ruta, externa, ahora)
                resultado["externas"].append(externa)
                if aviso:
                    resultado["errores"].append(f"Copia en «{externa}»: {aviso}")
            except (OSError, sqlite3.Error) as error:
                resultado["errores"].append(f"Copia en «{externa}»: {error}")
    return resultado


def carpetas_de_copias(externas=None):
    """(carpeta, etiqueta) donde buscar copias: la del programa y las externas."""
    return ([(CARPETA_RESPALDOS, "Programa")]
            + [(c, "Documentos" if i == 0 else "Adicional")
               for i, c in enumerate(carpetas_externas() if externas is None else externas)])


_RECUENTOS_COPIAS = {}
_CERROJO_RECUENTOS = threading.Lock()


def _firma_archivo(ruta, estado):
    return (os.path.realpath(ruta), estado.st_dev, estado.st_ino, estado.st_size,
            estado.st_mtime_ns, estado.st_ctime_ns)


def _datos_de_copia(ruta, estado):
    """Reutiliza recuentos de archivos intactos; nunca guarda errores de lectura ni bases con un journal."""
    clave = _firma_archivo(ruta, estado)
    def sin_journal():
        return not any(os.path.exists(ruta + sufijo) for sufijo in ("-wal", "-shm", "-journal"))
    estable = sin_journal()
    if estable:
        with _CERROJO_RECUENTOS:
            anterior = _RECUENTOS_COPIAS.pop(clave, None)
            if anterior is not None:
                _RECUENTOS_COPIAS[clave] = anterior
                return dict(anterior)
    datos = contar_datos(ruta)
    if datos is not None and estable and sin_journal():
        try:
            if _firma_archivo(ruta, os.stat(ruta)) == clave:
                with _CERROJO_RECUENTOS:
                    _RECUENTOS_COPIAS[clave] = dict(datos)
                    while len(_RECUENTOS_COPIAS) > 256:
                        del _RECUENTOS_COPIAS[next(iter(_RECUENTOS_COPIAS))]
        except OSError:
            return None
    return datos


def _iterar_copias(carpetas):
    """Ordena metadatos antes de abrir SQLite: la recuperación puede detenerse en la primera copia útil."""
    archivos = []
    for carpeta, donde in carpetas:
        try:
            with os.scandir(carpeta) as entradas:
                for entrada in entradas:
                    nombre = entrada.name
                    if not nombre.endswith(".db") or "danada" in nombre:
                        continue
                    try:
                        if entrada.is_file():
                            # En Windows, DirEntry.stat() deja st_ino y st_dev en cero: la firma no coincidiría
                            # con la de os.stat() y los recuentos nunca se reutilizarían.
                            estado = os.stat(entrada.path) if ES_WINDOWS else entrada.stat()
                            archivos.append((estado, entrada.path, nombre, donde))
                    except OSError:
                        continue
        except OSError:
            continue
    archivos.sort(key=lambda archivo: archivo[0].st_mtime_ns, reverse=True)
    for estado, ruta, nombre, donde in archivos:
        datos = _datos_de_copia(ruta, estado)
        if datos is None:
            continue
        m = PATRON_COPIA.fullmatch(nombre)
        tipo = TIPOS_COPIA[m.group(1)] if m else "Diaria" if PATRON_EXTERNA.fullmatch(nombre) else "Otra"
        yield {"ruta": ruta, "nombre": nombre, "tipo": tipo, "donde": donde,
               "fecha": datetime.fromtimestamp(estado.st_mtime), **datos}


def listar_copias(carpetas):
    """Copias legibles, la más nueva primero; cuenta de nuevo solo los archivos que cambiaron."""
    return list(_iterar_copias(carpetas))


def buscar_restauracion(ruta=None, carpetas=None):
    """Ofrece la primera copia con datos, sin abrir todas las copias posteriores."""
    ruta = DB_PATH if ruta is None else ruta
    if hay_datos(ruta):
        return None
    carpetas = carpetas_de_copias() if carpetas is None else carpetas
    return next((c for c in _iterar_copias(carpetas) if any(c[t] for t in TABLAS) or hay_datos(c["ruta"])), None)


# Carpetas que nunca contienen los datos de una versión anterior: se saltan al buscarlos.
_CARPETAS_SIN_DATOS = {"appdata", "application data", "library", "node_modules", "__pycache__", "$recycle.bin",
                       "windows", "program files", "program files (x86)", "programdata", "system volume information",
                       "respaldos", "contratos", "datos legibles"}


def lugares_datos_anteriores(casa=None):
    """(carpeta, profundidad) donde una versión anterior pudo dejar agencia.db junto al programa (Iniciar.bat o
    Agencia.exe guardaban los datos en su propia carpeta): Escritorio, Documentos, Descargas, OneDrive y la
    carpeta personal; en Windows también las carpetas de primer nivel del disco del sistema (C:\\Agencia...)."""
    casa = os.path.expanduser("~") if casa is None else casa
    lugares = [(casa, 1)] + [(os.path.join(casa, nombre), 4) for nombre in (
        "Desktop", "Escritorio", "Documents", "Documentos", "Downloads", "Descargas", "OneDrive")]
    if ES_WINDOWS and casa == os.path.expanduser("~"):
        lugares += [(carpeta_documentos(), 4), (os.path.join(os.environ.get("SystemDrive", "C:"), os.sep), 2)]
    vistos, unicos = set(), []
    for carpeta, profundidad in lugares:
        clave = os.path.normcase(os.path.abspath(carpeta))
        if clave not in vistos and os.path.isdir(carpeta):
            vistos.add(clave)
            unicos.append((carpeta, profundidad))
    return unicos


def buscar_datos_anteriores(lugares=None, excluir=(), limite=2.0):
    """La agencia.db con datos más reciente que dejó una versión anterior junto al programa, lista para ofrecerla
    como una copia (con «anterior»: True); None si no hay. Solo lee, y con límite de tiempo para no demorar la
    apertura del programa."""
    import time
    fin = time.monotonic() + limite
    lugares = lugares_datos_anteriores() if lugares is None else lugares
    excluir = {os.path.normcase(os.path.abspath(ruta)) for ruta in excluir}
    candidatas = {}
    for raiz, profundidad in lugares:
        pendientes = [(raiz, 0)]
        while pendientes and time.monotonic() < fin:
            carpeta, nivel = pendientes.pop()
            try:
                with os.scandir(carpeta) as entradas:
                    for entrada in entradas:
                        try:
                            if entrada.is_dir(follow_symlinks=False):
                                if (nivel < profundidad and not entrada.name.startswith((".", "$"))
                                        and entrada.name.lower() not in _CARPETAS_SIN_DATOS):
                                    pendientes.append((entrada.path, nivel + 1))
                            elif entrada.name.lower() == "agencia.db":
                                clave = os.path.normcase(os.path.abspath(entrada.path))
                                if clave not in excluir:
                                    candidatas[clave] = entrada.path
                        except OSError:
                            continue
            except OSError:
                continue
    mejor = None
    for ruta in candidatas.values():
        datos = contar_datos(ruta)
        if not datos or not any(datos.get(tabla) for tabla in TABLAS):
            continue
        try:
            fecha = datetime.fromtimestamp(os.path.getmtime(ruta))
        except OSError:
            continue
        if mejor is None or fecha > mejor["fecha"]:
            mejor = {"ruta": ruta, "nombre": os.path.basename(ruta), "tipo": "Versión anterior",
                     "donde": "Versión anterior", "fecha": fecha, "anterior": True, **datos}
    return mejor


def debe_buscar_datos_anteriores():
    """Solo en Windows, con el programa instalado (o el .exe) y todavía sin datos: es la situación de quien usaba
    Iniciar.bat o Agencia.exe con los datos junto al programa y acaba de pasar al instalador."""
    return ES_WINDOWS and (getattr(sys, "frozen", False) or instalado_con_runtime()) and not hay_datos(DB_PATH)


def restaurar_si_esta_danada(ruta=None, carpeta=None):
    """Prepara y migra la recuperación antes de apartar una base dañada."""
    import tempfile
    import uuid
    ruta = DB_PATH if ruta is None else os.fspath(ruta)
    if not os.path.exists(ruta) or base_sana(ruta):
        return None
    if carpeta is None:
        carpetas = carpetas_de_copias()
    else:
        carpetas = [(c, "Programa") for c in ([carpeta] if isinstance(carpeta, str) else carpeta)]
    sano = next((c for c in _iterar_copias(carpetas)
        if (any(c[t] for t in TABLAS) or hay_datos(c["ruta"])) and base_sana(c["ruta"])), None)
    if sano is None:
        raise sqlite3.DatabaseError("La base de datos está dañada y no hay ningún respaldo sano en las "
                                    "carpetas de respaldo. No se modificó nada.")
    destino = CARPETA_RESPALDOS if carpeta is None else carpetas[0][0]
    os.makedirs(destino, exist_ok=True)
    apartada = os.path.join(destino, f"agencia-danada-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}.db")
    with carpeta_temporal("agencia-recuperacion-", dir=Path(ruta).parent) as temporal:
        preparada = os.path.join(temporal, "verificada.db")
        copiar_base(sano["ruta"], preparada)
        migrada = BaseDatos(preparada)
        migrada.con.close()
        movidos = []
        try:
            for sufijo in ("", "-journal", "-wal", "-shm"):
                if os.path.exists(ruta + sufijo):
                    os.replace(ruta + sufijo, apartada + sufijo)
                    movidos.append(sufijo)
            restaurar_archivo(preparada, ruta)
        except BaseException:
            # No dejar un archivo vacío que el siguiente arranque interprete como nuevo.
            for sufijo in movidos:
                os.replace(apartada + sufijo, ruta + sufijo)
            raise
    return (f"La base de datos estaba dañada, así que se restauró la copia del {sano['fecha']:%d/%m/%Y %H:%M} "
            f"(«{sano['nombre']}»).\n\nPuede faltar lo registrado después de esa copia. La base dañada se "
            f"guardó como {os.path.basename(apartada)}.")


def esquema_desactualizado(ruta):
    """True si la base es de una versión anterior y el programa va a cambiar su estructura al abrirla."""
    if not os.path.exists(ruta):
        return False
    try:
        con = conexion_lectura(ruta, timeout=1)
        try:
            for tabla, campos in TABLAS.items():
                existentes = {fila[1] for fila in con.execute(f"PRAGMA table_info({tabla})")}
                if not existentes or set(claves(campos)) - existentes:
                    return True
            return not con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'areas'").fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return False


def preparar_base():
    """Antes de abrir la ventana: revisa la base y, si hace falta, la restaura.
    Devuelve (aviso, oferta): un aviso si se restauró algo, y la copia que conviene ofrecer si el programa está vacío."""
    aviso = restaurar_si_esta_danada()
    if os.path.exists(DB_PATH + "-journal") or os.path.exists(DB_PATH + "-wal"):
        # Una sesión anterior se cortó a mitad de guardar (corte de luz, apagado): una conexión de escritura
        # deshace lo pendiente, como haría SQLite al abrir. Si no, las lecturas de solo lectura de abajo fallarían
        # y la base se migraría sin la copia previa.
        try:
            con = sqlite3.connect(DB_PATH, timeout=10)
            try:
                con.execute("SELECT count(*) FROM sqlite_master").fetchone()
            finally:
                con.close()
        except sqlite3.Error:
            pass
    if esquema_desactualizado(DB_PATH):
        copia = respaldar("antes-de-actualizar")
        if not (copia["archivo"] or copia["externas"] or copia["omitido"]):
            raise OSError("No se pudo guardar una copia antes de actualizar la base. " + "; ".join(copia["errores"]))
    return aviso, buscar_restauracion()


def reabrir_con_tk_moderno():
    """El Python de Xcode en macOS trae Tk 8.5, que deja la ventana en negro. Si hay otro Python con
    Tk 8.6 o más, el programa se reabre con él (solo ocurre en esa situación)."""
    if (sys.platform != "darwin" or tk.TkVersion >= 8.6 or getattr(sys, "frozen", False)
            or os.environ.get("AGENCIA_TK_PROBADO")):
        return
    import glob
    import subprocess
    carpetas = ("/opt/homebrew/bin", "/usr/local/bin", os.path.expanduser("~/.local/bin"),
                *glob.glob("/Library/Frameworks/Python.framework/Versions/*/bin"))
    candidatos = sorted({p for c in carpetas for p in glob.glob(os.path.join(c, "python3.*"))
                         if re.fullmatch(r"python3\.\d+", os.path.basename(p))},
                        key=lambda p: int(p.rsplit(".", 1)[1]), reverse=True)
    for python in candidatos:
        try:
            salida = subprocess.run([python, "-c", "import tkinter; print(tkinter.TkVersion)"],
                                    capture_output=True, text=True, timeout=20)
            if salida.returncode == 0 and float(salida.stdout.strip()) >= 8.6:
                os.execve(python, [python, os.path.abspath(__file__), *sys.argv[1:]],
                          dict(os.environ, AGENCIA_TK_PROBADO="1"))
        except (OSError, ValueError, subprocess.SubprocessError):
            continue


def registrar_error(info, ruta=None):
    """Anota un error inesperado en errores.log (junto al programa) y devuelve su detalle.
    Sin consola (pyw / .exe) un fallo en un botón pasaría sin que nadie lo note."""
    ruta = ERRORES_PATH if ruta is None else ruta
    import traceback
    detalle = "".join(traceback.format_exception(*info))
    try:
        if os.path.getsize(ruta) > 512 * 1024:   # el registro no crece sin límite
            os.replace(ruta, f"{ruta}.anterior")
    except OSError:
        pass
    try:
        with open(ruta, "a", encoding="utf-8") as archivo:
            archivo.write(f"--- {datetime.now():%d/%m/%Y %H:%M:%S} ---\n{detalle}\n")
    except OSError:
        pass
    return detalle


def avisar_error(root, tipo, valor, traza, abierto=[False]):
    """Sustituye al informe silencioso de tkinter: guarda el error y avisa una sola vez."""
    registrar_error((tipo, valor, traza))
    if abierto[0]:   # un error repetido no apila ventanas
        return
    abierto[0] = True
    try:
        messagebox.showerror(
            "Error inesperado",
            "No se pudo completar la acción. Lo que ya estaba guardado sigue a salvo.\n\n"
            f"{tipo.__name__}: {valor}\n\nEl detalle quedó en el archivo errores.log.")
    finally:
        abierto[0] = False


def main():
    reabrir_con_tk_moderno()
    try:  # texto nítido en pantallas con escala en Windows
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    try:  # identidad propia en la barra de tareas de Windows: su ícono, no el de Python
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ServicioExclusivo.AgenciaDeEmpleos")
    except Exception:
        pass
    root = tk.Tk()
    root.report_callback_exception = lambda tipo, valor, traza: avisar_error(root, tipo, valor, traza)
    try:
        os.makedirs(CARPETA, exist_ok=True)
        aviso, oferta = preparar_base()
        if not aviso and debe_buscar_datos_anteriores():
            descartados = leer_configuracion().get("datos_anteriores_descartados") or []
            anterior = buscar_datos_anteriores(excluir=[DB_PATH, *[d for d in descartados if isinstance(d, str)]])
            if anterior and (not oferta or anterior["fecha"] > oferta["fecha"]):
                oferta = anterior
        app = App(root)
    except Exception:  # p. ej. base dañada sin respaldo, bloqueada o sin permiso: avisar en vez de cerrarse en silencio
        avisar_error(root, *sys.exc_info())
        root.destroy()
        return
    if aviso:
        root.after(400, lambda: messagebox.showwarning("Base de datos restaurada", aviso))
    elif oferta:
        root.after(400, lambda: app.ofrecer_recuperacion(oferta))
    root.mainloop()


if __name__ == "__main__":
    main()
