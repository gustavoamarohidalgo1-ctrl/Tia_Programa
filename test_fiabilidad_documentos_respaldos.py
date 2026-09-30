"""Conservación documental y copias: datos ficticios y fallos reales, sin producción."""
import csv
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import agencia


class ConservacionFinalTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.ruta = self.root / "datos.db"
        self.db = agencia.BaseDatos(str(self.ruta))
        self.cli = self.db.insertar("clientes", {"nombre": "Cliente ficticio", "telefono": "5551001",
            "dni": "00012345", "ocupacion": "Ocupación original", "tipo_servicio": list(agencia.AREAS)[0]})
        self.trab = self.db.insertar("trabajadoras", {"nombre": "Trabajadora ficticia", "telefono": "5551002"})
        self.id = self.db.insertar("colocaciones", {"cliente_id": str(self.cli), "trabajadora_id": str(self.trab),
            "estado": "En proceso", "fecha_enlace": "01/10/2026", "fecha_contrato": "01/10/2026",
            "comision": "300.00", "sueldo_acordado": "1500", "garantia": "Sí", "meses_garantia": "2",
            "puesto": "Puesto original", "modalidad": "Cama afuera", "descanso": "Domingo"})
        self.app = agencia.App.__new__(agencia.App)
        self.app.db = self.db
        self.app.root = Mock()
        self.app.refrescar_todo = Mock()
        self.app.iniciar_contratos_firmados = Mock()
        self.pagina = agencia.PaginaContratos.__new__(agencia.PaginaContratos)
        self.pagina.db = self.db
        self.pagina.app = self.app
        self.avisos = patch.object(agencia.messagebox, "showwarning")
        self.avisos.start()
        self.addCleanup(self.avisos.stop)

    def tearDown(self):
        self.db.con.close()
        self.temp.cleanup()

    def firmas(self, nombre="Firma ficticia"):
        return {k: json.dumps({"tipo": "nombre", "texto": nombre + " " + k})
            for k in ("firma_cliente", "firma_trabajadora", "firma_agencia")}

    def abrir_firma(self):
        recibido = {}
        with patch.object(agencia, "DialogoFirmas", side_effect=lambda *args: recibido.update(guardar=args[-1])), \
                patch.object(agencia.messagebox, "askyesno", return_value=True):
            self.pagina.firmar(self.db.uno("colocaciones", self.id))
        self.assertIn("guardar", recibido)
        return recibido["guardar"]

    def firmar(self):
        guardar = self.abrir_firma()
        with patch.object(agencia.messagebox, "askyesno", return_value=False):
            self.assertTrue(guardar(self.firmas()))
        return self.db.uno("colocaciones", self.id)

    def abrir_edicion(self):
        recibido = {}
        def dialogo(master, numero, valores, guardar, **kwargs):
            recibido.update(valores=dict(valores), guardar=guardar)
        with patch.object(agencia, "DialogoContrato", side_effect=dialogo):
            self.pagina.editar_datos(self.db.uno("colocaciones", self.id))
        return recibido

    def test_documento_firmado_permanece_inmutable_tras_editar_personas_y_condiciones(self):
        c = self.firmar()
        original = c["contrato_html"]
        self.assertIn("Firma ficticia", original)
        self.db.actualizar("clientes", self.cli, {"nombre": "Otra persona", "direccion": "Otra dirección"})
        self.db.actualizar("trabajadoras", self.trab, {"nombre": "Nombre modificado"})
        self.db.actualizar("colocaciones", self.id, {"comision": "900.00", "puesto": "Puesto modificado"})
        actualizado = self.db.uno("colocaciones", self.id)
        self.assertEqual(agencia.html_contrato(actualizado, {}, {}), original)
        self.assertEqual(actualizado["contrato_html"], original)
        self.assertIn("window.print()", agencia.html_contrato(actualizado, {}, {}, imprimir=True))

    def test_firma_rechaza_cambio_de_comision_en_otra_conexion(self):
        guardar = self.abrir_firma()
        otra = sqlite3.connect(self.ruta)
        with otra:
            otra.execute("UPDATE colocaciones SET comision='500.00' WHERE id=?", (self.id,))
        otra.close()
        self.assertFalse(guardar(self.firmas()))
        fila = agencia.leer_registro_actual(self.db, "colocaciones", self.id)
        self.assertEqual(fila["comision"], "500.00")
        self.assertEqual(fila["contrato_firmado"], "")
        self.assertEqual(fila["contrato_html"], "")

    def test_firma_rechaza_personas_editadas_mientras_se_firma(self):
        guardar = self.abrir_firma()
        self.db.actualizar("clientes", self.cli, {"dni": "87654321"})
        self.assertFalse(guardar(self.firmas()))
        self.assertEqual(self.db.uno("colocaciones", self.id)["contrato_firmado"], "")

    def test_firma_rechaza_asignacion_eliminada_sin_cerrar_dialogo(self):
        guardar = self.abrir_firma()
        self.db.eliminar("colocaciones", self.id)
        self.assertFalse(guardar(self.firmas()))
        self.assertIsNone(self.db.uno("colocaciones", self.id))

    def test_firma_invalida_no_se_persiste(self):
        guardar = self.abrir_firma()
        firmas = self.firmas()
        firmas["firma_cliente"] = '{"tipo":"nombre","texto":"   "}'
        self.assertFalse(guardar(firmas))
        self.assertEqual(self.db.uno("colocaciones", self.id)["firma_cliente"], "")

    def test_generacion_fallida_revierte_firmas_y_documento(self):
        guardar = self.abrir_firma()
        with patch.object(agencia, "html_contrato", side_effect=OSError("error simulado")):
            with self.assertRaises(OSError):
                guardar(self.firmas())
        fila = self.db.uno("colocaciones", self.id)
        self.assertEqual(fila["contrato_firmado"], "")
        self.assertEqual(fila["firma_cliente"], "")
        self.assertEqual(fila["contrato_html"], "")

    def test_refirma_explicitamente_actualiza_ejemplar(self):
        self.firmar()
        self.db.actualizar("colocaciones", self.id, {"comision": "432.10"})
        guardar = self.abrir_firma()
        with patch.object(agencia.messagebox, "askyesno", return_value=False):
            self.assertTrue(guardar(self.firmas("Segunda firma")))
        self.assertIn("432.10", self.db.uno("colocaciones", self.id)["contrato_html"])
        self.assertIn("Segunda firma", self.db.uno("colocaciones", self.id)["contrato_html"])

    def test_edicion_concurrente_no_sobrescribe_datos(self):
        edicion = self.abrir_edicion()
        self.db.actualizar("colocaciones", self.id, {"comision": "400.00"})
        datos = dict(edicion["valores"], puesto="Nuevo puesto local")
        self.assertFalse(edicion["guardar"](datos))
        fila = self.db.uno("colocaciones", self.id)
        self.assertEqual(fila["comision"], "400.00")
        self.assertEqual(fila["puesto"], "Puesto original")

    def test_edicion_cliente_concurrente_conserva_ocupacion(self):
        edicion = self.abrir_edicion()
        self.db.actualizar("clientes", self.cli, {"ocupacion": "Ocupación nueva externa"})
        self.assertFalse(edicion["guardar"](dict(edicion["valores"], puesto="Otro puesto")))
        self.assertEqual(self.db.uno("clientes", self.cli)["ocupacion"], "Ocupación nueva externa")

    def test_edicion_no_cambia_importe_ya_cobrado(self):
        self.db.actualizar("colocaciones", self.id, {"comision_pagada": "1", "fecha_pago": "01/10/2026"})
        edicion = self.abrir_edicion()
        self.assertFalse(edicion["guardar"](dict(edicion["valores"], comision="900.00")))
        fila = self.db.uno("colocaciones", self.id)
        self.assertEqual(fila["comision"], "300.00")
        self.assertEqual(fila["comision_pagada"], "1")
        self.assertEqual(fila["fecha_pago"], "01/10/2026")

    def test_edicion_operativa_conserva_ejemplar_firmado(self):
        firmado = self.firmar()["contrato_html"]
        edicion = self.abrir_edicion()
        self.assertTrue(edicion["guardar"](dict(edicion["valores"], puesto="Puesto revisado")))
        fila = self.db.uno("colocaciones", self.id)
        self.assertEqual(fila["puesto"], "Puesto revisado")
        self.assertEqual(fila["contrato_html"], firmado)

    def test_firma_migrada_se_congela_antes_de_editar_fichas(self):
        self.db.actualizar("colocaciones", self.id, dict(self.firmas(), contrato_firmado="1",
            fecha_firma="01/10/2026 12:00"))
        original = agencia.html_contrato(self.db.uno("colocaciones", self.id),
            self.db.uno("clientes", self.cli), self.db.uno("trabajadoras", self.trab))
        self.db.con.close()
        self.db = agencia.BaseDatos(str(self.ruta))
        self.assertEqual(self.db.uno("colocaciones", self.id)["contrato_html"], original)
        self.db.actualizar("clientes", self.cli, {"nombre": "Nuevo nombre"})
        self.assertEqual(agencia.html_contrato(self.db.uno("colocaciones", self.id), {}, {}), original)

    def test_impresion_firmada_funciona_con_personas_ausentes(self):
        c = self.firmar()
        self.db.eliminar("clientes", self.cli)
        self.db.eliminar("trabajadoras", self.trab)
        with patch.object(agencia, "CARPETA_CONTRATOS", str(self.root)), patch("webbrowser.open") as navegador, \
                patch.object(agencia.os, "startfile", create=True) as windows:   # en Windows se abre con os.startfile
            self.pagina.imprimir_contrato(c)
        self.assertEqual(navegador.call_count + windows.call_count, 1)
        self.assertIn("Cliente ficticio", (self.root / f"contrato_{self.id}.html").read_text(encoding="utf-8"))

    def test_impresion_fallida_no_trunca_documento_anterior(self):
        c = self.firmar()
        ruta = self.root / f"contrato_{self.id}.html"
        ruta.write_text("Documento anterior")
        with patch.object(agencia, "CARPETA_CONTRATOS", str(self.root)), \
                patch.object(agencia.os, "replace", side_effect=OSError("sin permiso")):
            with self.assertRaises(OSError):
                self.pagina.imprimir_contrato(c)
        self.assertEqual(ruta.read_text(), "Documento anterior")
        self.assertFalse(list(self.root.glob("*.tmp")))

    def test_dialogo_de_firma_permanece_abierto_si_guardado_rechazado(self):
        dialogo = agencia.DialogoFirmas.__new__(agencia.DialogoFirmas)
        dialogo.paneles = {k: Mock(vacia=Mock(return_value=False), datos=Mock(return_value="firma"))
            for k in ("firma_cliente", "firma_trabajadora", "firma_agencia")}
        dialogo.al_guardar = Mock(return_value=False)
        dialogo.destroy = Mock()
        dialogo.guardar()
        dialogo.destroy.assert_not_called()

    def test_borrador_fallido_conserva_formulario_y_avisa(self):
        self.app.clientes = SimpleNamespace(tabla="clientes", borrador={"nombre": "Pendiente"})
        self.app.trabajadoras = SimpleNamespace(tabla="trabajadoras", borrador=None)
        with patch.object(agencia, "DB_PATH", str(self.ruta)), \
                patch.object(agencia, "archivo_atomico", side_effect=PermissionError("sin permiso")):
            self.assertFalse(self.app.guardar_borradores())
        self.assertEqual(self.app.clientes.borrador["nombre"], "Pendiente")
        pagina = agencia.Pagina.__new__(agencia.Pagina)
        pagina.id_actual = None
        pagina.cambios_sin_guardar = Mock(return_value=True)
        pagina.guardar = Mock(return_value=False)
        pagina.guardar_borrador = Mock(return_value=False)
        self.assertFalse(pagina.resolver_cambios())

    def test_configuracion_fallida_no_reemplaza_archivo_bueno(self):
        ruta = self.root / "configuracion.json"
        ruta.write_text('{"copia_adicional":"USB original"}')
        with patch.object(agencia.os, "replace", side_effect=OSError("fallo simulado")):
            with self.assertRaises(OSError):
                agencia.guardar_configuracion({"copia_adicional": "USB nueva"}, str(ruta))
        self.assertEqual(json.loads(ruta.read_text())["copia_adicional"], "USB original")
        self.assertFalse(list(self.root.glob("*.tmp")))

    def test_archivo_atomico_no_publica_cuerpo_incompleto(self):
        ruta = self.root / "documento.txt"
        ruta.write_text("original")
        with self.assertRaises(RuntimeError):
            with agencia.archivo_atomico(ruta) as f:
                f.write("parcial")
                raise RuntimeError("interrupción")
        self.assertEqual(ruta.read_text(), "original")
        self.assertFalse(list(self.root.glob("*.tmp")))

    def test_csv_neutraliza_formulas_sin_alterar_base(self):
        peligrosos = ["=1+1", "+SUM(1,2)", "-1+2", "@SUM(1,2)", " \t=1", "\ttexto", "\rtexto"]
        for nombre in peligrosos:
            self.db.insertar("clientes", {"nombre": nombre})
        destino = self.root / "csv"
        agencia.exportar_legible(str(self.ruta), str(destino))
        with open(destino / "Clientes.csv", newline="", encoding="utf-8-sig") as f:
            nombres = [r["nombre"] for r in csv.DictReader(f)]
        for nombre in peligrosos:
            self.assertIn("'" + nombre, nombres)
            self.assertIn(nombre, [r["nombre"] for r in self.db.todos("clientes")])
        self.assertEqual(agencia.celda_csv("Ana"), "Ana")
        self.assertEqual(agencia.celda_csv(123), 123)

    def test_dos_copias_misma_hora_conservan_ambas_instantaneas(self):
        carpeta = self.root / "respaldos"
        ahora = datetime(2026, 10, 1, 12, 0)
        a = agencia.respaldar("manual", str(self.ruta), str(carpeta), externas=[], ahora=ahora)
        self.db.insertar("clientes", {"nombre": "Otra persona ficticia"})
        b = agencia.respaldar("manual", str(self.ruta), str(carpeta), externas=[], ahora=ahora)
        self.assertNotEqual(a["archivo"], b["archivo"])
        self.assertEqual(agencia.contar_datos(a["archivo"])["clientes"], 1)
        self.assertEqual(agencia.contar_datos(b["archivo"])["clientes"], 2)
        self.assertIsNotNone(agencia._fecha_de_copia(Path(b["archivo"]).name))

    def test_nombre_de_respaldo_con_fecha_imposible_no_interrumpe_retencion(self):
        carpeta = self.root / "respaldos"
        carpeta.mkdir()
        invalido = carpeta / "agencia-auto-20269999-120000.db"
        invalido.write_text("ajeno")
        agencia.podar_respaldos(str(carpeta))
        self.assertTrue(invalido.exists())
        self.assertIsNone(agencia._fecha_de_copia(invalido.name))

    def test_copiar_o_restaurar_sobre_la_fuente_y_alias_se_rechaza(self):
        alias = self.root / "alias.db"
        original = self.ruta.read_bytes()
        os.link(self.ruta, alias)
        for destino in (self.ruta, alias):
            with self.subTest(destino=destino):
                with self.assertRaises(ValueError):
                    agencia.copiar_base(str(self.ruta), str(destino))
                with self.assertRaises(ValueError):
                    agencia.restaurar_archivo(str(self.ruta), str(destino))
        self.assertEqual(self.ruta.read_bytes(), original)
        self.assertEqual(alias.read_bytes(), original)
        # SQLite 3.54 no permite consultar una base con más de un enlace físico, y Windows no borra un enlace
        # de un archivo abierto: se cierra, se borra el alias y se reabre.
        self.db.con.close()
        alias.unlink()
        self.db = agencia.BaseDatos(str(self.ruta))

    def test_backup_sqlite_ocupado_tiene_espera_limitada(self):
        bloqueo = sqlite3.connect(self.ruta)
        bloqueo.execute("BEGIN EXCLUSIVE")
        fuente = agencia.conexion_lectura(str(self.ruta))
        destino = sqlite3.connect(self.root / "timeout.db")
        inicio = time.monotonic()
        try:
            with self.assertRaises(sqlite3.OperationalError):
                agencia._copiar_sqlite(fuente, destino, limite=0.1)
            self.assertLess(time.monotonic() - inicio, 2)
        finally:
            fuente.close()
            destino.close()
            bloqueo.rollback()
            bloqueo.close()

    def test_migracion_no_comienza_sin_respaldo_previo(self):
        copia = {"archivo": None, "externas": [], "omitido": None, "errores": ["sin espacio"]}
        with patch.object(agencia, "restaurar_si_esta_danada", return_value=None), \
                patch.object(agencia, "esquema_desactualizado", return_value=True), \
                patch.object(agencia, "respaldar", return_value=copia), \
                patch.object(agencia, "buscar_restauracion") as buscar:
            with self.assertRaises(OSError):
                agencia.preparar_base()
            buscar.assert_not_called()

    def test_importar_no_crea_directorio_de_datos(self):
        nuevo = self.root / "no-creado"
        env = dict(os.environ, AGENCIA_DATOS=str(nuevo))
        proc = subprocess.run([sys.executable, "-c", "import agencia"], cwd=Path(agencia.__file__).parent,
            env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(nuevo.exists())

    def test_error_de_ruta_al_arrancar_se_muestra(self):
        ruta = self.root / "es-un-archivo"
        ruta.write_text("contenido")
        ventana = Mock()
        with patch.object(agencia, "CARPETA", str(ruta)), patch.object(agencia.tk, "Tk", return_value=ventana), \
                patch.object(agencia, "reabrir_con_tk_moderno"), patch.object(agencia, "avisar_error") as aviso, \
                patch.object(agencia, "App") as app, patch.dict(sys.modules, {"ctypes": Mock()}):
            agencia.main()
        aviso.assert_called_once()
        app.assert_not_called()
        ventana.destroy.assert_called_once()

    def test_html_y_resumen_formatean_centavos_con_el_mismo_redondeo(self):
        self.db.actualizar("colocaciones", self.id, {"comision": "2.675", "sueldo_acordado": "1.015"})
        c = self.db.uno("colocaciones", self.id)
        documento = agencia.html_contrato(c, self.db.uno("clientes", self.cli), self.db.uno("trabajadoras", self.trab))
        self.assertIn("S/ 2.68", documento)
        self.assertIn("S/ 1.02", documento)

    def test_error_de_copia_resuelto_se_avisa_si_vuelve_a_ocurrir(self):
        self.app._errores_avisados = set()
        mala = {"archivo": None, "externas": [], "errores": ["USB no disponible"]}
        buena = {"archivo": "copia verificada", "externas": [], "errores": []}
        with patch.object(agencia.messagebox, "showwarning") as avisar:
            self.app._tomar_copia(mala, 1, True)
            self.app._tomar_copia(mala, 1, True)
            self.app._tomar_copia(buena, 2, True)
            self.app._tomar_copia(mala, 3, True)
            self.assertEqual(avisar.call_count, 2)


    def test_copia_de_base_wal_es_independiente_y_no_cambia_fuente(self):
        self.assertEqual(self.db.con.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
        self.db.insertar("clientes", {"nombre": "Cliente dentro del WAL"})
        destino = self.root / "copia-wal.db"
        agencia.copiar_base(str(self.ruta), str(destino))
        self.assertFalse(Path(str(destino)+"-wal").exists())
        self.assertFalse(Path(str(destino)+"-shm").exists())
        con = agencia.conexion_lectura(destino)
        try:
            self.assertEqual(con.execute("PRAGMA journal_mode").fetchone()[0], "delete")
            self.assertEqual(con.execute("SELECT count(*) FROM clientes").fetchone()[0], 2)
        finally:
            con.close()
        self.assertEqual(self.db.con.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        self.assertEqual(len(self.db.todos("clientes")), 2)

    def test_copia_externa_de_base_wal_incluye_csv_consistente(self):
        self.db.con.execute("PRAGMA journal_mode=WAL")
        self.db.insertar("clientes", {"nombre": "Cliente dentro del WAL"})
        externa = self.root / "externa-wal"
        agencia.copia_externa(str(self.ruta), str(externa), datetime(2026, 10, 1))
        self.assertEqual(agencia.contar_datos(str(externa / "agencia-20261001.db"))["clientes"], 2)
        with open(externa / "Datos legibles" / "Clientes.csv", newline="", encoding="utf-8-sig") as f:
            self.assertEqual(len(list(csv.DictReader(f))), 2)
        self.assertEqual(self.db.con.execute("PRAGMA journal_mode").fetchone()[0], "wal")

    def test_error_inesperado_de_copia_en_hilo_se_avisa(self):
        import queue
        respuestas = queue.Queue()
        respuestas.put(OSError("sin espacio en disco"))
        self.app._copiando = True
        self.app._errores_avisados = set()
        self.app._version_copiada = 4
        with patch.object(agencia, "registrar_error") as registrar, \
                patch.object(agencia.messagebox, "showwarning") as avisar:
            self.app._recoger_copia(respuestas, 5)
        registrar.assert_called_once()
        avisar.assert_called_once()
        self.assertIn("sin espacio en disco", avisar.call_args.args[1])
        self.assertFalse(self.app._copiando)
        self.assertEqual(self.app._version_copiada, 4)

    def test_configuracion_adicional_invalida_no_impide_copia_en_documentos(self):
        for valor in ([], {}, True, 25, "   "):
            with self.subTest(valor=valor):
                rutas = agencia.carpetas_externas({"copia_adicional": valor})
                self.assertEqual(len(rutas), 1)
        self.assertEqual(len(agencia.carpetas_externas({"copia_adicional": str(self.root)})), 2)
        self.assertEqual(len(agencia.carpetas_externas([])), 1)

    def test_area_usada_durante_confirmacion_no_se_elimina(self):
        nombre = list(agencia.AREAS_INICIALES)[-1]
        self.app.areas = Mock()
        self.app.copia_antes_de_borrar = Mock(return_value=True)
        def confirmar(*args, **kwargs):
            otra = sqlite3.connect(self.ruta)
            with otra:
                otra.execute("INSERT INTO clientes (nombre,tipo_servicio) VALUES (?,?)", ("Otra persona", nombre))
            otra.close()
            return True
        with patch.object(agencia.messagebox, "askyesno", side_effect=confirmar):
            self.assertFalse(self.app.eliminar_area(nombre))
        self.assertIsNotNone(self.db.con.execute("SELECT id FROM areas WHERE nombre=?", (nombre,)).fetchone())

    def test_area_nueva_rechaza_duplicado_externo_no_cacheado(self):
        self.app.areas = Mock()
        otra = sqlite3.connect(self.ruta)
        with otra:
            otra.execute("INSERT INTO areas (nombre,titulo) VALUES ('Jardinería','Jardinería')")
        otra.close()
        with patch.object(agencia, "pedir_texto", return_value="JARDINERÍA"):
            self.assertFalse(self.app.nueva_area())
        self.assertEqual(self.db.con.execute("SELECT count(*) FROM areas WHERE nombre='Jardinería'").fetchone()[0], 1)

    def test_area_sin_tilde_no_duplica_una_ya_existente(self):
        self.app.areas = Mock()
        with patch.object(agencia, "pedir_texto", return_value="Ninera"):
            self.assertFalse(self.app.nueva_area())
        self.assertEqual(self.db.con.execute("SELECT count(*) FROM areas WHERE nombre='Ninera'").fetchone()[0], 0)

    def test_formulario_rechaza_area_eliminada_aunque_cache_la_conserve(self):
        nombre = list(agencia.AREAS_INICIALES)[-1]
        self.db.con.execute("DELETE FROM areas WHERE nombre=?", (nombre,))
        self.db.con.commit()
        pagina = agencia.PaginaClientes.__new__(agencia.PaginaClientes)
        pagina.db = self.db
        pagina.form = Mock()
        self.assertIsNotNone(agencia.Pagina.validar_extra(pagina, {"tipo_servicio": nombre}))

    def test_nuevo_registro_no_adquiere_id_si_confirmacion_sqlite_falla(self):
        pagina = agencia.PaginaClientes.__new__(agencia.PaginaClientes)
        pagina.db = self.db
        pagina.app = self.app
        pagina.id_actual = None
        pagina.borrador = None
        escritos = {k: "" for k in agencia.claves(agencia.CAMPOS_CLIENTE)}
        escritos.update(nombre="Registro sin confirmar", telefono="5550123", tipo_servicio=list(agencia.AREAS)[0])
        pagina.form = Mock(obtener=Mock(return_value=escritos))
        lector = sqlite3.connect(self.ruta)
        lector.execute("BEGIN")
        lector.execute("SELECT * FROM clientes").fetchall()
        self.db.con.execute("PRAGMA busy_timeout=20")
        try:
            with self.assertRaises(sqlite3.OperationalError):
                agencia.Pagina.guardar(pagina, silencioso=True)
        finally:
            lector.rollback()
            lector.close()
        self.assertIsNone(pagina.id_actual)
        self.assertFalse(self.db.con.in_transaction)
        self.assertEqual(self.db.con.execute("SELECT count(*) FROM clientes WHERE nombre='Registro sin confirmar'").fetchone()[0], 0)
        self.assertEqual(pagina.form.obtener()["nombre"], "Registro sin confirmar")


    def test_dos_procesos_serializan_copia_externa_y_csv(self):
        externa = self.root / "externa"
        registro = self.root / "secuencia.txt"
        inicio = self.root / "salida"
        worker = """
import agencia,sys,time,os
from pathlib import Path
from datetime import datetime
ruta,externa,registro,inicio,numero=sys.argv[1:]
Path(inicio+numero).write_text('listo')
plazo=time.monotonic()+5
while not (Path(inicio+'0').exists() and Path(inicio+'1').exists()):
    if time.monotonic()>plazo: raise RuntimeError('barrera')
    time.sleep(0.01)
original=agencia.copiar_base
def copiar(*args):
    with open(registro,'a') as f: f.write('in '+numero+'\\n')
    original(*args)
    time.sleep(0.15)
    with open(registro,'a') as f: f.write('out '+numero+'\\n')
agencia.copiar_base=copiar
agencia.copia_externa(ruta,externa,datetime(2026,10,1))
"""
        procesos = [subprocess.Popen([sys.executable, "-c", worker, str(self.ruta), str(externa),
            str(registro), str(inicio), str(i)], cwd=Path(agencia.__file__).parent,
            env=dict(os.environ, AGENCIA_DATOS=str(self.root / ("datos-proceso-"+str(i)))),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in range(2)]
        try:
            for p in procesos:
                stdout, stderr = p.communicate(timeout=15)
                self.assertEqual(p.returncode, 0, stderr)
        finally:
            for p in procesos:
                if p.poll() is None:
                    p.kill()
                    p.communicate()
        entradas = registro.read_text().splitlines()
        self.assertIn(entradas, [["in 0", "out 0", "in 1", "out 1"], ["in 1", "out 1", "in 0", "out 0"]])
        self.assertEqual(agencia.contar_datos(str(externa / "agencia-20261001.db"))["clientes"], 1)
        with open(externa / "Datos legibles" / "Clientes.csv", newline="", encoding="utf-8-sig") as f:
            self.assertEqual(len(list(csv.DictReader(f))), 1)
        self.assertFalse(list(externa.rglob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
