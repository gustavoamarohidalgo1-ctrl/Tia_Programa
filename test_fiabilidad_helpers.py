"""Conservación y cierres con datos ficticios; Windows se simula, no se ejecuta nativamente."""
import errno
import hashlib
import importlib.util
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock


IMPORTACION = tempfile.TemporaryDirectory(prefix="helpers-importacion-")
FUENTE = Path(__file__).resolve().parent / "agencia.py"
spec = importlib.util.spec_from_file_location("agencia_pruebas_helpers", FUENTE)
ag = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ag
with mock.patch.dict(os.environ, {"AGENCIA_DATOS": IMPORTACION.name}):
    sys.path.insert(0, str(FUENTE.parent))
    try:
        spec.loader.exec_module(ag)
    finally:
        sys.path.pop(0)


class RespaldosYRecursos(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory(prefix="helpers-fiabilidad-")
        self.root = Path(self.temporal.name)
        self.copias = self.root / "copias"
        self.copias.mkdir()

    def tearDown(self):
        self.temporal.cleanup()

    def base_areas(self, nombre="fuente.db", borrar=False):
        ruta = self.root / nombre
        db = ag.BaseDatos(ruta)
        try:
            if borrar:
                db.con.execute("DELETE FROM areas")
            else:
                db.con.execute("INSERT INTO areas(nombre,titulo,descripcion) VALUES (?,?,?)",
                    ("area-ficticia", "Área ficticia", "Configuración personalizada"))
            db.con.commit()
            areas = [tuple(fila) for fila in db.con.execute("SELECT * FROM areas ORDER BY id")]
        finally:
            db.con.close()
        return ruta, areas

    def publicar(self, fuente, nombre="agencia-auto-20260929-120000.db"):
        copia = self.copias / nombre
        ag.copiar_base(str(fuente), str(copia))
        return copia

    def test_error_de_desbloqueo_windows_simulado_cierra_descriptor(self):
        archivo = open(self.copias / ".copias.lock", "a+b")
        msvcrt = SimpleNamespace(LK_NBLCK=2, LK_UNLCK=0)
        def locking(fd, modo, longitud):
            if modo == msvcrt.LK_UNLCK:
                raise OSError("Fallo simulado al desbloquear")
        msvcrt.locking = locking
        try:
            with mock.patch.object(ag.sys, "platform", "win32"), \
                    mock.patch.dict(sys.modules, {"msvcrt": msvcrt}), \
                    mock.patch("builtins.open", return_value=archivo):
                with self.assertRaises(OSError):
                    with ag.cerrojo_carpeta(str(self.copias)):
                        pass
            self.assertTrue(archivo.closed)
        finally:
            archivo.close()

    def test_contencion_windows_simulada_tiene_limite_y_cierra_descriptor(self):
        archivo = open(self.copias / ".copias.lock", "a+b")
        msvcrt = SimpleNamespace(LK_NBLCK=2, LK_UNLCK=0,
            locking=mock.Mock(side_effect=PermissionError(errno.EACCES, "Archivo bloqueado")))
        inicio = time.monotonic()
        try:
            with mock.patch.object(ag.sys, "platform", "win32"), \
                    mock.patch.dict(sys.modules, {"msvcrt": msvcrt}), \
                    mock.patch("builtins.open", return_value=archivo):
                with self.assertRaises(TimeoutError):
                    with ag.cerrojo_carpeta(str(self.copias), limite=0):
                        self.fail("No puede entrar mientras otro proceso tiene el bloqueo")
            self.assertTrue(archivo.closed)
            self.assertLess(time.monotonic() - inicio, 1)
        finally:
            archivo.close()

    def test_copia_solo_con_areas_personalizadas_se_ofrece_sin_crear_destino(self):
        fuente, _ = self.base_areas()
        copia = self.publicar(fuente)
        vacia, _ = self.base_areas("vacia.db")
        db = ag.BaseDatos(vacia)
        try:
            db.con.execute("DELETE FROM areas WHERE nombre='area-ficticia'")
            db.con.commit()
        finally:
            db.con.close()
        vacia_copia = self.publicar(vacia, "agencia-auto-20260929-130000.db")
        os.utime(copia, (1_000_000_000, 1_000_000_000))
        os.utime(vacia_copia, (1_000_000_001, 1_000_000_001))
        destino = self.root / "inexistente.db"
        resultado = ag.buscar_restauracion(str(destino), [(str(self.copias), "Prueba")])
        self.assertIsNotNone(resultado)
        self.assertEqual(Path(resultado["ruta"]), copia)
        self.assertFalse(destino.exists())

    def test_recuperacion_preserva_areas_personalizadas_y_eliminadas(self):
        for borrar in (False, True):
            with self.subTest(areas_eliminadas=borrar):
                fuente, esperadas = self.base_areas(f"areas-{borrar}.db", borrar=borrar)
                copia = self.publicar(fuente, f"agencia-manual-20260929-12000{int(borrar)}.db")
                os.utime(copia, (1_000_000_000 + int(borrar), 1_000_000_000 + int(borrar)))
                destino = self.root / f"danada-{borrar}.db"
                original = b"Base ficticia danada " + str(borrar).encode()
                destino.write_bytes(original)
                aviso = ag.restaurar_si_esta_danada(str(destino), str(self.copias))
                self.assertTrue(aviso)
                con = sqlite3.connect(destino)
                try:
                    self.assertEqual(con.execute("SELECT * FROM areas ORDER BY id").fetchall(), esperadas)
                    self.assertEqual(con.execute("PRAGMA quick_check").fetchone()[0], "ok")
                finally:
                    con.close()
                self.assertTrue(any(p.read_bytes() == original for p in self.copias.glob("*danada*.db")))

    def test_copia_interrumpida_revierte_destino_existente(self):
        fuente = sqlite3.connect(self.root / "grande.db")
        destino = sqlite3.connect(self.root / "previa.db")
        try:
            fuente.execute("CREATE TABLE clientes(id INTEGER PRIMARY KEY,nombre TEXT)")
            fuente.executemany("INSERT INTO clientes(nombre) VALUES (?)", [("x" * 2000,)] * 2500)
            fuente.commit()
            destino.execute("CREATE TABLE anterior(id INTEGER PRIMARY KEY,valor TEXT)")
            destino.execute("INSERT INTO anterior(valor) VALUES ('Contenido previo')")
            destino.commit()
            with self.assertRaises(sqlite3.OperationalError):
                ag._copiar_sqlite(fuente, destino, limite=0)
            self.assertEqual(destino.execute("SELECT valor FROM anterior").fetchall(), [("Contenido previo",)])
            self.assertEqual(destino.execute("PRAGMA quick_check").fetchone()[0], "ok")
        finally:
            fuente.close()
            destino.close()

    def test_restauracion_fallida_no_publica_base_vacia(self):
        fuente, _ = self.base_areas()
        inicial = hashlib.sha256(fuente.read_bytes()).digest()
        destino = self.root / "nuevo.db"
        with mock.patch.object(ag, "_copiar_sqlite", side_effect=sqlite3.OperationalError("Copia interrumpida")):
            with self.assertRaises(sqlite3.OperationalError):
                ag.restaurar_archivo(str(fuente), str(destino))
        self.assertFalse(destino.exists())
        self.assertEqual(hashlib.sha256(fuente.read_bytes()).digest(), inicial)
        self.assertFalse(list(self.root.glob("*.tmp")))

    def test_recuperacion_fallida_no_mueve_la_base_danada(self):
        fuente, _ = self.base_areas()
        self.publicar(fuente)
        destino = self.root / "danada.db"
        original = "Archivo ficticio dañado".encode("utf-8")
        destino.write_bytes(original)
        with mock.patch.object(ag, "_copiar_sqlite", side_effect=sqlite3.OperationalError("Copia interrumpida")):
            with self.assertRaises(sqlite3.OperationalError):
                ag.restaurar_si_esta_danada(str(destino), str(self.copias))
        self.assertEqual(destino.read_bytes(), original)
        self.assertFalse(list(self.copias.glob("*danada*.db")))
        self.assertFalse(list(self.root.rglob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
