"""Comportamientos propios de Windows: archivos retenidos, CSV abiertos en Excel, rutas de red y el Python del
instalador. Las pruebas marcadas «solo Windows» usan el sistema real (GitHub Actions las ejecuta en Windows x64);
las demás simulan Windows y corren en cualquier equipo. Todo con datos ficticios y carpetas temporales."""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

import agencia

EN_WINDOWS = sys.platform == "win32"


def error_windows(codigo):
    error = PermissionError(13, "El proceso no tiene acceso al archivo porque está siendo utilizado por otro proceso")
    error.winerror = codigo
    return error


class ReintentosDeWindows(unittest.TestCase):
    def test_reintenta_mientras_el_archivo_esta_retenido_y_luego_publica(self):
        llamadas = []

        def mover(origen, destino):
            llamadas.append((origen, destino))
            if len(llamadas) < 3:
                raise error_windows(32)
            return "hecho"
        with mock.patch.object(agencia.sys, "platform", "win32"), mock.patch("time.sleep") as espera:
            self.assertEqual(agencia.reintentar_si_windows_bloquea(mover, "a", "b"), "hecho")
        self.assertEqual(len(llamadas), 3)
        self.assertEqual(espera.call_count, 2)

    def test_un_permiso_real_no_se_reintenta_para_siempre(self):
        mover = mock.Mock(side_effect=error_windows(32))
        with mock.patch.object(agencia.sys, "platform", "win32"), mock.patch("time.sleep"):
            with self.assertRaises(PermissionError):
                agencia.reintentar_si_windows_bloquea(mover, "a", "b", intentos=4)
        self.assertEqual(mover.call_count, 4)
        otro = mock.Mock(side_effect=error_windows(1224))    # otro error de Windows: no es un bloqueo pasajero
        with mock.patch.object(agencia.sys, "platform", "win32"), mock.patch("time.sleep"):
            with self.assertRaises(PermissionError):
                agencia.reintentar_si_windows_bloquea(otro, "a", "b")
        self.assertEqual(otro.call_count, 1)

    def test_fuera_de_windows_se_ejecuta_una_sola_vez(self):
        mover = mock.Mock(side_effect=error_windows(32))
        with mock.patch.object(agencia.sys, "platform", "darwin"):
            with self.assertRaises(PermissionError):
                agencia.reintentar_si_windows_bloquea(mover, "a", "b")
        self.assertEqual(mover.call_count, 1)


class CSVAbiertoEnExcel(unittest.TestCase):
    NOMBRES = ("Clientes.csv", "Trabajadoras.csv", "Asignaciones.csv", "Areas.csv")

    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory(prefix="csv-excel-", ignore_cleanup_errors=True)
        self.carpeta = Path(self.temporal.name)
        self.ruta = self.carpeta / "agencia.db"
        db = agencia.BaseDatos(str(self.ruta))
        db.insertar("clientes", {"nombre": "Cliente nuevo"})
        db.con.close()
        self.destino = self.carpeta / "Datos legibles"
        self.destino.mkdir()
        for nombre in self.NOMBRES:
            (self.destino / nombre).write_bytes(b"anterior\r\n")

    def tearDown(self):
        self.temporal.cleanup()

    def comprobar(self, error):
        self.assertIsInstance(error, agencia.CSVOcupados)
        self.assertEqual(error.nombres, ["Clientes.csv"])
        self.assertIn("Clientes.csv", str(error))
        self.assertIn("Excel", str(error))
        self.assertEqual((self.destino / "Clientes.csv").read_bytes(), b"anterior\r\n")        # intacto
        for nombre in self.NOMBRES[1:]:                                                         # los demás, al día
            self.assertTrue((self.destino / nombre).read_bytes().startswith(b"\xef\xbb\xbfid,"))
        self.assertEqual(sorted(p.name for p in self.destino.iterdir()), sorted(self.NOMBRES))  # sin temporales

    def test_se_actualizan_los_demas_y_el_abierto_queda_igual(self):
        reemplazar = os.replace

        def como_excel(origen, destino):
            if Path(destino).name == "Clientes.csv":
                raise error_windows(32)
            return reemplazar(origen, destino)
        with mock.patch.object(agencia.sys, "platform", "win32"), mock.patch("time.sleep"), \
                mock.patch.object(agencia.os, "replace", side_effect=como_excel):
            with self.assertRaises(agencia.CSVOcupados) as contexto:
                agencia.exportar_legible(str(self.ruta), str(self.destino))
        self.comprobar(contexto.exception)

    @unittest.skipUnless(EN_WINDOWS, "solo Windows: un archivo abierto no se puede reemplazar")
    def test_con_el_archivo_abierto_de_verdad(self):
        with open(self.destino / "Clientes.csv", "rb"):      # como Excel: abierto sin permitir borrarlo
            with self.assertRaises(agencia.CSVOcupados) as contexto:
                agencia.exportar_legible(str(self.ruta), str(self.destino))
        self.comprobar(contexto.exception)

    def test_la_copia_externa_cuenta_como_hecha_y_el_aviso_no_cambia(self):
        externa = self.carpeta / "externa"
        aviso = agencia.CSVOcupados(["Clientes.csv"])
        with mock.patch.object(agencia, "exportar_legible", side_effect=aviso), \
                mock.patch.object(agencia, "carpetas_externas", return_value=[str(externa)]):
            primera = agencia.respaldar("auto", ruta=str(self.ruta), carpeta=str(self.carpeta / "respaldos"))
            segunda = agencia.respaldar("auto", ruta=str(self.ruta), carpeta=str(self.carpeta / "respaldos"))
        self.assertEqual(primera["externas"], [str(externa)])
        self.assertTrue(primera["archivo"])
        self.assertEqual(len(primera["errores"]), 1)
        self.assertEqual(primera["errores"], segunda["errores"])      # mismo texto: se avisa una sola vez
        self.assertTrue(any(externa.glob("agencia-*.db")))


class RutasDeWindows(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory(prefix="rutas ñ #% ", ignore_cleanup_errors=True)
        self.ruta = os.path.join(self.temporal.name, "datos José Peña", "agencia.db")
        os.makedirs(os.path.dirname(self.ruta))
        db = agencia.BaseDatos(self.ruta)
        db.insertar("clientes", {"nombre": "Ana"})
        db.con.close()

    def tearDown(self):
        self.temporal.cleanup()

    def test_rutas_con_tildes_espacios_y_simbolos(self):
        self.assertTrue(agencia.base_sana(self.ruta))
        self.assertEqual(agencia.contar_datos(self.ruta)["clientes"], 1)
        with closing(agencia.conexion_lectura(self.ruta)) as con:
            with self.assertRaises(sqlite3.OperationalError):
                con.execute("INSERT INTO clientes (nombre) VALUES ('no')")     # solo lectura de verdad

    @unittest.skipUnless(EN_WINDOWS, "solo Windows")
    def test_uri_de_unidad_y_de_red(self):
        with mock.patch("os.path.abspath", side_effect=lambda r: r):
            self.assertEqual(agencia.uri_sqlite(r"Z:\Respaldos\agencia 1.db"), "file:///Z:/Respaldos/agencia%201.db")
            self.assertEqual(agencia.uri_sqlite(r"\\NAS\copias\agencia.db"), "file:////NAS/copias/agencia.db")
            self.assertEqual(agencia.uri_sqlite(r"\\?\UNC\NAS\copias\a.db"), "file:////NAS/copias/a.db")

    @unittest.skipUnless(EN_WINDOWS, "solo Windows: recurso administrativo \\\\localhost\\C$")
    def test_una_copia_en_una_ruta_de_red_se_puede_leer(self):
        unidad, resto = os.path.splitdrive(os.path.abspath(self.ruta))
        red = "\\\\localhost\\" + unidad.rstrip(":") + "$" + resto
        if not os.path.exists(red):
            self.skipTest("este equipo no comparte " + unidad + "$")
        self.assertTrue(agencia.base_sana(red))
        self.assertEqual(agencia.contar_datos(red)["clientes"], 1)
        copia = os.path.join(os.path.dirname(red), "copia de red.db")
        agencia.copiar_base(self.ruta, copia)          # copia verificada con SQLite escrita en la ruta de red
        self.assertEqual(agencia.contar_datos(copia)["clientes"], 1)


class DatosDeUnaVersionAnterior(unittest.TestCase):
    """Quien usaba Iniciar.bat o Agencia.exe tenía agencia.db junto al programa; al pasar al instalador el programa
    abre vacío. Se buscan esos datos (solo lectura) para ofrecer traerlos."""

    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory(prefix="casa-ficticia-", ignore_cleanup_errors=True)
        self.casa = Path(self.temporal.name)

    def tearDown(self):
        self.temporal.cleanup()

    def base(self, relativa, clientes=1):
        ruta = self.casa / relativa
        ruta.parent.mkdir(parents=True, exist_ok=True)
        db = agencia.BaseDatos(str(ruta))
        for i in range(clientes):
            db.insertar("clientes", {"nombre": f"Cliente ficticio {i}"})
        db.con.close()
        return ruta

    def test_encuentra_la_mas_reciente_con_datos_y_salta_las_carpetas_del_sistema(self):
        vieja = self.base("Documents/Agencia vieja/agencia.db", clientes=2)
        os.utime(vieja, (1_600_000_000, 1_600_000_000))
        nueva = self.base("Desktop/Programa Tía/agencia.db", clientes=3)
        self.base("Downloads/vacia/agencia.db", clientes=0)
        self.base("AppData/Local/Agencia de Empleos/agencia.db", clientes=9)     # la del propio programa: no
        self.base("Desktop/Programa Tía/respaldos/agencia.db", clientes=9)       # una copia: no
        encontrada = agencia.buscar_datos_anteriores(agencia.lugares_datos_anteriores(str(self.casa)))
        self.assertEqual(Path(encontrada["ruta"]), nueva)
        self.assertEqual(encontrada["clientes"], 3)
        self.assertTrue(encontrada["anterior"])
        # la ya descartada no se vuelve a ofrecer: queda la siguiente
        otra = agencia.buscar_datos_anteriores(agencia.lugares_datos_anteriores(str(self.casa)), excluir=[str(nueva)])
        self.assertEqual(Path(otra["ruta"]), vieja)

    def test_sin_tiempo_o_sin_datos_no_ofrece_nada(self):
        self.base("Desktop/Agencia/agencia.db", clientes=0)
        self.assertIsNone(agencia.buscar_datos_anteriores(agencia.lugares_datos_anteriores(str(self.casa))))
        self.base("Desktop/Otra/agencia.db", clientes=1)
        self.assertIsNone(agencia.buscar_datos_anteriores(agencia.lugares_datos_anteriores(str(self.casa)), limite=0))

    def test_aceptar_trae_los_datos_y_rechazar_no_vuelve_a_preguntar(self):
        anterior = self.base("Desktop/Agencia/agencia.db", clientes=2)
        original = anterior.read_bytes()
        copia = agencia.buscar_datos_anteriores(agencia.lugares_datos_anteriores(str(self.casa)))
        actual = str(self.casa / "datos" / "agencia.db")
        os.makedirs(os.path.dirname(actual))
        db = agencia.BaseDatos(actual)
        app = mock.Mock(db=db, root=None)
        configuracion = str(self.casa / "datos" / "configuracion.json")
        try:
            with mock.patch.object(agencia, "DB_PATH", actual), mock.patch.object(agencia, "CONFIG_PATH", configuracion), \
                    mock.patch.object(agencia.messagebox, "askyesno", return_value=False) as pregunta:
                agencia.App.ofrecer_recuperacion(app, copia)
                self.assertIn(str(anterior), pregunta.call_args[0][1])
                self.assertEqual(agencia.leer_configuracion(configuracion)["datos_anteriores_descartados"], [str(anterior)])
                self.assertEqual(db.todos("clientes"), [])
            with mock.patch.object(agencia, "DB_PATH", actual), \
                    mock.patch.object(agencia.messagebox, "askyesno", return_value=True), \
                    mock.patch.object(agencia.messagebox, "showinfo"):
                agencia.App.ofrecer_recuperacion(app, copia)
            self.assertEqual(len(db.todos("clientes")), 2)
            self.assertEqual(anterior.read_bytes(), original)      # el archivo original no se toca
        finally:
            db.con.close()


class InstalacionDeWindows(unittest.TestCase):
    def test_sin_datos_en_la_linea_de_comandos_nunca_usa_la_carpeta_del_programa(self):
        with tempfile.TemporaryDirectory() as raiz:
            app = os.path.join(raiz, "app")
            os.makedirs(os.path.join(raiz, "runtime"))
            Path(raiz, "runtime", "pythonw.exe").write_bytes(b"ficticio")
            with mock.patch.object(agencia, "carpeta_app", return_value=app):
                # instalada: sea cual sea el Python que la abra (el incluido o uno del sistema)
                datos = agencia.carpeta_datos(argv=["iniciar.pyw"], entorno={"LOCALAPPDATA": "L"}, plataforma="win32")
                self.assertEqual(datos, os.path.join("L", agencia.AGENCIA_NOMBRE))
                # con --datos manda lo indicado
                self.assertEqual(agencia.carpeta_datos(argv=["iniciar.pyw", "--datos", "D"], entorno={},
                                                       plataforma="win32"), "D")
                # en Mac/Linux no aplica
                self.assertFalse(agencia.instalado_con_runtime("darwin"))
            # una carpeta propia sin runtime (Iniciar.bat) sigue usando la carpeta del programa, como siempre
            suelta = os.path.join(raiz, "Programa de la agencia")
            with mock.patch.object(agencia, "carpeta_app", return_value=suelta):
                self.assertEqual(agencia.carpeta_datos(argv=["agencia.py"], entorno={}, plataforma="win32"), suelta)

    @unittest.skipUnless(EN_WINDOWS, "solo Windows")
    def test_el_tcl_del_python_propio_manda_sobre_el_entorno(self):
        propio = os.path.join(sys.base_prefix, "tcl", "tcl8.6")
        if not os.path.isfile(os.path.join(propio, "init.tcl")):
            self.skipTest("este Python no trae Tcl en tcl\\tcl8.6")
        self.assertEqual(os.path.normcase(os.environ.get("TCL_LIBRARY", "")), os.path.normcase(propio))


if __name__ == "__main__":
    unittest.main()
