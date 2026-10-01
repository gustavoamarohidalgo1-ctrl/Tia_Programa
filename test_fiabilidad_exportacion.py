"""Exportaciones CSV completas y recuperación ante errores, con datos ficticios."""
import csv
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from contextlib import closing

if not os.environ.get("AGENCIA_DATOS"):      # nunca la carpeta de datos real, aunque se pruebe desde el proyecto
    os.environ["AGENCIA_DATOS"] = tempfile.mkdtemp(prefix="agencia-pruebas-")

import agencia


class FiabilidadExportacionTest(unittest.TestCase):
    NOMBRES = ("Clientes.csv", "Trabajadoras.csv", "Asignaciones.csv", "Areas.csv")

    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory(prefix="csv-ficticios-")
        self.carpeta = Path(self.temporal.name)
        self.ruta = self.carpeta / "agencia.db"
        self.destino = self.carpeta / "Datos legibles"
        self.db = agencia.BaseDatos(str(self.ruta))
        self.cli = self.db.insertar("clientes", {"nombre": "Cliente actual", "notas": "=1+1"})
        self.trab = self.db.insertar("trabajadoras", {"nombre": "Trabajadora actual", "notas": " @SUM(1,2)"})
        self.db.insertar("colocaciones", {"cliente_id": str(self.cli), "trabajadora_id": str(self.trab),
                                          "estado": "Activa", "comision": "500"})
        self.originales = {n: ("Exportación anterior de " + n + "\r\n").encode("utf-8") for n in self.NOMBRES}

    def tearDown(self):
        self.db.con.close()
        self.temporal.cleanup()

    def preparar_anteriores(self):
        self.destino.mkdir()
        for nombre, datos in self.originales.items():
            (self.destino / nombre).write_bytes(datos)
        (self.destino / "Notas propias.txt").write_bytes(b"Documento ajeno a la exportacion")
        (self.destino / "Adjuntos").mkdir()
        (self.destino / "Adjuntos" / "documento.txt").write_bytes(b"Adjunto ajeno")

    def verificar_anteriores(self):
        for nombre, datos in self.originales.items():
            self.assertEqual((self.destino / nombre).read_bytes(), datos)
        self.assertEqual((self.destino / "Notas propias.txt").read_bytes(), b"Documento ajeno a la exportacion")
        self.assertEqual((self.destino / "Adjuntos" / "documento.txt").read_bytes(), b"Adjunto ajeno")
        self.assertEqual(sorted(p.name for p in self.destino.iterdir()), sorted((*self.NOMBRES, "Notas propias.txt", "Adjuntos")))

    def leer(self, nombre):
        with (self.destino / nombre).open(encoding="utf-8-sig", newline="") as archivo:
            return list(csv.DictReader(archivo))

    def exportar(self):
        agencia.exportar_legible(str(self.ruta), str(self.destino))

    def test_exportacion_completa_bom_neutralizacion_y_archivos_ajenos(self):
        self.preparar_anteriores()
        fuente = hashlib.sha256(self.ruta.read_bytes()).hexdigest()
        self.exportar()
        for nombre in self.NOMBRES:
            self.assertTrue((self.destino / nombre).read_bytes().startswith(b"\xef\xbb\xbf"))
            self.assertNotEqual((self.destino / nombre).read_bytes(), self.originales[nombre])
        self.assertEqual(self.leer("Clientes.csv")[0]["nombre"], "Cliente actual")
        self.assertEqual(self.leer("Clientes.csv")[0]["notas"], "'=1+1")
        self.assertEqual(self.leer("Trabajadoras.csv")[0]["notas"], "' @SUM(1,2)")
        self.assertEqual((self.destino / "Notas propias.txt").read_bytes(), b"Documento ajeno a la exportacion")
        self.assertEqual((self.destino / "Adjuntos" / "documento.txt").read_bytes(), b"Adjunto ajeno")
        self.assertFalse(list(self.destino.glob(".exportacion-csv-*")))
        self.assertEqual(hashlib.sha256(self.ruta.read_bytes()).hexdigest(), fuente)

    def test_error_preparando_segunda_tabla_no_publica_primera(self):
        self.preparar_anteriores()
        original = agencia.celda_csv
        def convertir(valor):
            if valor == "Trabajadora actual":
                raise OSError("fallo de lectura o escritura")
            return original(valor)
        with patch.object(agencia, "celda_csv", side_effect=convertir):
            with self.assertRaisesRegex(OSError, "fallo de lectura"):
                self.exportar()
        self.verificar_anteriores()

    def test_error_de_preparacion_en_destino_vacio_no_deja_csv_parcial(self):
        original = agencia.celda_csv
        def convertir(valor):
            if valor == "Trabajadora actual":
                raise OSError("fallo de preparación")
            return original(valor)
        with patch.object(agencia, "celda_csv", side_effect=convertir):
            with self.assertRaises(OSError):
                self.exportar()
        self.assertEqual(list(self.destino.iterdir()), [])

    def test_cuatro_csv_y_copias_previas_estan_completos_antes_de_publicar(self):
        self.preparar_anteriores()
        reemplazar = agencia.os.replace
        observado = []
        def publicar(origen, destino):
            if Path(origen).parent.name == "nuevos" and not observado:
                observado.append(True)
                nuevos = Path(origen).parent
                resguardo = nuevos.parent / "anteriores"
                self.assertEqual(sorted(p.name for p in nuevos.iterdir()), sorted(self.NOMBRES))
                for nombre in self.NOMBRES:
                    self.assertTrue((nuevos / nombre).read_bytes().startswith(b"\xef\xbb\xbf"))
                    self.assertEqual((resguardo / nombre).read_bytes(), self.originales[nombre])
                    self.assertEqual((self.destino / nombre).read_bytes(), self.originales[nombre])
            return reemplazar(origen, destino)
        with patch.object(agencia.os, "replace", side_effect=publicar):
            self.exportar()
        self.assertEqual(observado, [True])

    def test_error_publicando_cualquier_csv_revierte_conjunto_entero(self):
        self.preparar_anteriores()
        reemplazar = agencia.os.replace
        for fallido in self.NOMBRES:
            with self.subTest(fallido=fallido):
                def publicar(origen, destino):
                    if Path(origen).parent.name == "nuevos" and Path(destino).name == fallido:
                        raise OSError("fallo de publicación")
                    return reemplazar(origen, destino)
                with patch.object(agencia.os, "replace", side_effect=publicar):
                    with self.assertRaisesRegex(OSError, "fallo de publicación"):
                        self.exportar()
                self.verificar_anteriores()

    def test_error_despues_de_renombrar_tambien_revierte(self):
        self.preparar_anteriores()
        reemplazar = agencia.os.replace
        def publicar(origen, destino):
            resultado = reemplazar(origen, destino)
            if Path(origen).parent.name == "nuevos" and Path(destino).name == "Trabajadoras.csv":
                raise OSError("fallo después de publicar")
            return resultado
        with patch.object(agencia.os, "replace", side_effect=publicar):
            with self.assertRaises(OSError):
                self.exportar()
        self.verificar_anteriores()

    def test_error_publicando_en_carpeta_vacia_elimina_solo_csv_nuevos(self):
        self.destino.mkdir()
        (self.destino / "Notas.txt").write_bytes(b"Archivo ajeno")
        reemplazar = agencia.os.replace
        def publicar(origen, destino):
            if Path(origen).parent.name == "nuevos" and Path(destino).name == "Asignaciones.csv":
                raise OSError("sin espacio")
            return reemplazar(origen, destino)
        with patch.object(agencia.os, "replace", side_effect=publicar):
            with self.assertRaises(OSError):
                self.exportar()
        self.assertEqual([p.name for p in self.destino.iterdir()], ["Notas.txt"])
        self.assertEqual((self.destino / "Notas.txt").read_bytes(), b"Archivo ajeno")

    def test_error_resguardando_anteriores_no_cambia_la_exportacion(self):
        self.preparar_anteriores()
        copiar = shutil.copy2
        def copia(origen, destino, **kwargs):
            if Path(destino).parent.name == "anteriores" and Path(destino).name == "Trabajadoras.csv":
                raise OSError("fallo de resguardo")
            return copiar(origen, destino, **kwargs)
        with patch.object(shutil, "copy2", side_effect=copia):
            with self.assertRaisesRegex(OSError, "fallo de resguardo"):
                self.exportar()
        self.verificar_anteriores()

    def test_reversion_fallida_conserva_todos_anteriores_y_reporta_ruta(self):
        self.preparar_anteriores()
        reemplazar = agencia.os.replace
        def publicar(origen, destino):
            padre, nombre = Path(origen).parent.name, Path(destino).name
            if padre == "nuevos" and nombre == "Asignaciones.csv":
                raise OSError("fallo publicando")
            if padre == "restauracion" and nombre == "Clientes.csv":
                raise OSError("fallo recuperando")
            return reemplazar(origen, destino)
        with patch.object(agencia.os, "replace", side_effect=publicar):
            with self.assertRaisesRegex(OSError, "recuperación fallaron") as capturado:
                self.exportar()
        resguardo = Path(capturado.exception._resguardo_csv)
        self.assertTrue(resguardo.is_dir())
        self.assertIn(str(resguardo), str(capturado.exception))
        for nombre, datos in self.originales.items():
            self.assertEqual((resguardo / nombre).read_bytes(), datos)
        manifest = json.loads((resguardo / "restauracion.json").read_text(encoding="utf-8"))
        self.assertEqual(set(manifest["anteriores"]), set(self.NOMBRES))
        self.assertEqual(manifest["ausentes"], [])
        self.assertEqual((self.destino / "Notas propias.txt").read_bytes(), b"Documento ajeno a la exportacion")
        for nombre in self.NOMBRES[1:]:
            self.assertEqual((self.destino / nombre).read_bytes(), self.originales[nombre])

    def test_resguardo_permanece_si_falla_borrar_nuevo_csv_durante_reversion(self):
        reemplazar, quitar = agencia.os.replace, agencia.os.unlink
        def publicar(origen, destino):
            if Path(origen).parent.name == "nuevos" and Path(destino).name == "Trabajadoras.csv":
                raise OSError("fallo publicando")
            return reemplazar(origen, destino)
        def borrar(destino, *args, **kwargs):
            if Path(destino).name == "Clientes.csv":
                raise OSError("fallo quitando CSV parcial")
            return quitar(destino, *args, **kwargs)
        with patch.object(agencia.os, "replace", side_effect=publicar), patch.object(agencia.os, "unlink", side_effect=borrar):
            with self.assertRaises(OSError) as capturado:
                self.exportar()
        resguardo = Path(capturado.exception._resguardo_csv)
        manifest = json.loads((resguardo / "restauracion.json").read_text(encoding="utf-8"))
        self.assertEqual(set(manifest["ausentes"]), set(self.NOMBRES))
        self.assertEqual(manifest["anteriores"], [])
        self.assertTrue((self.destino / "Clientes.csv").exists())
        self.assertFalse((self.destino / "Trabajadoras.csv").exists())

    def test_fuente_ausente_no_se_crea_ni_cambia_csv_anteriores(self):
        self.preparar_anteriores()
        fuente = self.carpeta / "ausente.db"
        with self.assertRaises(sqlite3.Error):
            agencia.exportar_legible(str(fuente), str(self.destino))
        self.assertFalse(fuente.exists())
        self.verificar_anteriores()

    def test_fuente_antigua_sin_tablas_exporta_vacios_en_lugar_de_datos_previos(self):
        self.preparar_anteriores()
        antigua = self.carpeta / "antigua.db"
        with closing(sqlite3.connect(antigua)) as con, con:
            con.execute("CREATE TABLE clientes (id INTEGER PRIMARY KEY, nombre TEXT)")
            con.execute("INSERT INTO clientes VALUES (1, 'Cliente antiguo')")
        agencia.exportar_legible(str(antigua), str(self.destino))
        self.assertEqual(self.leer("Clientes.csv")[0]["nombre"], "Cliente antiguo")
        for nombre in self.NOMBRES[1:]:
            self.assertEqual(self.leer(nombre), [])
            self.assertTrue((self.destino / nombre).read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_snapshot_sqlite_conserva_misma_generacion_entre_tablas(self):
        self.db.con.execute("PRAGMA journal_mode=WAL")
        self.db.con.commit()
        self.db.actualizar("clientes", self.cli, {"nombre": "Cliente actual"})  # crea WAL/SHM para la conexión RO
        original = agencia.celda_csv
        cambiado = False
        def convertir(valor):
            nonlocal cambiado
            if valor == "Cliente actual" and not cambiado:
                cambiado = True
                with closing(sqlite3.connect(self.ruta)) as otra, otra:
                    otra.execute("UPDATE clientes SET nombre='Cliente posterior'")
                    otra.execute("UPDATE trabajadoras SET nombre='Trabajadora posterior'")
            return original(valor)
        with patch.object(agencia, "celda_csv", side_effect=convertir):
            self.exportar()
        self.assertTrue(cambiado)
        self.assertEqual(self.leer("Clientes.csv")[0]["nombre"], "Cliente actual")
        self.assertEqual(self.leer("Trabajadoras.csv")[0]["nombre"], "Trabajadora actual")
        self.db.cambio_externo()
        self.assertEqual(self.db.uno("trabajadoras", self.trab)["nombre"], "Trabajadora posterior")

    def test_db_de_respaldo_se_conserva_aunque_exportar_csv_falle(self):
        externa = self.carpeta / "respaldo externo"
        with patch.object(agencia, "celda_csv", side_effect=OSError("fallo de exportación")):
            with self.assertRaises(OSError):
                agencia.copia_externa(str(self.ruta), str(externa), datetime(2026, 9, 29))
        copia = externa / "agencia-20260929.db"
        self.assertTrue(copia.is_file())
        with closing(agencia.conexion_lectura(str(copia))) as con:
            self.assertEqual(con.execute("SELECT nombre FROM clientes").fetchone()[0], "Cliente actual")
        self.assertEqual(list((externa / "Datos legibles").iterdir()), [])

    def test_reversion_restaura_enlace_simbolico_sin_modificar_archivo_enlazado(self):
        self.preparar_anteriores()
        destino_original = self.carpeta / "archivo enlazado.csv"
        destino_original.write_bytes(self.originales["Clientes.csv"])
        (self.destino / "Clientes.csv").unlink()
        try:
            os.symlink(destino_original, self.destino / "Clientes.csv")
        except (OSError, NotImplementedError):
            self.skipTest("El sistema no permite crear enlaces simbólicos.")
        reemplazar = agencia.os.replace
        def publicar(origen, destino):
            if Path(origen).parent.name == "nuevos" and Path(destino).name == "Trabajadoras.csv":
                raise OSError("fallo publicando")
            return reemplazar(origen, destino)
        with patch.object(agencia.os, "replace", side_effect=publicar):
            with self.assertRaises(OSError):
                self.exportar()
        self.assertTrue((self.destino / "Clientes.csv").is_symlink())
        self.assertEqual(destino_original.read_bytes(), self.originales["Clientes.csv"])
        self.verificar_anteriores()


if __name__ == "__main__":
    unittest.main()
