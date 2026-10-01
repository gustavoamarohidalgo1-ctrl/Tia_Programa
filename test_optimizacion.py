"""Regresiones de cachés y recuperación con datos ficticios, sin abrir ventanas."""
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
from unittest.mock import Mock, patch

if not os.environ.get("AGENCIA_DATOS"):      # nunca la carpeta de datos real, aunque se pruebe desde el proyecto
    os.environ["AGENCIA_DATOS"] = tempfile.mkdtemp(prefix="agencia-pruebas-")

import agencia


class OptimizacionTest(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory()
        self.carpeta = Path(self.temporal.name)
        self.respaldos = self.carpeta / "respaldos"
        self.respaldos.mkdir()
        self.ruta = self.carpeta / "actual.db"
        self.db = agencia.BaseDatos(str(self.ruta))
        agencia.cargar_areas(self.db)
        self.app = agencia.App.__new__(agencia.App)
        self.app.db = self.db
        self.app._reemplazos = (-1, {})
        agencia._RECUENTOS_COPIAS.clear()

    def tearDown(self):
        self.db.con.close()
        agencia._RECUENTOS_COPIAS.clear()
        agencia.restablecer_areas()
        self.temporal.cleanup()

    def ingresos(self):
        cliente = self.db.insertar("clientes", {"nombre": "Cliente ficticio", "tipo_servicio": list(agencia.AREAS)[0]})
        enlace = self.db.insertar("colocaciones", {"cliente_id": str(cliente), "comision": "150.00",
                                                "comision_pagada": "1", "fecha_pago": "15/01/2026"})
        return cliente, enlace

    def copia(self, nombre="copia.db", fecha=1000):
        destino = self.respaldos / nombre
        agencia.copiar_base(str(self.ruta), str(destino))
        os.utime(destino, (fecha, fecha))
        return destino

    def test_resumen_compartido_recalcula_solo_por_datos_relevantes(self):
        cliente, enlace = self.ingresos()
        dia = date(2026, 1, 15)
        with patch.object(agencia, "resumen_ganancias", wraps=agencia.resumen_ganancias) as calcular:
            anterior = self.app.resumen_financiero(dia)
            self.db.insertar("trabajadoras", {"nombre": "Persona ficticia"})
            self.assertIs(self.app.resumen_financiero(dia), anterior)
            self.assertEqual(calcular.call_count, 1)
            self.db.actualizar("colocaciones", enlace, {"comision": "200"})
            nuevo = self.app.resumen_financiero(dia)
            self.assertEqual(nuevo["cobrado_total"], 200)
            self.assertEqual(anterior["cobrado_total"], 150)
            self.db.actualizar("clientes", cliente, {"nombre": "Nombre revisado"})
            self.assertEqual(self.app.resumen_financiero(dia)["historial"][0]["cliente"], "Nombre revisado")
            self.assertEqual(self.app.resumen_financiero(date(2026, 2, 15))["cobrado_mes"], 0)
            area = list(agencia.AREAS)[0]
            agencia.AREAS[area] = ("Título revisado", "Descripción")
            self.assertEqual(self.app.resumen_financiero(dia)["por_area"]["Título revisado"], 200)
            self.assertEqual(calcular.call_count, 5)

    def test_resumen_descarta_cambios_revertidos_y_detecta_cambios_externos(self):
        _, enlace = self.ingresos()
        dia = date(2026, 1, 15)
        self.app.resumen_financiero(dia)
        with self.assertRaises(RuntimeError):
            with self.db.lote():
                self.db.actualizar("colocaciones", enlace, {"comision": "999"})
                self.assertEqual(self.app.resumen_financiero(dia)["cobrado_total"], 999)
                raise RuntimeError("revertir")
        self.assertEqual(self.app.resumen_financiero(dia)["cobrado_total"], 150)
        with closing(sqlite3.connect(self.ruta)) as otra, otra:
            otra.execute("UPDATE colocaciones SET comision='250' WHERE id=?", (enlace,))
        self.assertTrue(self.db.cambio_externo())
        self.assertEqual(self.app.resumen_financiero(dia)["cobrado_total"], 250)

    def test_mantenimiento_no_repite_barridos_por_cambios_en_trabajadoras(self):
        self.ingresos()
        self.app.iniciar_contratos_firmados()
        self.app.cerrar_garantias_vencidas()
        self.app.reemplazo_pendiente(1)
        self.db.insertar("trabajadoras", {"nombre": "Persona ficticia"})
        with patch.object(self.db, "todos", wraps=self.db.todos) as todos:
            self.app.iniciar_contratos_firmados()
            self.app.cerrar_garantias_vencidas()
            self.app.reemplazo_pendiente(1)
            todos.assert_not_called()

    def test_inicios_se_guardan_juntos_y_revierten_completos_si_hay_error(self):
        ids = []
        for i in range(3):
            cliente = self.db.insertar("clientes", {"nombre": f"Cliente de prueba {i}", "estado": "En entrevista"})
            trabajadora = self.db.insertar("trabajadoras", {"nombre": f"Trabajadora de prueba {i}", "estado": "Disponible"})
            ids.append(self.db.insertar("colocaciones", {"cliente_id": str(cliente), "trabajadora_id": str(trabajadora),
                "estado": "En proceso", "contrato_firmado": "1", "fecha_contrato": "15/01/2026", "garantia": "No"}))
        with patch.object(self.app, "sincronizar", side_effect=[None, RuntimeError("fallo"), None]):
            with self.assertRaises(RuntimeError):
                self.app.iniciar_contratos_firmados()
        self.assertEqual([self.db.uno("colocaciones", i)["estado"] for i in ids], ["En proceso"] * 3)
        sql = []
        self.db.con.set_trace_callback(sql.append)
        self.app.iniciar_contratos_firmados()
        self.db.con.set_trace_callback(None)
        self.assertEqual([self.db.uno("colocaciones", i)["estado"] for i in ids], ["Activa"] * 3)
        puntos = [s for s in sql if s.upper().startswith("SAVEPOINT LOTE")]
        self.assertTrue(puntos)
        self.assertEqual(sum(s.upper() == "BEGIN IMMEDIATE" for s in sql), 1)
        self.assertEqual(sum(s.upper() == "COMMIT" for s in sql), 1)
        self.assertFalse(self.db.con.in_transaction)

    def test_catalogo_reutiliza_recuentos_y_devuelve_diccionarios_independientes(self):
        self.ingresos()
        self.copia()
        carpetas = [(str(self.respaldos), "Prueba")]
        with patch.object(agencia, "contar_datos", wraps=agencia.contar_datos) as contar:
            primera = agencia.listar_copias(carpetas)
            llamadas = contar.call_count
            primera[0]["clientes"] = 999
            segunda = agencia.listar_copias(carpetas)
            self.assertEqual(contar.call_count, llamadas)
            self.assertTrue(all(c["clientes"] == 1 for c in segunda))

    def test_catalogo_detecta_modificacion_y_sustitucion_del_archivo(self):
        self.ingresos()
        copia = self.copia()
        estado = copia.stat()
        self.assertEqual(agencia._datos_de_copia(str(copia), estado)["clientes"], 1)
        with closing(sqlite3.connect(copia)) as con, con:
            con.execute("INSERT INTO clientes (nombre) VALUES ('Otro cliente ficticio')")
        self.assertEqual(agencia._datos_de_copia(str(copia), copia.stat())["clientes"], 2)
        nueva = self.copia("nueva.db")
        os.replace(nueva, copia)
        os.utime(copia, ns=(estado.st_atime_ns, estado.st_mtime_ns))
        self.assertEqual(agencia._datos_de_copia(str(copia), copia.stat())["clientes"], 1)

    def test_errores_de_lectura_se_reintentan_y_no_se_cachean(self):
        self.ingresos()
        copia = self.copia()
        with patch.object(agencia, "contar_datos", side_effect=[None, {"clientes": 1}]) as contar:
            self.assertIsNone(agencia._datos_de_copia(str(copia), copia.stat()))
            self.assertEqual(agencia._datos_de_copia(str(copia), copia.stat()), {"clientes": 1})
            self.assertEqual(contar.call_count, 2)

    def test_catalogo_no_cachea_bases_con_wal(self):
        self.ingresos()
        copia = self.copia()
        con = sqlite3.connect(copia)
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA wal_autocheckpoint=0")
            con.execute("INSERT INTO clientes (nombre) VALUES ('Cliente WAL')")
            con.commit()
            antes = copia.stat()
            self.assertEqual(agencia._datos_de_copia(str(copia), antes)["clientes"], 2)
            con.execute("INSERT INTO clientes (nombre) VALUES ('Otro cliente WAL')")
            con.commit()
            self.assertEqual(agencia._datos_de_copia(str(copia), copia.stat())["clientes"], 3)
            self.assertFalse(any(k[0] == str(copia.resolve()) for k in agencia._RECUENTOS_COPIAS))
        finally:
            con.close()

    def test_recuperacion_se_detiene_en_la_copia_mas_reciente_con_datos(self):
        self.ingresos()
        self.copia("antigua.db", 1000)
        nueva = self.copia("nueva.db", 2000)
        ausente = str(self.carpeta / "ausente.db")
        with patch.object(agencia, "contar_datos", wraps=agencia.contar_datos) as contar:
            oferta = agencia.buscar_restauracion(ausente, [(str(self.respaldos), "Prueba")])
            self.assertEqual(oferta["ruta"], str(nueva))
            self.assertEqual(contar.call_count, 2)  # base ausente y copia elegida
            self.assertFalse(Path(ausente).exists())

    def test_fuente_ausente_no_se_crea_y_destino_se_conserva(self):
        self.ingresos()
        ausente = self.carpeta / "ausente.db"
        antes = self.ruta.read_bytes()
        for operacion in (agencia.copiar_base, agencia.restaurar_archivo, self.db.restaurar_desde):
            with self.assertRaises(sqlite3.Error):
                if operacion == self.db.restaurar_desde:
                    operacion(str(ausente))
                else:
                    operacion(str(ausente), str(self.ruta))
            self.assertFalse(ausente.exists())
            self.assertEqual(self.ruta.read_bytes(), antes)

    def test_restauracion_conserva_la_copia_elegida_si_la_poda_la_borra(self):
        self.ingresos()
        elegida = self.copia()
        self.db.insertar("clientes", {"nombre": "Cliente posterior"})
        self.app.root = Mock()
        self.app.clientes = Mock()
        self.app.trabajadoras = Mock()
        self.app.refrescar_todo = Mock()
        def copiar_y_podar(*args, **kwargs):
            elegida.unlink()
            return {"archivo": "previa.db", "omitido": None, "errores": []}
        self.app.hacer_copia = Mock(side_effect=copiar_y_podar)
        copia = {"ruta": str(elegida), "fecha": datetime(2026, 1, 15),
                 "clientes": 1, "trabajadoras": 0, "colocaciones": 1}
        with patch.object(agencia, "DB_PATH", str(self.ruta)), patch.object(agencia.messagebox, "askyesno", return_value=True):
            self.assertTrue(self.app.restaurar_copia(copia))
        self.assertEqual(len(self.db.todos("clientes")), 1)
        self.assertFalse(elegida.exists())
        self.app.refrescar_todo.assert_called_once()

    def test_numero_mantiene_formatos_y_rechaza_valores_no_finitos(self):
        ejemplos = {"2,200": 2200, "12,50": 12.5, "1.234,56": 1234.56,
                    "1,234.56": 1234.56, "S/ 2 200": 2200, "-100": -100}
        for texto, esperado in ejemplos.items():
            self.assertEqual(agencia.leer_numero(texto), esperado)
            self.assertEqual(agencia.leer_numero(texto), esperado)
        for invalido in ("nan", "inf", "-inf", float("nan"), float("inf")):
            self.assertIsNone(agencia.leer_numero(invalido))

    def test_liberacion_ignora_widgets_secundarios_y_cierra_solo_una_vez(self):
        self.app.root = Mock()
        self.app.root.tk.call.return_value = ("after#1", "after#2")
        self.app._liberar_recursos(Mock(widget=Mock()))
        self.assertEqual(self.db.todos("clientes"), [])
        self.app.root.after_cancel.assert_not_called()
        evento = Mock(widget=self.app.root)
        self.app._liberar_recursos(evento)
        self.app._liberar_recursos(evento)
        canceladas = [llamada for llamada in self.app.root.tk.call.call_args_list
                      if llamada.args[:2] == ("after", "cancel")]
        self.assertEqual(len(canceladas), 2)
        with self.assertRaises(sqlite3.ProgrammingError):
            self.db.con.execute("SELECT 1")

    def test_error_cancelando_un_timer_no_impide_cancelar_los_demas(self):
        self.app.root = Mock()
        self.app.root.tk.call.side_effect = [("after#1", "after#2"), agencia.tk.TclError("ya eliminado"), None]
        self.app._liberar_recursos(Mock(widget=self.app.root))
        self.assertEqual(self.app.root.tk.call.call_count, 3)
        with self.assertRaises(sqlite3.ProgrammingError):
            self.db.con.execute("SELECT 1")

    def test_vigilar_actualiza_al_cambiar_dia_sin_cambios_externos(self):
        enlace = self.db.insertar("colocaciones", {"estado": "Activa", "garantia": "Sí",
                                                "meses_garantia": "1", "fin_garantia": "31/01/2026"})
        self.app.root = Mock()
        self.app._dia_refresco = date(2026, 1, 31)
        nuevo_dia = date(2026, 2, 1)
        def refrescar():
            self.app._dia_refresco = nuevo_dia
            self.app.cerrar_garantias_vencidas()
        self.app.refrescar_todo = Mock(side_effect=refrescar)
        with patch.object(agencia, "date") as fecha:
            fecha.today.return_value = nuevo_dia
            self.app.vigilar_cambios()
            self.app.vigilar_cambios()
        self.assertEqual(self.db.uno("colocaciones", enlace)["estado"], "Garantía cumplida")
        self.app.refrescar_todo.assert_called_once()

    def test_mostrar_actualiza_al_cambiar_dia_antes_del_siguiente_timer(self):
        self.app.root = Mock()
        self.app.lateral = Mock()
        self.app.enlazar = Mock()
        self.app.contratos = Mock()
        self.app.areas = Mock()
        self.app.visible = Mock()
        self.app.refrescar_visible = Mock()
        self.app.refrescar_todo = Mock()
        self.app._dia_refresco = date(2026, 1, 31)
        pagina = Mock()
        with patch.object(agencia, "date") as fecha:
            fecha.today.return_value = date(2026, 2, 1)
            self.app.mostrar(pagina)
        self.app.refrescar_todo.assert_called_once()
        self.app.refrescar_visible.assert_called_once()
        pagina.tkraise.assert_called_once()


if __name__ == "__main__":
    unittest.main()
