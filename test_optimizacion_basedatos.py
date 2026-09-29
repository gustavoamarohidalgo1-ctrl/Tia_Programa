"""Regresiones de lectura puntual, instantáneas y transacciones de Servicio Exclusivo.

Todas las conexiones y los datos de importación se crean en carpetas temporales.
No se abre la base de producción ni se crean ventanas.
"""
import importlib.util
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock


RAIZ = Path(__file__).resolve().parent
IMPORTACION = tempfile.TemporaryDirectory(prefix="agencias-importacion-pruebas-")


def cargar_agencia(nombre, ruta):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = modulo
    with mock.patch.dict(os.environ, {"AGENCIA_DATOS": IMPORTACION.name}):
        sys.path.insert(0, str(ruta.parent))
        try:
            spec.loader.exec_module(modulo)
        finally:
            sys.path.pop(0)
    return modulo


MODULOS = {
    "principal": cargar_agencia("agencia_opt_principal", RAIZ / "agencia.py"),
}


class CasosBaseDatos:
    agencia = None

    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory(prefix="agencia-base-pruebas-")
        self.ruta = Path(self.temporal.name) / "agencia.db"
        self.db = self.agencia.BaseDatos(self.ruta)

    def tearDown(self):
        self.db.con.close()
        self.temporal.cleanup()

    def llenar(self, cantidad=500):
        self.db.con.executemany("INSERT INTO clientes(nombre, zona) VALUES (?, ?)",
                                [(f"Cliente {i}", "Lince") for i in range(cantidad)])
        self.db.con.commit()

    def test_lectura_puntual_no_consulta_tabla_completa_y_se_reutiliza(self):
        self.llenar()
        consultas = []
        self.db.con.set_trace_callback(consultas.append)
        primera = self.db.uno("clientes", "7")
        self.assertEqual(primera["nombre"], "Cliente 6")
        self.assertIs(self.db.uno("clientes", 7), primera)
        lecturas = [sql for sql in consultas if sql.startswith("SELECT")]
        self.assertEqual(len(lecturas), 1)
        self.assertIn("WHERE id = 7", lecturas[0])
        self.assertNotIn("ORDER BY", lecturas[0])
        self.assertIs(next(f for f in self.db.todos("clientes") if f["id"] == 7), primera)

    def test_id_invalido_no_dispara_lecturas(self):
        consultas = []
        self.db.con.set_trace_callback(consultas.append)
        for id_ in (None, "", "xyz", float("inf"), float("nan"), 1 << 63, -(1 << 63) - 1, 1 << 200):
            self.assertIsNone(self.db.uno("clientes", id_))
        self.assertEqual(consultas, [])

    def test_cache_individual_refleja_edicion_y_borrado(self):
        id_ = self.db.insertar("clientes", {"nombre": "Ana", "zona": "Lince"})
        antigua = self.db.uno("clientes", id_)
        self.db.actualizar("clientes", str(id_), {"zona": 123})
        nueva = self.db.uno("clientes", id_)
        self.assertEqual(nueva["zona"], "123")
        self.assertEqual(antigua["zona"], "Lince")
        self.assertIsNot(nueva, antigua)
        self.db.eliminar("clientes", str(id_))
        self.assertIsNone(self.db.uno("clientes", id_))
        self.assertEqual(self.db.todos("clientes"), [])

    def test_lote_mixto_conserva_lista_anterior_y_orden_sin_releer_tabla(self):
        self.llenar(4)
        antes = self.db.todos("clientes")
        consultas = []
        self.db.con.set_trace_callback(consultas.append)
        with self.db.lote():
            self.db.actualizar("clientes", 2, {"zona": "Ate"})
            descartado = self.db.insertar("clientes", {"nombre": "Temporal"})
            self.db.eliminar("clientes", 1)
            self.db.actualizar("clientes", descartado, {"zona": "Comas"})
            self.db.eliminar("clientes", descartado)
            ultimo = self.db.insertar("clientes", {"nombre": "Nueva"})
            self.assertEqual(self.db.uno("clientes", 2)["zona"], "Ate")
        despues = self.db.todos("clientes")
        self.assertEqual([f["id"] for f in antes], [4, 3, 2, 1])
        self.assertEqual(antes[2]["zona"], "Lince")
        self.assertEqual([f["id"] for f in despues], [ultimo, 4, 3, 2])
        self.assertIsNot(despues, antes)
        self.assertIs(self.db.todos("clientes"), despues)
        self.assertFalse(any("ORDER BY id DESC" in sql for sql in consultas))
        for fila in despues:
            self.assertIs(self.db.uno("clientes", fila["id"]), fila)

    def test_id_manual_inferior_se_ordena_correctamente(self):
        self.llenar(3)
        self.db.todos("clientes")
        self.db.insertar("clientes", {"id": -4, "nombre": "Manual"})
        self.assertEqual([f["id"] for f in self.db.todos("clientes")], [3, 2, 1, -4])

    def test_invalidacion_directa_de_cache_no_reutiliza_filas_obsoletas(self):
        id_ = self.db.insertar("clientes", {"nombre": "Ana"})
        self.db.uno("clientes", id_)
        self.db.con.execute("UPDATE clientes SET nombre = 'Nuevo' WHERE id = ?", (id_,))
        self.db.con.commit()
        self.db._memoria.clear()
        self.assertEqual(self.db.todos("clientes")[0]["nombre"], "Nuevo")
        self.assertEqual(self.db.uno("clientes", id_)["nombre"], "Nuevo")

    def test_cambio_externo_invalida_cache_individual_y_listas_pendientes(self):
        id_ = self.db.insertar("clientes", {"nombre": "Ana"})
        self.db.uno("clientes", id_)
        with closing(sqlite3.connect(self.ruta)) as otra, otra:
            otra.execute("UPDATE clientes SET nombre = 'Externa' WHERE id = ?", (id_,))
        self.assertTrue(self.db.cambio_externo())
        self.assertEqual(self.db.uno("clientes", id_)["nombre"], "Externa")
        self.db.todos("clientes")
        self.db.actualizar("clientes", id_, {"zona": "Ate"})
        with closing(sqlite3.connect(self.ruta)) as otra, otra:
            otra.execute("DELETE FROM clientes WHERE id = ?", (id_,))
        self.assertTrue(self.db.cambio_externo())
        self.assertEqual(self.db.todos("clientes"), [])
        self.assertIsNone(self.db.uno("clientes", id_))

    def test_rollback_anidado_reconstruye_lecturas_y_conserva_lote_externo(self):
        with self.db.lote():
            id_ = self.db.insertar("clientes", {"nombre": "Externa"})
            self.db.uno("clientes", id_)
            with self.assertRaises(RuntimeError):
                with self.db.lote():
                    self.db.actualizar("clientes", id_, {"nombre": "Interna"})
                    self.db.todos("clientes")
                    raise RuntimeError("Revertir sólo el lote interior")
            self.assertEqual(self.db.uno("clientes", id_)["nombre"], "Externa")
            self.db.actualizar("clientes", id_, {"zona": "Lince"})
        self.assertEqual(self.db.todos("clientes")[0]["nombre"], "Externa")
        self.assertEqual(self.db.todos("clientes")[0]["zona"], "Lince")

    def _fallo_de_confirmacion(self, en_lote):
        id_ = self.db.insertar("clientes", {"nombre": "Confirmado"})
        self.db.todos("clientes")
        revision = self.db.revision("clientes")
        self.db.con.execute("PRAGMA busy_timeout = 25")
        lector = sqlite3.connect(self.ruta)
        try:
            lector.execute("BEGIN")
            lector.execute("SELECT * FROM clientes").fetchall()
            with self.assertRaises(sqlite3.OperationalError):
                if en_lote:
                    with self.db.lote():
                        self.db.actualizar("clientes", id_, {"nombre": "No confirmado"})
                else:
                    self.db.actualizar("clientes", id_, {"nombre": "No confirmado"})
            self.assertFalse(self.db.con.in_transaction)
            self.assertEqual(self.db.uno("clientes", id_)["nombre"], "Confirmado")
            cambios = self.db.cambios_desde("clientes", revision)
            self.assertTrue(cambios is None or ("todo", None) in cambios)
        finally:
            lector.rollback()
            lector.close()
        self.db.insertar("trabajadoras", {"nombre": "Rosa"})
        with closing(sqlite3.connect(self.ruta)) as otra, otra:
            self.assertEqual(otra.execute("SELECT nombre FROM clientes").fetchone()[0], "Confirmado")

    def test_commit_fallido_no_publica_ni_confirma_cambios_mas_tarde(self):
        self._fallo_de_confirmacion(en_lote=False)

    def test_release_fallido_revierte_lote_y_cache(self):
        self._fallo_de_confirmacion(en_lote=True)

    def test_restauracion_invalida_no_crea_origen_ni_reemplaza_datos(self):
        self.db.insertar("clientes", {"nombre": "Conservar"})
        self.db.uno("clientes", 1)
        ausente = Path(self.temporal.name) / "no-existe.db"
        with self.assertRaises(sqlite3.Error):
            self.db.restaurar_desde(ausente)
        self.assertFalse(ausente.exists())
        self.assertEqual(self.db.uno("clientes", 1)["nombre"], "Conservar")

    def test_restauracion_descarta_todas_las_instantaneas_y_cache_individual(self):
        self.db.insertar("clientes", {"nombre": "Anterior"})
        self.db.uno("clientes", 1)
        copia = Path(self.temporal.name) / "copia.db"
        otra = self.agencia.BaseDatos(copia)
        try:
            otra.insertar("clientes", {"nombre": "Restaurado"})
        finally:
            otra.con.close()
        self.db.restaurar_desde(copia)
        self.assertEqual(self.db.uno("clientes", 1)["nombre"], "Restaurado")
        self.assertIs(self.db.todos("clientes")[0], self.db.uno("clientes", 1))


class Principal(CasosBaseDatos, unittest.TestCase):
    agencia = MODULOS["principal"]


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        IMPORTACION.cleanup()
