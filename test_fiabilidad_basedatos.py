"""Conservación y fallos reales de SQLite de Servicio Exclusivo, sólo con datos temporales."""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import shutil
import tempfile
import threading
import time
import unittest
from unittest import mock

from test_optimizacion_basedatos import MODULOS


class CasosFiabilidad:
    agencia = None

    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory(prefix="agencia-fiabilidad-")
        self.ruta = Path(self.temporal.name) / "actual.db"
        self.db = self.agencia.BaseDatos(self.ruta)
        self.id_ = self.db.insertar("clientes", {"nombre": "Cliente conservado"})
        self.db.todos("clientes")

    def tearDown(self):
        self.db.con.close()
        self.temporal.cleanup()

    def copia(self):
        ruta = Path(self.temporal.name) / "copia.db"
        otra = self.agencia.BaseDatos(ruta)
        try:
            otra.insertar("clientes", {"nombre": "Cliente de la copia"})
        finally:
            otra.con.close()
        return ruta

    def nombres_directos(self):
        return [r[0] for r in self.db.con.execute("SELECT nombre FROM clientes ORDER BY id")]

    def instalar_trigger_fallido(self):
        self.db.insertar("trabajadoras", {"nombre": "Trabajadora conservada"})
        self.db.con.execute("CREATE TRIGGER fallo_real AFTER UPDATE ON clientes "
                            "WHEN NEW.nombre = 'Guardado fallido' BEGIN "
                            "UPDATE trabajadoras SET nombre = 'Cambio oculto'; "
                            "SELECT RAISE(FAIL, 'Guardado rechazado'); END")
        self.db.con.commit()

    def test_execute_fallido_no_deja_transaccion_ni_cambios_para_otro_guardado(self):
        self.instalar_trigger_fallido()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.actualizar("clientes", self.id_, {"nombre": "Guardado fallido"})
        self.assertFalse(self.db.con.in_transaction)
        self.assertEqual(self.nombres_directos(), ["Cliente conservado"])
        self.db.insertar("clientes", {"nombre": "Otro guardado"})
        with closing(sqlite3.connect(self.ruta)) as lector:
            self.assertEqual(lector.execute("SELECT nombre FROM trabajadoras").fetchone()[0],
                             "Trabajadora conservada")

    def test_fallo_capturado_dentro_lote_revierte_solo_la_escritura_fallida(self):
        self.instalar_trigger_fallido()
        with self.db.lote():
            nuevo = self.db.insertar("clientes", {"nombre": "Anterior al error"})
            with self.assertRaises(sqlite3.IntegrityError):
                self.db.actualizar("clientes", self.id_, {"nombre": "Guardado fallido"})
            self.db.actualizar("clientes", nuevo, {"zona": "Ate"})
        self.assertEqual(self.nombres_directos(), ["Cliente conservado", "Anterior al error"])
        self.assertEqual(self.db.todos("trabajadoras")[0]["nombre"], "Trabajadora conservada")

    def test_restaurar_mismo_archivo_o_alias_se_rechaza_antes_de_abrirlo(self):
        alias = Path(self.temporal.name) / "alias.db"
        os.link(self.ruta, alias)
        for ruta in (self.ruta, alias):
            with self.subTest(ruta=ruta), mock.patch.object(
                    self.agencia, "conexion_lectura", side_effect=AssertionError("Backup a sí mismo")):
                with self.assertRaises(ValueError):
                    self.db.restaurar_desde(ruta)
        alias.unlink()
        # SQLite de macOS invalida su descriptor cuando cambia el número de enlaces del archivo.
        # La detección ocurrió sin consultas/backup; reabrir permite verificar la conservación física.
        self.db.con.close()
        self.db = self.agencia.BaseDatos(self.ruta)
        self.assertEqual(self.nombres_directos(), ["Cliente conservado"])

    def test_fallo_de_migracion_no_reemplaza_la_base_viva_ni_sus_caches(self):
        copia = self.copia()
        antes = self.db.todos("clientes")
        with mock.patch.object(self.agencia.BaseDatos, "_migrar", side_effect=RuntimeError("Migración fallida")):
            with self.assertRaises(RuntimeError):
                self.db.restaurar_desde(copia)
        self.assertEqual(self.nombres_directos(), ["Cliente conservado"])
        self.assertIs(self.db.todos("clientes"), antes)
        self.assertFalse(self.db.con.in_transaction)

    def test_fallo_de_publicacion_recupera_destino_y_conserva_cache_anterior(self):
        copia = self.copia()
        antes = self.db.todos("clientes")
        copiar = self.agencia._copiar_sqlite
        fallado = False

        def publicar(fuente, destino, limite=30):
            nonlocal fallado
            copiar(fuente, destino, limite)
            if destino is self.db.con and not fallado:
                fallado = True
                raise sqlite3.OperationalError("Fallo después de publicar")

        with mock.patch.object(self.agencia, "_copiar_sqlite", side_effect=publicar):
            with self.assertRaises(sqlite3.OperationalError):
                self.db.restaurar_desde(copia)
        self.assertEqual(self.nombres_directos(), ["Cliente conservado"])
        self.assertIs(self.db.todos("clientes"), antes)

    def test_source_wal_se_restaura_con_temporal_delete_legible_sin_laterales(self):
        copia = self.copia()
        fuente = self.agencia.BaseDatos(copia)
        fuente.con.execute("PRAGMA journal_mode = WAL")
        fuente.insertar("clientes", {"nombre": "Escrito en WAL"})
        copiar = self.agencia._copiar_sqlite
        comprobadas = []

        def publicar(origen, destino, limite=30):
            if destino is self.db.con:
                self.assertEqual(origen.execute("PRAGMA journal_mode").fetchone()[0], "delete")
                ruta = next(r[2] for r in origen.execute("PRAGMA database_list") if r[1] == "main")
                sin_laterales = Path(self.temporal.name) / "temporal_sin_wal.db"
                sin_laterales.write_bytes(Path(ruta).read_bytes())
                with closing(self.agencia.conexion_lectura(sin_laterales)) as lector:
                    self.assertEqual(lector.execute("PRAGMA quick_check").fetchone()[0], "ok")
                    self.assertEqual(lector.execute("SELECT COUNT(*) FROM clientes").fetchone()[0], 2)
                comprobadas.append(ruta)
            copiar(origen, destino, limite)

        try:
            with mock.patch.object(self.agencia, "_copiar_sqlite", side_effect=publicar):
                self.db.restaurar_desde(copia)
            self.assertEqual(fuente.con.execute("PRAGMA journal_mode").fetchone()[0], "wal")
            self.assertEqual(self.db.con.execute("PRAGMA journal_mode").fetchone()[0], "delete")
            self.assertEqual(self.nombres_directos(), ["Cliente de la copia", "Escrito en WAL"])
            self.assertEqual(len(comprobadas), 1)
        finally:
            fuente.con.close()

    def test_destino_wal_conserva_modo_y_resguardo_delete_al_recuperar(self):
        copia = self.copia()
        self.db.con.execute("PRAGMA journal_mode = WAL")
        copiar = self.agencia._copiar_sqlite
        fallado = False
        modos = []

        def publicar(origen, destino, limite=30):
            nonlocal fallado
            if destino is self.db.con:
                modos.append(origen.execute("PRAGMA journal_mode").fetchone()[0])
            copiar(origen, destino, limite)
            if destino is self.db.con and not fallado:
                fallado = True
                raise sqlite3.OperationalError("Fallo después de publicar")

        with mock.patch.object(self.agencia, "_copiar_sqlite", side_effect=publicar):
            with self.assertRaises(sqlite3.OperationalError):
                self.db.restaurar_desde(copia)
        self.assertEqual(modos, ["delete", "delete"])
        self.assertEqual(self.db.con.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        self.assertEqual(self.nombres_directos(), ["Cliente conservado"])

    def test_recuperacion_fallida_retiene_resguardo_legible(self):
        copia = self.copia()
        copiar = self.agencia._copiar_sqlite

        def publicar(fuente, destino, limite=30):
            if destino is self.db.con:
                raise sqlite3.OperationalError("Destino ocupado")
            copiar(fuente, destino, limite)

        with mock.patch.object(self.agencia, "_copiar_sqlite", side_effect=publicar):
            with self.assertRaises(sqlite3.DatabaseError) as capturada:
                self.db.restaurar_desde(copia)
        resguardo = Path(str(capturada.exception).rsplit(": ", 1)[1])
        try:
            self.assertTrue(resguardo.is_file())
            with closing(sqlite3.connect(resguardo)) as lector:
                self.assertEqual(lector.execute("PRAGMA quick_check").fetchone()[0], "ok")
                self.assertEqual(lector.execute("SELECT nombre FROM clientes").fetchone()[0], "Cliente conservado")
        finally:
            shutil.rmtree(resguardo.parent)

    def test_destino_bloqueado_termina_con_resguardo_y_sin_reemplazar_datos(self):
        copia = self.copia()
        copiar = self.agencia._copiar_sqlite
        self.db.con.execute("PRAGMA busy_timeout = 5")
        lector = sqlite3.connect(self.ruta)
        lector.execute("BEGIN")
        lector.execute("SELECT * FROM clientes").fetchall()
        inicio = time.monotonic()
        try:
            with mock.patch.object(self.agencia, "_copiar_sqlite",
                                   side_effect=lambda fuente, destino, limite=30: copiar(fuente, destino, 0.03)):
                with self.assertRaises(sqlite3.DatabaseError) as capturada:
                    self.db.restaurar_desde(copia)
        finally:
            lector.rollback()
            lector.close()
        self.assertLess(time.monotonic() - inicio, 2)
        self.assertEqual(self.nombres_directos(), ["Cliente conservado"])
        resguardo = Path(str(capturada.exception).rsplit(": ", 1)[1])
        self.assertTrue(resguardo.is_file())
        shutil.rmtree(resguardo.parent)

    def test_actualizacion_congela_firmados_previos_sin_reescribir_snapshot(self):
        trabajadora = self.db.insertar("trabajadoras", {"nombre": "Nombre original"})
        contrato = self.db.insertar("colocaciones", {
            "cliente_id": str(self.id_), "trabajadora_id": str(trabajadora),
            "contrato_firmado": "1", "contrato_html": "", "fecha_firma": "2026-09-29"})
        self.db.con.close()
        self.db = self.agencia.BaseDatos(self.ruta)
        documento = self.db.uno("colocaciones", contrato)["contrato_html"]
        self.assertIn("Nombre original", documento)
        self.db.actualizar("trabajadoras", trabajadora, {"nombre": "Ficha editada"})
        self.db.con.close()
        self.db = self.agencia.BaseDatos(self.ruta)
        self.assertEqual(self.db.uno("colocaciones", contrato)["contrato_html"], documento)

    def test_firmado_heredado_sin_persona_conserva_fila_y_no_inventa_documento(self):
        contrato = self.db.insertar("colocaciones", {
            "cliente_id": str(self.id_), "trabajadora_id": "999999", "contrato_firmado": "1"})
        self.db.con.close()
        self.db = self.agencia.BaseDatos(self.ruta)
        fila = self.db.uno("colocaciones", contrato)
        self.assertEqual(fila["contrato_html"], "")
        self.assertEqual(fila["trabajadora_id"], "999999")

    def test_guardado_local_incorpora_cambios_ajenos_en_otras_filas(self):
        otro = self.db.insertar("clientes", {"nombre": "Otra ficha", "zona": "Lince"})
        self.db.todos("clientes")
        with closing(sqlite3.connect(self.ruta)) as externa, externa:
            externa.execute("UPDATE clientes SET zona = 'Comas' WHERE id = ?", (otro,))
        self.db.actualizar("clientes", self.id_, {"zona": "Ate"})
        self.assertEqual(self.db.uno("clientes", otro)["zona"], "Comas")
        self.assertEqual(self.db.uno("clientes", self.id_)["zona"], "Ate")

    def test_lote_incorpora_cambios_ajenos_en_cache_al_confirmar(self):
        otro = self.db.insertar("clientes", {"nombre": "Otra ficha", "zona": "Lince"})
        self.db.todos("clientes")
        with closing(sqlite3.connect(self.ruta)) as externa, externa:
            externa.execute("UPDATE clientes SET zona = 'Comas' WHERE id = ?", (otro,))
        with self.db.lote():
            self.db.actualizar("clientes", self.id_, {"zona": "Ate"})
        self.assertEqual(self.db.uno("clientes", otro)["zona"], "Comas")

    def test_lote_refresca_cache_antes_de_validar_y_reserva_escritura(self):
        with closing(sqlite3.connect(self.ruta)) as externa, externa:
            externa.execute("UPDATE clientes SET zona = 'Comas' WHERE id = ?", (self.id_,))
        with self.db.lote():
            self.assertEqual(self.db.uno("clientes", self.id_)["zona"], "Comas")
            with closing(sqlite3.connect(self.ruta, timeout=0.02)) as otra:
                with self.assertRaises(sqlite3.OperationalError):
                    otra.execute("UPDATE clientes SET zona = 'Simultánea' WHERE id = ?", (self.id_,))
                otra.rollback()
            self.db.actualizar("clientes", self.id_, {"zona": "Ate"})
        self.assertEqual(self.db.uno("clientes", self.id_)["zona"], "Ate")

    def test_restaurar_dentro_lote_no_confirma_escrituras_pendientes(self):
        copia = self.copia()
        with self.db.lote():
            nuevo = self.db.insertar("clientes", {"nombre": "Dentro del lote"})
            with self.assertRaises(ValueError):
                self.db.restaurar_desde(copia)
            self.assertEqual(self.db.uno("clientes", nuevo)["nombre"], "Dentro del lote")
        self.assertEqual(self.nombres_directos(), ["Cliente conservado", "Dentro del lote"])

    def test_copia_de_tabla_incompatible_no_reemplaza_la_base(self):
        copia = Path(self.temporal.name) / "incompatible.db"
        with closing(sqlite3.connect(copia)) as origen, origen:
            origen.execute("CREATE TABLE clientes (nombre TEXT)")
            origen.execute("INSERT INTO clientes VALUES ('Sin clave primaria')")
        with self.assertRaises(sqlite3.DatabaseError):
            self.db.restaurar_desde(copia)
        self.assertEqual(self.nombres_directos(), ["Cliente conservado"])

    def test_clave_que_no_genera_rowid_auto_no_se_acepta_como_copia(self):
        for esquema in ("id INTEGER, nombre TEXT, PRIMARY KEY(id, nombre)",
                        "id INTEGER PRIMARY KEY DESC, nombre TEXT"):
            with self.subTest(esquema=esquema):
                copia = Path(self.temporal.name) / "clave-incompatible.db"
                if copia.exists():
                    copia.unlink()
                with closing(sqlite3.connect(copia)) as origen, origen:
                    origen.execute(f"CREATE TABLE clientes ({esquema})")
                    origen.execute("INSERT INTO clientes(id,nombre) VALUES (1, 'No compatible')")
                with self.assertRaises(sqlite3.DatabaseError):
                    self.db.restaurar_desde(copia)
                self.assertEqual(self.nombres_directos(), ["Cliente conservado"])

    def test_inicio_fallido_cierra_la_conexion(self):
        real = sqlite3.connect(Path(self.temporal.name) / "inicio.db")
        proxy = mock.Mock(wraps=real)
        with mock.patch.object(self.agencia.sqlite3, "connect", return_value=proxy), \
                mock.patch.object(self.agencia.BaseDatos, "_migrar", side_effect=RuntimeError("No migrar")):
            with self.assertRaises(RuntimeError):
                self.agencia.BaseDatos("irrelevante.db")
        try:
            proxy.close.assert_called_once()
            with self.assertRaises(sqlite3.ProgrammingError):
                real.execute("SELECT 1")
        finally:
            real.close()

    def test_migracion_espera_a_otra_instancia_en_vez_de_upgrade_busy(self):
        antigua = Path(self.temporal.name) / "antigua.db"
        with closing(sqlite3.connect(antigua)) as origen, origen:
            origen.execute("CREATE TABLE clientes (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT)")
            origen.execute("INSERT INTO clientes(nombre) VALUES ('Histórico')")
        bloqueado = threading.Event()
        errores = []

        def escribir():
            try:
                with closing(sqlite3.connect(antigua)) as writer:
                    writer.execute("BEGIN IMMEDIATE")
                    writer.execute("UPDATE clientes SET nombre = 'Histórico actualizado'")
                    bloqueado.set()
                    time.sleep(0.15)
                    writer.commit()
            except BaseException as error:
                errores.append(error)
                bloqueado.set()

        hilo = threading.Thread(target=escribir)
        hilo.start()
        self.assertTrue(bloqueado.wait(2))
        try:
            migrada = self.agencia.BaseDatos(antigua)
            try:
                self.assertEqual(migrada.uno("clientes", 1)["nombre"], "Histórico actualizado")
            finally:
                migrada.con.close()
        finally:
            hilo.join(2)
        self.assertEqual(errores, [])


class Principal(CasosFiabilidad, unittest.TestCase):
    agencia = MODULOS["principal"]


if __name__ == "__main__":
    unittest.main()
