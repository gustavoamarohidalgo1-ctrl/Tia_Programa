"""Pruebas de operaciones que deben conservar los datos aun si algo falla."""

import json
import os
import struct
import sys
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta
from unittest import mock
from pathlib import Path

import agencia
from agencia import (BaseDatos, area_de_texto, filtrar_opciones, sin_acentos, sinonimos_de_area, cargar_areas, restablecer_areas, base_sana, buscar_restauracion, carpetas_externas, con_garantia, contar_datos,
                     copia_externa, copiar_base, datos_contrato, hay_datos, html_contrato, html_firma,
                     inicio_por_firma, leer_configuracion, guardar_configuracion, leer_fecha, leer_numero,
                     esquema_desactualizado, listar_copias, meses_de_garantia, meses_del_cliente, numero_en_letras, texto_meses, podar_respaldos, monto_por_porcentaje, porcentaje_de, porcentaje_en_letras, registrar_error,
                     respaldar, restaurar_si_esta_danada, resumen_ganancias, situacion_garantia, sumar_meses)


class LotesDeBaseDatos(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory()
        self.ruta = Path(self.temporal.name) / "agencia.db"
        self.db = BaseDatos(self.ruta)

    def tearDown(self):
        self.db.con.close()
        self.temporal.cleanup()

    def test_un_error_revierte_todo_el_lote(self):
        with self.assertRaises(RuntimeError):
            with self.db.lote():
                self.db.insertar("clientes", {"nombre": "No guardar"})
                self.assertEqual(len(self.db.todos("clientes")), 1)
                raise RuntimeError("fallo simulado")

        self.assertEqual(self.db.todos("clientes"), [])
        with sqlite3.connect(self.ruta) as conexion:
            self.assertEqual(conexion.execute("SELECT count(*) FROM clientes").fetchone()[0], 0)

    def test_un_lote_interno_puede_revertirse_sin_perder_el_externo(self):
        with self.db.lote():
            cliente = self.db.insertar("clientes", {"nombre": "Guardar"})
            with self.assertRaises(RuntimeError):
                with self.db.lote():
                    self.db.actualizar("clientes", cliente, {"nombre": "Revertir"})
                    raise RuntimeError("fallo interno")
            self.assertEqual(self.db.uno("clientes", cliente)["nombre"], "Guardar")
            self.db.insertar("trabajadoras", {"nombre": "Trabajadora"})

        with sqlite3.connect(self.ruta) as conexion:
            self.assertEqual(conexion.execute("SELECT nombre FROM clientes").fetchone()[0], "Guardar")
            self.assertEqual(conexion.execute("SELECT count(*) FROM trabajadoras").fetchone()[0], 1)


class FirmasEnContrato(unittest.TestCase):
    def test_firmas_anteriores_y_datos_invalidos(self):
        dibujo = json.dumps({"w": 330, "h": 150, "trazos": [[1, 2, 3, 4]]})
        self.assertIn("<svg", html_firma(dibujo))
        self.assertEqual(html_firma('{"w": 330, "h": 150, "trazos": [["<script>", 2, 3, 4]]}'), "")
        self.assertEqual(html_firma('{"trazos": []}'), "")

    def test_nombre_se_escapa_al_imprimir(self):
        nombre = json.dumps({"tipo": "nombre", "texto": "Ana <López> & Sol"})
        self.assertIn("Ana &lt;López&gt; &amp; Sol", html_firma(nombre))


class Ganancias(unittest.TestCase):
    def setUp(self):
        self.clientes = [
            {"id": 1, "nombre": "Ana", "tipo_servicio": "Niñera"},
            {"id": 2, "nombre": "Luis", "tipo_servicio": "Cama adentro"},
        ]
        self.hoy = date(2026, 9, 27)

    def test_cobros_por_periodo_area_y_fecha_del_historial(self):
        colocaciones = [
            {"id": 1, "cliente_id": "1", "trabajadora_id": "7", "comision": "150.00",
             "comision_pagada": "1", "fecha_pago": "27/09/2026"},
            {"id": 2, "cliente_id": "2", "trabajadora_id": "8", "comision": "200",
             "comision_pagada": "1", "fecha_pago": "03/01/2026"},
            {"id": 3, "cliente_id": "1", "trabajadora_id": "9", "comision": "75",
             "comision_pagada": "1", "fecha_pago": "29/12/2025"},
            {"id": 4, "cliente_id": "2", "comision": "300", "comision_pagada": "0",
             "fecha_pago": "20/09/2026"},
            {"id": 5, "cliente_id": "1", "comision": "0", "comision_pagada": "1",
             "reemplazo_de": "1", "fecha_pago": "27/09/2026"},
        ]
        resumen = resumen_ganancias(colocaciones, self.clientes, self.hoy)

        self.assertEqual(resumen["cobrado_total"], 425)
        self.assertEqual(resumen["por_cobrar"], 300)
        self.assertEqual(resumen["cobrado_mes"], 150)
        self.assertEqual(resumen["cobrado_anio"], 350)
        self.assertEqual(resumen["cobrado_semana"], 150)  # 27/09/2026 es domingo: semana del 21 al 27
        self.assertEqual(len(resumen["meses_anio"]), 12)
        self.assertEqual(resumen["meses_anio"][0], 200)
        self.assertEqual(resumen["meses_anio"][8], 150)
        self.assertEqual(sum(resumen["meses_anio"]), 350)
        self.assertEqual(resumen["por_area"]["Niñeras"], 225)
        self.assertEqual(resumen["por_area"]["Cama adentro"], 200)
        self.assertEqual([pago["id"] for pago in resumen["historial"]], [1, 2, 3])
        self.assertEqual(resumen["historial"][0]["cliente"], "Ana")

    def test_datos_invalidos_no_inflan_cifras_ni_rompen_el_resumen(self):
        colocaciones = [
            {"id": 1, "cliente_id": 999, "comision": "50", "comision_pagada": "1",
             "fecha_pago": "fecha inválida"},
            {"id": 2, "comision": "sin importe", "comision_pagada": "1"},
            {"id": 3, "comision": "nan", "comision_pagada": "1"},
            {"id": 4, "comision": "inf", "comision_pagada": "0"},
            {"id": 5, "comision": "-20", "comision_pagada": "0"},
        ]
        resumen = resumen_ganancias(colocaciones, self.clientes, self.hoy)

        self.assertEqual(resumen["cobrado_total"], 50)
        self.assertEqual(resumen["por_area"]["Sin área"], 50)
        self.assertEqual(resumen["cobrado_anio"], 0)
        self.assertEqual(resumen["por_cobrar"], 0)
        self.assertEqual(resumen["historial"], [])

    def test_reversion_de_pago_devuelve_la_comision_a_por_cobrar(self):
        colocacion = {"id": 1, "cliente_id": 1, "comision": "300",
                      "comision_pagada": "1", "fecha_pago": "10/09/2026"}
        cobrada = resumen_ganancias([colocacion], self.clientes, self.hoy)
        pendiente = resumen_ganancias(
            [{**colocacion, "comision_pagada": "0", "fecha_pago": ""}],
            self.clientes, self.hoy)

        self.assertEqual(cobrada["cobrado_total"], 300)
        self.assertEqual(cobrada["por_cobrar"], 0)
        self.assertEqual(pendiente["cobrado_total"], 0)
        self.assertEqual(pendiente["por_cobrar"], 300)
        self.assertEqual(pendiente["historial"], [])


class GananciasSemanales(unittest.TestCase):
    def test_la_semana_va_de_lunes_a_domingo_y_cruza_meses(self):
        clientes = [{"id": 1, "nombre": "Ana", "tipo_servicio": "Niñera"}]

        def pago(dia, monto="100"):
            return {"id": 1, "cliente_id": "1", "comision": monto, "comision_pagada": "1", "fecha_pago": dia}

        hoy = date(2026, 10, 1)  # jueves; su semana va del 28/09 al 04/10
        cobros = [pago("27/09/2026"), pago("28/09/2026"), pago("01/10/2026"), pago("04/10/2026"),
                  pago("05/10/2026")]
        resumen = resumen_ganancias(cobros, clientes, hoy)
        self.assertEqual(resumen["cobrado_semana"], 300)   # 28/09, 01/10 y 04/10
        self.assertEqual(resumen["cobrado_mes"], 300)      # 01/10, 04/10 y 05/10


class InicioPorFirma(unittest.TestCase):
    def firmado(self, **cambios):
        c = {"estado": "En proceso", "contrato_firmado": "1", "fecha_contrato": "27/09/2026",
             "fecha_enlace": "20/09/2026", "garantia": "Sí", "meses_garantia": "2"}
        return {**c, **cambios}

    def test_la_garantia_corre_desde_la_fecha_del_contrato(self):
        self.assertEqual(inicio_por_firma(self.firmado()), {
            "fecha_inicio": "27/09/2026", "estado": "Activa", "fin_garantia": "27/11/2026"})

    def test_sin_garantia_inicia_pero_no_tiene_fin(self):
        datos = inicio_por_firma(self.firmado(garantia="No", meses_garantia="0"))
        self.assertEqual(datos, {"fecha_inicio": "27/09/2026", "estado": "Activa"})

    def test_sin_fecha_de_contrato_usa_la_de_la_asignacion(self):
        self.assertEqual(inicio_por_firma(self.firmado(fecha_contrato=""))["fecha_inicio"], "20/09/2026")

    def test_no_inicia_si_no_esta_firmado_ni_si_ya_inicio(self):
        self.assertIsNone(inicio_por_firma(self.firmado(contrato_firmado="")))
        self.assertIsNone(inicio_por_firma(self.firmado(estado="Activa")))
        self.assertIsNone(inicio_por_firma(self.firmado(estado="Reemplazo solicitado")))


class SituacionDeGarantia(unittest.TestCase):
    def enlace(self, **cambios):
        c = {"id": 1, "estado": "Activa", "garantia": "Sí", "meses_garantia": "2",
             "fin_garantia": "28/11/2026"}
        return {**c, **cambios}

    def test_sin_garantia_no_es_pendiente_ni_cerrada(self):
        self.assertEqual(situacion_garantia(self.enlace(garantia="No", meses_garantia="0"), set()),
                         ("Sin garantía", False))

    def test_pendiente_y_cerrada_segun_la_fecha_de_fin(self):
        vigente = self.enlace(fin_garantia="31/12/2999")
        self.assertTrue(situacion_garantia(vigente, set())[1])
        vencida = self.enlace(estado="Garantía cumplida")
        self.assertEqual(situacion_garantia(vencida, set()), ("Cumplida", False))
        self.assertEqual(situacion_garantia(self.enlace(estado="Reemplazo solicitado"), {"1"}),
                         ("Reemplazada", False))


class FechasYGarantia(unittest.TestCase):
    def test_sumar_meses_respeta_fin_de_mes_y_bisiestos(self):
        self.assertEqual(sumar_meses(date(2026, 9, 28), 2), date(2026, 11, 28))
        self.assertEqual(sumar_meses(date(2025, 12, 31), 2), date(2026, 2, 28))
        self.assertEqual(sumar_meses(date(2027, 12, 31), 2), date(2028, 2, 29))   # 2028 es bisiesto
        self.assertEqual(sumar_meses(date(2026, 11, 30), 3), date(2027, 2, 28))

    def test_leer_fecha_solo_acepta_dd_mm_aaaa(self):
        self.assertEqual(leer_fecha(" 05/03/2026 "), date(2026, 3, 5))
        for texto in ("", None, "2026-03-05", "31/02/2026", "5/3"):
            self.assertIsNone(leer_fecha(texto))

    def test_garantia_por_defecto_sin_dato_y_meses_invalidos(self):
        self.assertTrue(con_garantia({}))                      # enlaces antiguos: con garantía
        self.assertFalse(con_garantia({"garantia": "No"}))
        self.assertFalse(con_garantia({"meses_garantia": "0"}))
        self.assertEqual(meses_de_garantia({"meses_garantia": "3"}), 3)
        self.assertEqual(meses_de_garantia({"meses_garantia": "x"}), 2)
        self.assertEqual(meses_de_garantia({"garantia": "No"}), 0)

    def test_porcentaje_informativo(self):
        self.assertEqual(porcentaje_de("300", "1500"), "20")
        self.assertEqual(porcentaje_de("300", ""), "")
        self.assertEqual(porcentaje_de("abc", "1500"), "")


class ContratoImpreso(unittest.TestCase):
    def setUp(self):
        self.c = {"id": 7, "estado": "Activa", "garantia": "Sí", "meses_garantia": "2", "comision": "300.00",
                  "sueldo_acordado": "1800", "fecha_contrato": "28/09/2026", "reemplazo_de": "",
                  "contrato_firmado": "", "fecha_firma": "", "firma_cliente": "", "firma_trabajadora": "",
                  "firma_agencia": "", "puesto": "", "modalidad": "", "descanso": ""}
        self.cli = {"nombre": "Ana <b>Pérez</b>", "dni": "12345678", "direccion": "Av. Uno 1", "zona": "Lince",
                    "telefono": "999", "ocupacion": "", "tipo_servicio": "Niñera", "dias_libres": "Domingo",
                    "horario": ""}
        self.t = {"nombre": "Rosa & Sol", "dni": "87654321", "direccion": "", "zona": "Ate"}

    def test_incluye_los_dos_contratos_y_escapa_los_datos(self):
        pagina = html_contrato(self.c, self.cli, self.t)
        self.assertIn("CONTRATO Y GARANTÍA", pagina)
        self.assertIn("CONTRATO DE TRABAJO", pagina)
        self.assertNotIn("Ana <b>", pagina)
        self.assertIn("Ana &lt;b&gt;Pérez&lt;/b&gt;", pagina)
        self.assertIn("Rosa &amp; Sol", pagina)

    def test_sin_garantia_cambia_las_clausulas(self):
        pagina = html_contrato(dict(self.c, garantia="No", meses_garantia="0"), self.cli, self.t)
        self.assertIn("sin garantía", pagina)
        self.assertEqual(datos_contrato(dict(self.c, garantia="No"), self.cli)["meses_garantia"], "0")

    def test_imprimir_agrega_el_disparo_de_impresion_solo_si_se_pide(self):
        self.assertNotIn("window.print()</script>", html_contrato(self.c, self.cli, self.t))
        self.assertIn("window.print()", html_contrato(self.c, self.cli, self.t, imprimir=True))


class RegistroDeErrores(unittest.TestCase):
    def test_guarda_el_error_y_acumula_sin_borrar_los_anteriores(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "errores.log"
            for mensaje in ("primero", "segundo"):
                try:
                    raise ValueError(mensaje)
                except ValueError:
                    import sys
                    detalle = registrar_error(sys.exc_info(), ruta)
                self.assertIn(f"ValueError: {mensaje}", detalle)
            texto = ruta.read_text(encoding="utf-8")
            self.assertIn("primero", texto)
            self.assertIn("segundo", texto)

    def test_una_ruta_imposible_no_provoca_otro_error(self):
        try:
            raise ValueError("x")
        except ValueError:
            import sys
            detalle = registrar_error(sys.exc_info(), "/no/existe/carpeta/errores.log")
        self.assertIn("ValueError: x", detalle)


class NumerosEscritosPorPersonas(unittest.TestCase):
    def test_separadores_de_miles_y_decimales(self):
        casos = {"2200": 2200, "2,200": 2200, "S/ 2,200": 2200, "1,234.56": 1234.56, "1.234,56": 1234.56,
                 "2 200": 2200, "12,50": 12.5, "300.00": 300, "1.234.567": 1234567, "1,234,567": 1234567,
                 "-20": -20, "1500.00": 1500, " 90 ": 90}
        for texto, esperado in casos.items():
            self.assertEqual(leer_numero(texto), esperado, texto)
        self.assertEqual(leer_numero(5), 5.0)

    def test_lo_que_no_es_numero_sigue_siendo_none(self):
        for texto in ("", None, "sin importe", "abc", "1,5,5x", "-"):
            self.assertIsNone(leer_numero(texto), texto)

    def test_lo_guardado_con_dos_decimales_se_lee_igual(self):
        for monto in (0, 300, 1500.5, 2200, 12345.67):
            self.assertEqual(leer_numero(f"{monto:.2f}"), monto)


class BaseDanadaYRespaldos(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory()
        self.carpeta = Path(self.temporal.name)
        self.ruta = str(self.carpeta / "agencia.db")
        self.respaldos = str(self.carpeta / "respaldos")
        db = BaseDatos(self.ruta)
        db.insertar("clientes", {"nombre": "Ana"})
        db.con.close()

    def tearDown(self):
        self.temporal.cleanup()

    def respaldar(self, dia=27, hora=12):
        return respaldar("auto", self.ruta, self.respaldos, externas=[], ahora=datetime(2026, 9, dia, hora))

    def danar(self):
        Path(self.ruta).write_bytes(b"esto no es una base de datos" * 200)

    def test_base_sana_y_danada(self):
        self.assertTrue(base_sana(self.ruta))
        self.danar()
        self.assertFalse(base_sana(self.ruta))

    def test_una_base_ocupada_por_otra_copia_no_se_confunde_con_dano(self):
        otra = sqlite3.connect(self.ruta, timeout=0)
        otra.execute("BEGIN EXCLUSIVE")
        try:
            self.assertTrue(base_sana(self.ruta))
            self.assertIsNone(restaurar_si_esta_danada(self.ruta, self.respaldos))
        finally:
            otra.rollback()
            otra.close()

    def test_no_hace_nada_si_la_base_esta_sana_o_no_existe(self):
        self.assertIsNone(restaurar_si_esta_danada(self.ruta, self.respaldos))
        self.assertIsNone(restaurar_si_esta_danada(str(self.carpeta / "no_existe.db"), self.respaldos))

    def test_restaura_el_ultimo_respaldo_sano_y_conserva_la_danada(self):
        self.respaldar()
        self.danar()
        Path(self.ruta + "-journal").write_bytes(b"resto")
        aviso = restaurar_si_esta_danada(self.ruta, self.respaldos)
        self.assertIn("agencia-auto-20260927-120000.db", aviso)
        with sqlite3.connect(self.ruta) as con:
            self.assertEqual(con.execute("SELECT nombre FROM clientes").fetchone()[0], "Ana")
        nombres = os.listdir(self.respaldos)
        self.assertTrue(any(n.startswith("agencia-danada-") and n.endswith(".db") for n in nombres))
        self.assertFalse(os.path.exists(self.ruta + "-journal"))   # ningún resto junto a la base nueva

    def test_sin_respaldo_sano_no_toca_nada_y_avisa(self):
        self.danar()
        original = Path(self.ruta).read_bytes()
        with self.assertRaises(sqlite3.DatabaseError):
            restaurar_si_esta_danada(self.ruta, self.respaldos)
        self.assertEqual(Path(self.ruta).read_bytes(), original)

    def test_un_respaldo_danado_se_salta_y_se_usa_uno_sano(self):
        self.respaldar(dia=26)
        (Path(self.respaldos) / "agencia-auto-20260927-120000.db").write_bytes(b"basura" * 100)
        self.danar()
        self.assertIn("agencia-auto-20260926-120000.db", restaurar_si_esta_danada(self.ruta, self.respaldos))

    def test_tambien_restaura_desde_una_carpeta_externa(self):
        externa = str(self.carpeta / "externa")
        copia_externa(self.ruta, externa, datetime(2026, 9, 27))
        self.danar()
        aviso = restaurar_si_esta_danada(self.ruta, [self.respaldos, externa])
        self.assertIn("agencia-20260927.db", aviso)


class MotorDeCopias(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory()
        self.carpeta = Path(self.temporal.name)
        self.ruta = str(self.carpeta / "agencia.db")
        self.respaldos = str(self.carpeta / "respaldos")
        self.db = BaseDatos(self.ruta)

    def tearDown(self):
        self.db.con.close()
        self.temporal.cleanup()

    def con_datos(self):
        self.db.insertar("clientes", {"nombre": "Ana"})

    def falsas(self, motivo, fechas):
        """Copias válidas con las fechas indicadas (para probar la retención)."""
        import shutil
        os.makedirs(self.respaldos, exist_ok=True)
        modelo = os.path.join(self.respaldos, "modelo.tmp")
        copiar_base(self.ruta, modelo)                      # una copia verificada; las demás son duplicados suyos
        for fecha in fechas:
            shutil.copyfile(modelo, os.path.join(self.respaldos, f"agencia-{motivo}-{fecha:%Y%m%d-%H%M%S}.db"))
        os.remove(modelo)

    def nombres(self, tipo="auto"):
        return sorted(n for n in os.listdir(self.respaldos) if n.startswith(f"agencia-{tipo}-"))

    def test_una_base_vacia_no_genera_copia(self):
        resultado = respaldar("auto", self.ruta, self.respaldos, externas=[])
        self.assertIsNone(resultado["archivo"])
        self.assertTrue(resultado["omitido"])
        self.assertFalse(os.path.exists(self.respaldos))

    def test_copia_verificada_con_nombre_de_fecha_y_hora(self):
        self.con_datos()
        r = respaldar("auto", self.ruta, self.respaldos, externas=[], ahora=datetime(2026, 9, 28, 10, 15, 30))
        self.assertTrue(r["archivo"].endswith("agencia-auto-20260928-101530.db"))
        self.assertEqual(contar_datos(r["archivo"])["clientes"], 1)
        self.assertEqual(r["errores"], [])
        self.assertFalse(any(n.endswith(".tmp") for n in os.listdir(self.respaldos)))

    def test_no_copia_una_base_danada_ni_deja_archivos_a_medias(self):
        dañada = str(self.carpeta / "mala.db")
        Path(dañada).write_bytes(b"basura" * 500)
        with self.assertRaises(sqlite3.DatabaseError):
            copiar_base(dañada, str(self.carpeta / "copia.db"))
        self.assertEqual(os.listdir(self.carpeta).count("copia.db"), 0)
        self.assertFalse(any(n.endswith(".tmp") for n in os.listdir(self.carpeta)))

    def test_una_copia_que_no_se_verifica_nunca_reemplaza_a_una_buena(self):
        self.con_datos()
        buena = str(self.carpeta / "copia.db")
        copiar_base(self.ruta, buena)
        contenido = Path(buena).read_bytes()
        self.db.insertar("clientes", {"nombre": "Luis"})
        with mock.patch.object(agencia, "base_sana", return_value=False):
            with self.assertRaises(sqlite3.DatabaseError):
                copiar_base(self.ruta, buena)
        self.assertEqual(Path(buena).read_bytes(), contenido)
        self.assertFalse(os.path.exists(buena + ".tmp"))

    def test_copia_externa_con_datos_legibles_para_excel(self):
        self.con_datos()
        externa = str(self.carpeta / "Documentos" / "Respaldos")
        r = respaldar("auto", self.ruta, self.respaldos, externas=[externa], ahora=datetime(2026, 9, 28, 9))
        self.assertEqual(r["externas"], [externa])
        self.assertEqual(contar_datos(os.path.join(externa, "agencia-20260928.db"))["clientes"], 1)
        csv_clientes = Path(externa, "Datos legibles", "Clientes.csv").read_bytes()
        self.assertTrue(csv_clientes.startswith(b"\xef\xbb\xbf"))            # Excel lee bien los acentos
        self.assertIn(b"Ana", csv_clientes)
        self.assertTrue(os.path.exists(os.path.join(externa, "LEEME.txt")))
        self.db.insertar("clientes", {"nombre": "Luis"})                       # el mismo día se renueva, no se acumula
        respaldar("auto", self.ruta, self.respaldos, externas=[externa], ahora=datetime(2026, 9, 28, 18))
        self.assertEqual([n for n in os.listdir(externa) if n.endswith(".db")], ["agencia-20260928.db"])
        self.assertEqual(contar_datos(os.path.join(externa, "agencia-20260928.db"))["clientes"], 2)

    def test_las_externas_guardan_solo_los_ultimos_dias(self):
        self.con_datos()
        externa = str(self.carpeta / "ext")
        for dia in range(1, 36):
            copia_externa(self.ruta, externa, datetime(2026, 8, 1) + timedelta(days=dia))
        diarias = [n for n in os.listdir(externa) if n.endswith(".db")]
        self.assertEqual(len(diarias), agencia.DIAS_EXTERNAS)

    def test_si_una_carpeta_externa_falla_las_demas_copias_se_hacen(self):
        self.con_datos()
        ocupada = self.carpeta / "es_un_archivo"
        ocupada.write_text("x")
        buena = str(self.carpeta / "buena")
        r = respaldar("auto", self.ruta, self.respaldos, externas=[str(ocupada / "sub"), buena])
        self.assertTrue(r["archivo"])
        self.assertEqual(r["externas"], [buena])
        self.assertEqual(len(r["errores"]), 1)

    def test_retencion_de_las_copias_automaticas(self):
        self.con_datos()
        ahora = datetime(2026, 9, 28, 12, 0)
        reciente = [ahora - timedelta(minutes=m) for m in (5, 20, 60, 150)]                   # <3 h: todas
        misma_hora = [ahora - timedelta(hours=10, minutes=m) for m in (5, 40)]                # una por hora
        otra_hora = [ahora - timedelta(hours=20)]
        mismo_dia = [ahora - timedelta(days=10, hours=h) for h in (0, 3, 6)]                  # una por día
        antiguas = [ahora - timedelta(days=61), ahora - timedelta(days=90)]                   # se borran
        self.falsas("auto", reciente + misma_hora + otra_hora + mismo_dia + antiguas)
        ajenas = ["agencia-manual-20200101-000000.db", "agencia-antes-entrevista-20260928-094707.db",
                  "agencia-danada-20260101-000000.db"]
        for nombre in ajenas:
            copiar_base(self.ruta, os.path.join(self.respaldos, nombre))
        podar_respaldos(self.respaldos, ahora)
        quedan = set(self.nombres())
        esperadas = [*reciente, max(misma_hora), *otra_hora, max(mismo_dia)]
        self.assertEqual(quedan, {f"agencia-auto-{f:%Y%m%d-%H%M%S}.db" for f in esperadas})
        for nombre in ajenas:                                                                  # lo que no crea el programa no se toca
            self.assertTrue(os.path.exists(os.path.join(self.respaldos, nombre)), nombre)

    def test_retencion_de_las_copias_previas_a_borrar_y_restaurar(self):
        self.con_datos()
        ahora = datetime(2026, 9, 28, 12, 0)
        self.falsas("antes-de-borrar", [ahora - timedelta(minutes=m) for m in range(35)])
        self.falsas("antes-de-restaurar", [ahora - timedelta(minutes=m) for m in range(15)])
        podar_respaldos(self.respaldos, ahora)
        self.assertEqual(len(self.nombres("antes-de-borrar")), 30)
        self.assertEqual(len(self.nombres("antes-de-restaurar")), 10)
        self.assertIn("agencia-antes-de-borrar-20260928-120000.db", self.nombres("antes-de-borrar"))   # la más nueva se queda

    def test_listar_copias_con_sus_datos_ordenadas_y_sin_basura(self):
        self.con_datos()
        r1 = respaldar("auto", self.ruta, self.respaldos, externas=[], ahora=datetime(2026, 9, 28, 9))
        self.db.insertar("trabajadoras", {"nombre": "Rosa"})
        r2 = respaldar("manual", self.ruta, self.respaldos, externas=[], ahora=datetime(2026, 9, 28, 10))
        os.utime(r1["archivo"], (1, 1000))
        Path(self.respaldos, "agencia-auto-20260101-000000.db").write_bytes(b"basura")
        Path(self.respaldos, "agencia-danada-20260101-000000.db").write_bytes(b"x")
        copias = listar_copias([(self.respaldos, "Programa")])
        self.assertEqual([c["tipo"] for c in copias], ["Manual", "Automática"])
        self.assertEqual((copias[0]["clientes"], copias[0]["trabajadoras"]), (1, 1))
        self.assertEqual((copias[1]["clientes"], copias[1]["trabajadoras"]), (1, 0))
        self.assertEqual({c["donde"] for c in copias}, {"Programa"})

    def test_ofrece_recuperar_solo_si_el_programa_esta_vacio_y_hay_copias_con_datos(self):
        self.con_datos()
        respaldar("auto", self.ruta, self.respaldos, externas=[], ahora=datetime(2026, 9, 28, 9))
        carpetas = [(self.respaldos, "Programa")]
        self.assertIsNone(buscar_restauracion(self.ruta, carpetas))                     # hay datos: no molestar
        self.db.con.close()
        os.remove(self.ruta)
        oferta = buscar_restauracion(self.ruta, carpetas)                               # la base desapareció
        self.assertEqual(oferta["clientes"], 1)
        self.db = BaseDatos(self.ruta)                                                  # base nueva y vacía
        self.assertEqual(buscar_restauracion(self.ruta, carpetas)["clientes"], 1)
        self.assertIsNone(buscar_restauracion(self.ruta, [(str(self.carpeta / "nada"), "x")]))

    def test_una_base_con_tablas_de_una_version_anterior_cuenta_sus_datos(self):
        antigua = str(self.carpeta / "antigua.db")
        with sqlite3.connect(antigua) as con:
            con.execute("CREATE TABLE clientes (id INTEGER PRIMARY KEY, nombre TEXT)")
            con.execute("INSERT INTO clientes (nombre) VALUES ('Ana')")
        self.assertEqual(contar_datos(antigua), {"clientes": 1, "trabajadoras": 0, "colocaciones": 0})
        self.assertTrue(hay_datos(antigua))

    def test_una_base_ocupada_no_se_toma_por_vacia(self):
        self.con_datos()
        otra = sqlite3.connect(self.ruta, timeout=0)
        otra.execute("BEGIN EXCLUSIVE")
        try:
            self.assertIsNone(contar_datos(self.ruta))      # se ignora cuánto hay: nunca se asume que está vacía
        finally:
            otra.rollback()
            otra.close()

    def test_no_ofrece_copias_vacias(self):
        vacia = str(self.carpeta / "respaldos" / "agencia-auto-20260101-000000.db")
        os.makedirs(self.respaldos)
        copiar_base(self.ruta, vacia)
        self.assertIsNone(buscar_restauracion(self.ruta, [(self.respaldos, "Programa")]))

    def test_restaurar_sobre_la_base_abierta_y_migrar_copias_antiguas(self):
        self.con_datos()
        copia = respaldar("auto", self.ruta, self.respaldos, externas=[])["archivo"]
        self.db.insertar("clientes", {"nombre": "Luis"})
        version = self.db.version
        self.db.restaurar_desde(copia)
        self.assertEqual([c["nombre"] for c in self.db.todos("clientes")], ["Ana"])
        self.assertGreater(self.db.version, version)
        # una copia de una versión antigua, sin las columnas nuevas, se completa sola
        antigua = str(self.carpeta / "antigua.db")
        with sqlite3.connect(antigua) as con:
            con.execute("CREATE TABLE clientes (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT DEFAULT '')")
            con.execute("INSERT INTO clientes (nombre) VALUES ('Vieja')")
        self.db.restaurar_desde(antigua)
        self.db.insertar("clientes", {"nombre": "Nueva", "ocupacion": "Contadora"})
        self.assertEqual(sorted(c["nombre"] for c in self.db.todos("clientes")), ["Nueva", "Vieja"])
        self.assertEqual(self.db.todos("trabajadoras"), [])

    def test_configuracion_y_carpetas_externas(self):
        ruta = str(self.carpeta / "configuracion.json")
        self.assertEqual(leer_configuracion(ruta), {})
        guardar_configuracion({"copia_adicional": "E:/USB"}, ruta)
        self.assertEqual(leer_configuracion(ruta), {"copia_adicional": "E:/USB"})
        Path(ruta).write_text("{ esto no es json")
        self.assertEqual(leer_configuracion(ruta), {})                                  # un archivo roto no impide abrir
        externas = carpetas_externas({"copia_adicional": "E:/USB"})
        self.assertEqual(len(externas), 2)
        self.assertTrue(externas[0].endswith("Respaldos " + agencia.AGENCIA_NOMBRE))
        self.assertEqual(carpetas_externas({"copia_adicional": externas[0]}), [externas[0]])   # sin duplicados


class DatosVaciosEnLaBase(unittest.TestCase):
    def test_un_valor_null_se_lee_como_texto_vacio(self):
        with tempfile.TemporaryDirectory() as carpeta:
            db = BaseDatos(Path(carpeta) / "agencia.db")
            db.insertar("clientes", {"nombre": "Ana"})
            db.con.execute("UPDATE clientes SET zona = NULL, estado = NULL")
            db.con.commit()
            db._memoria.clear()
            fila = db.todos("clientes")[0]
            self.assertEqual((fila["zona"], fila["estado"], fila["nombre"]), ("", "", "Ana"))
            db.con.close()


class IconoDeLaAplicacion(unittest.TestCase):
    CARPETA = Path(agencia.RECURSOS)

    def test_los_archivos_de_icono_son_validos(self):
        png = (self.CARPETA / "icono.png").read_bytes()
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", png[16:24]), (256, 256))
        ico = (self.CARPETA / "icono.ico").read_bytes()
        reservado, tipo, cantidad = struct.unpack("<HHH", ico[:6])
        self.assertEqual((reservado, tipo), (0, 1))
        self.assertGreaterEqual(cantidad, 4)
        for i in range(cantidad):   # cada imagen apunta a datos que existen dentro del archivo
            tamano, desplazamiento = struct.unpack("<II", ico[6 + 16 * i + 8:6 + 16 * i + 16])
            self.assertLessEqual(desplazamiento + tamano, len(ico))
        self.assertEqual((self.CARPETA / "icono.icns").read_bytes()[:4], b"icns")

    def test_poner_icono_funciona_y_no_falla_si_faltan_los_archivos(self):
        try:
            root = agencia.tk.Tk()
        except agencia.tk.TclError:
            self.skipTest("no hay pantalla disponible")
        root.withdraw()
        try:
            agencia.poner_icono(root)
            if agencia.tk.TkVersion >= 8.6:   # Tk 8.5 no lee PNG: ahí abre con el ícono por defecto
                self.assertEqual(root._icono.width(), 256)
            ruta_png, ruta_ico, ruta_logo = agencia.ICONO_PNG, agencia.ICONO_ICO, agencia.LOGO_PATH
            agencia.ICONO_PNG = agencia.ICONO_ICO = agencia.LOGO_PATH = "/no/existe.png"
            try:
                agencia.poner_icono(root)   # sin archivos: abre igual con el ícono por defecto
            finally:
                agencia.ICONO_PNG, agencia.ICONO_ICO, agencia.LOGO_PATH = ruta_png, ruta_ico, ruta_logo
        finally:
            root.destroy()


class CarpetaDeDatos(unittest.TestCase):
    def datos(self, **kw):
        return agencia.carpeta_datos(**{"argv": ["agencia.py"], "entorno": {}, "casa": "/Users/ana", **kw})

    def test_sin_instalar_los_datos_siguen_junto_al_programa(self):
        self.assertEqual(self.datos(), agencia.carpeta_app())

    def test_la_opcion_y_la_variable_mandan_sobre_todo(self):
        self.assertEqual(self.datos(argv=["agencia.py", "--datos", "/x/y"], entorno={"AGENCIA_DATOS": "/z"}), "/x/y")
        self.assertEqual(self.datos(entorno={"AGENCIA_DATOS": "/z"}), "/z")
        self.assertEqual(self.datos(argv=["agencia.py", "--datos"]), agencia.carpeta_app())   # sin valor: se ignora

    def test_instalado_usa_la_carpeta_del_usuario_segun_el_sistema(self):
        agencia.sys.frozen = True
        try:
            with tempfile.TemporaryDirectory() as vacia:
                original = agencia.sys.executable
                agencia.sys.executable = os.path.join(vacia, "programa")
                try:
                    self.assertEqual(self.datos(plataforma="darwin"),
                                     "/Users/ana/Library/Application Support/" + agencia.AGENCIA_NOMBRE)
                    self.assertEqual(self.datos(plataforma="win32", entorno={"LOCALAPPDATA": "C:\\L"}),
                                     os.path.join("C:\\L", agencia.AGENCIA_NOMBRE))
                    self.assertEqual(self.datos(plataforma="linux"),
                                     os.path.join("/Users/ana/.local/share", agencia.AGENCIA_NOMBRE))
                    Path(vacia, "agencia.db").write_bytes(b"")   # datos de una instalación antigua junto al .exe
                    self.assertEqual(self.datos(plataforma="win32"), vacia)
                finally:
                    agencia.sys.executable = original
        finally:
            del agencia.sys.frozen


class ComisionPorPorcentaje(unittest.TestCase):
    def test_porcentaje_con_decimales_y_monto_a_partir_del_porcentaje(self):
        self.assertEqual([porcentaje_de(m, s) for m, s in (("300", "1500"), ("275", "2200"), ("300", "2200"), ("0", "1500"))],
                         ["20", "12.5", "13.64", "0"])
        self.assertEqual(porcentaje_de("300", ""), "")
        self.assertEqual(porcentaje_de("abc", "1500"), "")
        self.assertEqual(monto_por_porcentaje("20", "1500"), "300.00")
        self.assertEqual(monto_por_porcentaje("12.5", "2,200"), "275.00")
        for malo in (("", "1500"), ("20", ""), ("x", "1500"), ("-5", "1500")):
            self.assertIsNone(monto_por_porcentaje(*malo), malo)

    def test_el_porcentaje_se_lee_en_letras_como_el_resto_del_contrato(self):
        casos = {"20": "veinte por ciento (20 %)", "1": "uno por ciento (1 %)", "21": "veintiuno por ciento (21 %)",
                 "31": "treinta y uno por ciento (31 %)", "50": "cincuenta por ciento (50 %)",
                 "100": "cien por ciento (100 %)", "12.5": "12.5 %", "13.64": "13.64 %"}
        for entrada, esperado in casos.items():
            self.assertEqual(porcentaje_en_letras(entrada), esperado, entrada)

    def contrato(self, comision, sueldo, **extra):
        c = {"id": 1, "estado": "Activa", "garantia": "Sí", "meses_garantia": "2", "comision": comision,
             "sueldo_acordado": sueldo, "fecha_contrato": "28/09/2026", "reemplazo_de": "", "contrato_firmado": "",
             "fecha_firma": "", "firma_cliente": "", "firma_trabajadora": "", "firma_agencia": "", "puesto": "",
             "modalidad": "", "descanso": "", **extra}
        cli = {"nombre": "A", "dni": "1", "direccion": "", "zona": "", "telefono": "", "ocupacion": "",
               "tipo_servicio": "Niñera", "dias_libres": "", "horario": ""}
        pagina = html_contrato(c, cli, {"nombre": "B", "dni": "2", "direccion": "", "zona": ""})
        import re
        primera = re.search(r"<b>PRIMERA:</b>.*?</p>", pagina, re.S).group(0)
        return " ".join(re.sub(r"<[^>]+>", "", primera).replace("&nbsp;", " ").split())

    def test_el_contrato_dice_el_monto_y_su_porcentaje_del_sueldo(self):
        self.assertIn("por única vez de S/ 300.00, equivalente al veinte por ciento (20 %) del sueldo mensual "
                      "pactado de S/ 1,500.00, con una garantía de dos (2) meses", self.contrato("300.00", "1500"))
        self.assertIn("equivalente al 12.5 % del sueldo mensual pactado de S/ 2,200.00",
                      self.contrato("275.00", "2200"))
        self.assertIn("equivalente al cincuenta por ciento (50 %) del sueldo mensual pactado de S/ 900.00",
                      self.contrato("450.00", "900"))

    def test_sin_sueldo_o_sin_costo_el_contrato_no_inventa_un_porcentaje(self):
        self.assertNotIn("equivalente", self.contrato("300.00", ""))
        gratis = self.contrato("0.00", "1500", reemplazo_de="4")
        self.assertNotIn("equivalente", gratis)
        self.assertIn("cambio de personal sin costo", gratis)


class AreasEnLaBase(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory()
        self.ruta = str(Path(self.temporal.name) / "agencia.db")

    def tearDown(self):
        restablecer_areas()
        self.temporal.cleanup()

    def test_una_base_nueva_trae_las_areas_de_siempre_y_no_cuenta_como_datos(self):
        db = BaseDatos(self.ruta)
        self.assertEqual([f["nombre"] for f in sorted(db.todos("areas"), key=lambda f: f["id"])],
                         list(agencia.AREAS_INICIALES))
        cargar_areas(db)
        self.assertEqual(dict(agencia.AREAS), agencia.AREAS_INICIALES)
        self.assertEqual(agencia.TIPOS_SERVICIO, list(agencia.AREAS_INICIALES))
        db.con.close()
        self.assertFalse(hay_datos(self.ruta))                     # las áreas iniciales no son «datos» de la agencia
        self.assertEqual(set(contar_datos(self.ruta)), {"clientes", "trabajadoras", "colocaciones"})

    def test_una_base_antigua_recibe_las_areas_una_sola_vez(self):
        with sqlite3.connect(self.ruta) as con:
            con.execute("CREATE TABLE clientes (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT DEFAULT '', "
                        "tipo_servicio TEXT DEFAULT '')")
            con.execute("INSERT INTO clientes (nombre, tipo_servicio) VALUES ('Ana', 'Niñera')")
        self.assertTrue(esquema_desactualizado(self.ruta))
        db = BaseDatos(self.ruta)
        self.assertEqual(len(db.todos("areas")), len(agencia.AREAS_INICIALES))
        self.assertEqual(db.todos("clientes")[0]["tipo_servicio"], "Niñera")          # sus datos siguen intactos
        cocina = next(f for f in db.todos("areas") if f["nombre"] == "Cocinera")
        db.eliminar("areas", cocina["id"])                                            # la agencia elimina un área...
        db.con.close()
        db = BaseDatos(self.ruta)                                                     # ...y al reabrir no reaparece
        self.assertNotIn("Cocinera", [f["nombre"] for f in db.todos("areas")])
        db.con.close()
        self.assertFalse(esquema_desactualizado(self.ruta))

    def test_las_areas_creadas_se_cargan_en_orden_y_dan_titulo_y_descripcion(self):
        db = BaseDatos(self.ruta)
        db.insertar("areas", {"nombre": "Jardinería", "titulo": "Jardinería", "descripcion": "Cuidado de jardines"})
        cargar_areas(db)
        self.assertEqual(list(agencia.AREAS)[-1], "Jardinería")
        self.assertEqual(agencia.AREAS["Jardinería"], ("Jardinería", "Cuidado de jardines"))
        self.assertIn("Jardinería", agencia.TIPOS_SERVICIO)
        self.assertEqual(agencia.AREAS["Niñera"][0], "Niñeras")                       # los títulos de siempre se conservan
        db.con.close()

    def test_una_copia_antigua_sin_areas_se_completa_al_restaurarla(self):
        db = BaseDatos(self.ruta)
        db.insertar("clientes", {"nombre": "Ana"})
        antigua = str(Path(self.temporal.name) / "antigua.db")
        with sqlite3.connect(antigua) as con:
            con.execute("CREATE TABLE clientes (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT DEFAULT '')")
            con.execute("INSERT INTO clientes (nombre) VALUES ('Vieja')")
        db.restaurar_desde(antigua)
        self.assertEqual(len(db.todos("areas")), len(agencia.AREAS_INICIALES))
        db.con.close()


class RegistroDeCambios(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory()
        self.db = BaseDatos(str(Path(self.temporal.name) / "agencia.db"))

    def tearDown(self):
        self.db.con.close()
        self.temporal.cleanup()

    def test_se_sabe_que_cambio_desde_una_revision(self):
        base = self.db.revision("clientes")
        self.assertEqual(self.db.cambios_desde("clientes", base), [])
        a = self.db.insertar("clientes", {"nombre": "Ana"})
        self.db.actualizar("clientes", a, {"zona": "Lince"})
        self.db.insertar("trabajadoras", {"nombre": "Rosa"})                     # otra tabla: no cuenta
        self.assertEqual(self.db.cambios_desde("clientes", base), [("ins", a), ("act", a)])
        medio = self.db.revision("clientes")
        self.db.eliminar("clientes", a)
        self.assertEqual(self.db.cambios_desde("clientes", medio), [("del", a)])
        self.assertEqual(self.db.cambios_desde("clientes", self.db.revision("clientes")), [])

    def releer_todo(self, base):
        """«No se puede saber» (None) o «todo cambió»: en ambos casos hay que releer todo."""
        cambios = self.db.cambios_desde("clientes", base)
        return cambios is None or ("todo", None) in cambios

    def test_los_cambios_que_no_se_pueden_saber_obligan_a_releer_todo(self):
        ruta = self.db.con.execute("PRAGMA database_list").fetchone()[2]
        a = self.db.insertar("clientes", {"nombre": "Ana"})
        base = self.db.revision("clientes")
        self.assertFalse(self.releer_todo(base))                                 # sin cambios: no hace falta
        with self.assertRaises(RuntimeError):                                    # una operación se revierte
            with self.db.lote():
                self.db.actualizar("clientes", a, {"zona": "X"})
                raise RuntimeError("fallo")
        self.assertTrue(self.releer_todo(base))
        base = self.db.revision("clientes")
        copia = str(Path(self.temporal.name) / "copia.db")
        copiar_base(ruta, copia)
        self.db.restaurar_desde(copia)                                           # se restaura una copia
        self.assertTrue(self.releer_todo(base))
        base = self.db.revision("clientes")
        otra = sqlite3.connect(ruta)                                             # otra copia del programa guarda
        otra.execute("UPDATE clientes SET zona = 'Y'"); otra.commit(); otra.close()
        self.assertTrue(self.db.cambio_externo())
        self.assertTrue(self.releer_todo(base))

    def leer_todo_de_nuevo(self, tabla):
        """Lo que daría leer la tabla entera desde el disco (para comparar con la memoria al día)."""
        return [BaseDatos._fila(r) for r in self.db.con.execute(f"SELECT * FROM {tabla} ORDER BY id DESC")]

    def test_la_memoria_al_dia_es_igual_a_releer_toda_la_tabla_en_cualquier_secuencia(self):
        import random
        azar = random.Random(9)
        for i in range(12):
            self.db.insertar("clientes", {"nombre": f"C{i}", "zona": "Lince"})
        self.db.todos("clientes")                                                # la memoria está llena
        for paso in range(150):
            ids = [f["id"] for f in self.db.todos("clientes")]
            op = azar.choice(["act", "act", "act", "ins", "del", "lote_fallido", "lote_bueno", "nulo", "numero"])
            if op == "act" and ids:
                self.db.actualizar("clientes", azar.choice(ids), {"zona": azar.choice(["A", "B", ""]), "nombre": f"N{paso}"})
            elif op == "ins":
                self.db.insertar("clientes", {"nombre": f"I{paso}"})
            elif op == "del" and len(ids) > 3:
                self.db.eliminar("clientes", azar.choice(ids))
            elif op == "lote_fallido" and ids:
                with self.assertRaises(RuntimeError):
                    with self.db.lote():
                        self.db.actualizar("clientes", azar.choice(ids), {"zona": "Fallida"})
                        self.db.insertar("clientes", {"nombre": "Fallido"})
                        raise RuntimeError("x")
            elif op == "lote_bueno" and ids:
                with self.db.lote():
                    self.db.actualizar("clientes", azar.choice(ids), {"zona": "Lote"})
                    self.db.insertar("clientes", {"nombre": f"L{paso}"})
            elif op == "nulo" and ids:                                           # NULL escrito desde fuera: se lee como vacío
                elegido = azar.choice(ids)
                self.db.con.execute("UPDATE clientes SET zona = NULL WHERE id = ?", (elegido,))
                self.db.actualizar("clientes", elegido, {"nombre": f"X{paso}"})     # (la misma fila, para que la lea al día)
            elif op == "numero" and ids:                                         # un número en una columna de texto
                self.db.actualizar("clientes", azar.choice(ids), {"zona": 123})
            self.assertEqual(self.db.todos("clientes"), self.leer_todo_de_nuevo("clientes"), f"paso {paso}: {op}")
            for f in self.db.todos("clientes"):
                self.assertIs(self.db.uno("clientes", f["id"]), f)

    def test_editar_no_vuelve_a_leer_toda_la_tabla(self):
        for i in range(50):
            self.db.insertar("clientes", {"nombre": f"C{i}"})
        antes = self.db.todos("clientes")
        lecturas = []
        original = self.db.con.execute

        class Espia:                                                             # cuenta las lecturas de la tabla entera
            def __init__(self, con): self.con = con
            def __getattr__(self, nombre): return getattr(self.con, nombre)
            def execute(self, sql, *a):
                if "ORDER BY id DESC" in sql: lecturas.append(sql)
                return self.con.execute(sql, *a)
        conexion = self.db.con
        self.db.con = Espia(conexion)
        try:
            self.db.actualizar("clientes", 7, {"zona": "Comas"})
            despues = self.db.todos("clientes")
            self.assertEqual(lecturas, [])                                       # no se releyó la tabla
            self.assertIsNot(despues, antes)                                     # pero la lista es nueva (se ve que cambió)
            self.assertEqual(self.db.uno("clientes", 7)["zona"], "Comas")
        finally:
            self.db.con = conexion

    def test_con_demasiados_cambios_o_una_revision_muy_vieja_no_se_sabe(self):
        a = self.db.insertar("clientes", {"nombre": "Ana"})
        vieja = self.db.revision("clientes")
        for i in range(100):
            self.db.actualizar("clientes", a, {"zona": str(i)})
        self.assertIsNone(self.db.cambios_desde("clientes", vieja))              # se perdió el hilo: hay que releer todo


class BusquedaDeAreas(unittest.TestCase):
    def tearDown(self):
        restablecer_areas()

    def buscar(self, texto):
        return filtrar_opciones(texto, agencia.TIPOS_SERVICIO, sinonimos_de_area)

    def test_sin_acentos_ni_mayusculas(self):
        self.assertEqual([sin_acentos(x) for x in ("NIÑERA", "Niñera", "ninera", "Días")], ["ninera"] * 3 + ["dias"])

    def test_sugerencias_mientras_se_escribe(self):
        casos = {"n": ["Niñera", "Cama adentro", "Cocinera"],                              # primero la que empieza igual
                 "nin": ["Niñera"], "NINERA": ["Niñera"], "niñeras": ["Niñera"],       # también por el título
                 "cama": ["Cama adentro", "Cama afuera"], "afuera": ["Cama afuera"], "dias": ["Por días"],
                 "cocina": ["Cocinera"], "adulto": ["Cuidado de adulto mayor"], "mayor": ["Cuidado de adulto mayor"],
                 "zzz": [], "": [], "   ": []}
        for escrito, esperado in casos.items():
            self.assertEqual(self.buscar(escrito), esperado, escrito)

    def test_primero_las_que_empiezan_igual_y_despues_las_que_contienen(self):
        self.assertEqual(filtrar_opciones("ma", ["Cocina mama", "Mascotas", "Amarillo"]),
                         ["Mascotas", "Cocina mama", "Amarillo"])

    def test_area_de_texto_reconoce_nombre_y_titulo(self):
        for escrito, area in {"niñera": "Niñera", "NIÑERAS": "Niñera", "cocina": "Cocinera", "COCINERA": "Cocinera",
                              "cama afuera": "Cama afuera", " por dias ": "Por días", "adulto mayor": "Cuidado de adulto mayor"}.items():
            self.assertEqual(area_de_texto(escrito), area, escrito)
        for escrito in ("", "xyz", "cama", "niñ"):
            self.assertIsNone(area_de_texto(escrito), escrito)                    # a medias no basta: se sugiere, no se adivina

    def test_una_area_creada_tambien_se_encuentra(self):
        agencia.AREAS["Jardinería"] = ("Jardinería", "")
        agencia.TIPOS_SERVICIO.append("Jardinería")
        self.assertEqual(self.buscar("jardin"), ["Jardinería"])
        self.assertEqual(area_de_texto("JARDINERIA"), "Jardinería")


class MesesDeGarantiaVariables(unittest.TestCase):
    def test_textos_de_meses_y_opciones_del_cuestionario(self):
        self.assertEqual([texto_meses(n) for n in (0, 1, 2, 6)], ["Sin garantía", "1 mes", "2 meses", "6 meses"])
        self.assertEqual(agencia.OPCIONES_GARANTIA, [texto_meses(n) for n in range(0, 7)])

    def test_meses_que_pidio_el_cliente_nuevos_y_antiguos(self):
        casos = [({"meses_garantia": "3 meses"}, 3), ({"meses_garantia": "1 mes"}, 1),
                 ({"meses_garantia": "Sin garantía"}, 0), ({"meses_garantia": "", "garantia": "No"}, 0),
                 ({"meses_garantia": "", "garantia": "Sí"}, agencia.MESES_GARANTIA), ({}, agencia.MESES_GARANTIA),
                 ({"meses_garantia": None, "garantia": "No"}, 0), ({"meses_garantia": "12 meses"}, 12)]
        for cliente, esperado in casos:
            self.assertEqual(meses_del_cliente(cliente), esperado, cliente)

    def test_el_plazo_se_escribe_en_letras_y_numero_como_el_resto_del_contrato(self):
        self.assertEqual([numero_en_letras(n) for n in (1, 3, 12, 20, 25, 34, 90, 100, 120)],
                         ["un", "tres", "doce", "veinte", "veinticinco", "treinta y cuatro", "noventa", "cien", "120"])
        c = {"id": 1, "estado": "Activa", "garantia": "Sí", "comision": "300", "sueldo_acordado": "1500",
             "fecha_contrato": "28/09/2026", "reemplazo_de": "", "contrato_firmado": "", "fecha_firma": "",
             "firma_cliente": "", "firma_trabajadora": "", "firma_agencia": "", "puesto": "", "modalidad": "",
             "descanso": ""}
        cli = {"nombre": "A", "dni": "1", "direccion": "", "zona": "", "telefono": "", "ocupacion": "",
               "tipo_servicio": "Niñera", "dias_libres": "", "horario": ""}
        t = {"nombre": "B", "dni": "2", "direccion": "", "zona": ""}
        pagina = lambda meses: html_contrato(dict(c, meses_garantia=str(meses)), cli, t)
        self.assertRegex(pagina(1), r"garantía de <span class=\"campo medio\">un \(1\)</span> mes\b")
        self.assertRegex(pagina(3), r"tres \(3\)</span> meses")
        self.assertRegex(pagina(6), r"seis \(6\)</span> meses")
        self.assertNotIn("dos (2)", pagina(3))
        self.assertIn("sin garantía", html_contrato(dict(c, meses_garantia="0", garantia="No"), cli, t))

    def test_los_clientes_antiguos_pasan_de_si_no_a_meses_sin_perder_nada(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = str(Path(carpeta) / "agencia.db")
            with sqlite3.connect(ruta) as con:
                con.execute("CREATE TABLE clientes (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT DEFAULT '', "
                            "garantia TEXT DEFAULT '')")
                con.executemany("INSERT INTO clientes (nombre, garantia) VALUES (?, ?)",
                                [("Con", "Sí"), ("Sin", "No"), ("Vacio", "")])
            self.assertTrue(esquema_desactualizado(ruta))
            db = BaseDatos(ruta)
            self.assertEqual({c["nombre"]: c["meses_garantia"] for c in db.todos("clientes")},
                             {"Con": "2 meses", "Sin": "Sin garantía", "Vacio": "2 meses"})
            self.assertEqual({c["nombre"]: c["garantia"] for c in db.todos("clientes")},
                             {"Con": "Sí", "Sin": "No", "Vacio": ""})            # el dato viejo no se toca
            sin = next(c for c in db.todos("clientes") if c["nombre"] == "Sin")
            db.actualizar("clientes", sin["id"], {"meses_garantia": "4 meses"})   # lo que elija la persona se respeta
            db.con.close()
            db = BaseDatos(ruta)
            self.assertEqual(db.uno("clientes", sin["id"])["meses_garantia"], "4 meses")
            db.con.close()
            self.assertFalse(esquema_desactualizado(ruta))

    def test_una_base_nueva_no_lleva_la_columna_antigua_y_abre_sin_error(self):
        with tempfile.TemporaryDirectory() as carpeta:
            db = BaseDatos(str(Path(carpeta) / "agencia.db"))
            columnas = {r["name"] for r in db.con.execute("PRAGMA table_info(clientes)")}
            self.assertIn("meses_garantia", columnas)
            self.assertNotIn("garantia", columnas)
            db.insertar("clientes", {"nombre": "Ana", "meses_garantia": "3 meses"})
            db.con.close()

    def test_antes_de_actualizar_la_estructura_se_guarda_una_copia(self):
        with tempfile.TemporaryDirectory() as carpeta:
            base = Path(carpeta)
            ruta = str(base / "agencia.db")
            with sqlite3.connect(ruta) as con:
                con.execute("CREATE TABLE clientes (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT DEFAULT '', "
                            "garantia TEXT DEFAULT '')")
                con.execute("INSERT INTO clientes (nombre, garantia) VALUES ('Ana', 'Sí')")
            with mock.patch.object(agencia, "DB_PATH", ruta), \
                    mock.patch.object(agencia, "CARPETA_RESPALDOS", str(base / "respaldos")), \
                    mock.patch.object(agencia, "carpetas_externas", lambda config=None: []):
                aviso, oferta = agencia.preparar_base()
            self.assertIsNone(aviso)
            copias = listar_copias([(str(base / "respaldos"), "Programa")])
            self.assertEqual([c["tipo"] for c in copias], ["Antes de actualizar"])
            self.assertEqual(copias[0]["clientes"], 1)
            with sqlite3.connect(copias[0]["ruta"]) as con:                    # es la copia de ANTES: estructura vieja
                self.assertNotIn("meses_garantia", [r[1] for r in con.execute("PRAGMA table_info(clientes)")])

    def test_la_pantalla_garantias_muestra_los_meses_de_cada_cliente(self):
        try:
            root = agencia.tk.Tk()
        except agencia.tk.TclError:
            self.skipTest("no hay pantalla disponible")
        root.withdraw()
        with tempfile.TemporaryDirectory() as carpeta, \
                mock.patch.object(agencia, "DB_PATH", str(Path(carpeta) / "agencia.db")), \
                mock.patch.object(agencia, "CARPETA_RESPALDOS", str(Path(carpeta) / "r")), \
                mock.patch.object(agencia, "carpetas_externas", lambda config=None: []):
            try:
                app = agencia.App(root)
                pagina = app.garantias
                base = {"id": 1, "cliente_id": "9", "trabajadora_id": "9", "estado": "Activa", "fecha_inicio": "28/09/2026",
                        "fin_garantia": "28/12/2026", "garantia": "Sí", "reemplazo_de": ""}
                self.assertEqual(pagina.valores(dict(base, meses_garantia="3"))[3], "3 meses")
                self.assertEqual(pagina.valores(dict(base, meses_garantia="1"))[3], "1 mes")
                self.assertEqual(pagina.valores(dict(base, garantia="No", meses_garantia="0"))[3], "-")
                self.assertEqual(len(pagina.columnas), len(pagina.valores(base)))
                self.assertNotIn("2 meses", pagina.subtitulo)
            finally:
                root.update()
                root.destroy()


class ProgramaConDatosProtegidos(unittest.TestCase):
    """El programa completo (ventana oculta) sobre carpetas temporales: nada toca los datos reales."""

    def setUp(self):
        try:
            self.root = agencia.tk.Tk()
        except agencia.tk.TclError:
            self.skipTest("no hay pantalla disponible")
        self.root.withdraw()
        self.temporal = tempfile.TemporaryDirectory()
        base = Path(self.temporal.name)
        self.respaldos, self.externa = str(base / "respaldos"), str(base / "externa")
        self.parches = [
            mock.patch.object(agencia, "DB_PATH", str(base / "agencia.db")),
            mock.patch.object(agencia, "CARPETA_RESPALDOS", self.respaldos),
            mock.patch.object(agencia, "CONFIG_PATH", str(base / "configuracion.json")),
            mock.patch.object(agencia, "carpetas_externas", lambda config=None: [self.externa]),
            mock.patch.object(agencia.tk.Toplevel, "grab_set", lambda self: None)]
        for parche in self.parches:
            parche.start()
        self.respuestas = {"askyesno": True, "askyesnocancel": True}
        self.mensajes = []
        for nombre in ("askyesno", "askyesnocancel"):
            p = mock.patch.object(agencia.messagebox, nombre, side_effect=lambda titulo, texto, _n=nombre, **k:
                                  (self.mensajes.append((titulo, texto)), self.respuestas[_n])[1])
            p.start(); self.parches.append(p)
        for nombre in ("showinfo", "showwarning", "showerror"):
            p = mock.patch.object(agencia.messagebox, nombre, side_effect=lambda titulo, texto, **k:
                                  self.mensajes.append((titulo, texto)))
            p.start(); self.parches.append(p)
        self.app = agencia.App(self.root)
        self.clientes = self.app.clientes

    def tearDown(self):
        for parche in reversed(self.parches):
            parche.stop()
        restablecer_areas()
        try:
            self.root.update()      # deja terminar las tareas pendientes antes de destruir la ventana
            self.root.destroy()
        except agencia.tk.TclError:
            pass
        self.temporal.cleanup()

    def escribir_cliente(self, nombre="Ana", telefono="999"):
        self.clientes.form.poner_valor("nombre", nombre)
        self.clientes.form.poner_valor("telefono", telefono)

    def cliente_guardado(self, nombre="Ana"):
        self.escribir_cliente(nombre)
        self.assertTrue(self.clientes.guardar())
        return self.clientes.id_actual

    def test_un_formulario_intacto_no_pide_guardar_y_uno_editado_si(self):
        self.assertFalse(self.clientes.cambios_sin_guardar())
        self.escribir_cliente()
        self.assertTrue(self.clientes.cambios_sin_guardar())
        id_ = self.cliente_guardado()
        self.assertFalse(self.clientes.cambios_sin_guardar())
        self.clientes.form.poner_valor("zona", "Lince")
        self.assertTrue(self.clientes.cambios_sin_guardar())
        self.clientes.form.poner_valor("zona", "")
        self.assertFalse(self.clientes.cambios_sin_guardar())
        # una trabajadora guardada sin marcar documentos (vacío en la base) no cuenta como cambio
        t = self.app.trabajadoras
        tid = self.app.db.insertar("trabajadoras", {"nombre": "Rosa", "telefono": "1"})
        self.app.refrescar_todo()
        t.seleccionar(tid); t.al_seleccionar()
        self.assertFalse(t.cambios_sin_guardar())
        self.assertEqual(id_, self.clientes.id_actual)

    def sin_avisos(self):
        return [m for m in self.mensajes if m[0] in ("Cambios sin guardar", "Revise los datos")]

    def test_los_cambios_se_guardan_solos_al_pasar_a_otro_registro_sin_ningun_aviso(self):
        a = self.cliente_guardado("Ana")
        self.clientes.nuevo()
        b = self.cliente_guardado("Beto")
        self.root.update()
        self.clientes.lista.selection_set(str(a)); self.root.update()
        self.assertEqual(self.clientes.id_actual, a)
        self.clientes.form.poner_valor("zona", "Comas")                                   # edita a Ana y elige a Beto sin guardar
        self.clientes.lista.selection_set(str(b)); self.root.update()
        self.assertEqual(self.clientes.id_actual, b)                                      # pasó a Beto...
        self.assertEqual(self.app.db.uno("clientes", a)["zona"], "Comas")                 # ...y lo de Ana se guardó solo
        self.clientes.form.poner_valor("zona", "Ate")
        self.clientes.lista.selection_set(str(a)); self.root.update()
        self.assertEqual(self.app.db.uno("clientes", b)["zona"], "Ate")
        self.assertEqual((self.clientes.id_actual, self.clientes.form.valor("zona")), (a, "Comas"))
        self.assertEqual(self.sin_avisos(), [])                                           # nunca se preguntó nada

    def test_un_registro_nuevo_completo_se_crea_solo_al_dejarlo(self):
        self.escribir_cliente("Luis")
        self.clientes.form.poner_valor("zona", "Lince")
        self.clientes.resolver_cambios()
        filas = self.app.db.todos("clientes")
        self.assertEqual([(f["nombre"], f["zona"], f["estado"]) for f in filas], [("Luis", "Lince", "Pendiente")])
        self.assertIsNone(self.clientes.borrador)
        self.assertEqual(self.sin_avisos(), [])

    def test_lo_escrito_en_un_registro_incompleto_queda_como_borrador_sin_avisos(self):
        self.clientes.form.poner_valor("zona", "Lince")                                   # falta nombre y teléfono
        self.clientes.form.poner_valor("sueldo_ofrecido", "1800")
        self.clientes.resolver_cambios()
        self.assertEqual(self.app.db.todos("clientes"), [])                               # no se creó nada incompleto
        self.assertEqual(self.sin_avisos(), [])                                           # y no se molestó con avisos
        self.assertEqual(self.clientes.borrador["zona"], "Lince")
        a = self.cliente_guardado_aparte("Ana")                                           # se va a otro registro...
        self.clientes.lista.selection_remove(*self.clientes.lista.selection())
        self.clientes.nuevo()                                                             # ...y al volver a «Nuevo» está lo escrito
        self.assertEqual((self.clientes.form.valor("zona"), self.clientes.form.valor("sueldo_ofrecido")), ("Lince", "1800"))
        self.escribir_cliente("Beto")                                                     # se completa y se guarda: el borrador se va
        self.assertTrue(self.clientes.guardar())
        self.assertIsNone(self.clientes.borrador)
        self.assertEqual(self.app.db.uno("clientes", self.clientes.id_actual)["zona"], "Lince")
        self.assertFalse(os.path.exists(agencia.ruta_borradores()))

    def cliente_guardado_aparte(self, nombre):
        """Un cliente ya guardado, sin tocar el formulario que se está escribiendo."""
        return self.app.db.insertar("clientes", {"nombre": nombre, "telefono": "1", "estado": "Pendiente"})

    def test_un_cambio_invalido_en_un_registro_que_ya_existe_no_lo_estropea(self):
        cid = self.cliente_guardado("Ana")
        self.clientes.form.poner_valor("nombre", "")                                      # se borra un dato obligatorio
        self.clientes.form.poner_valor("zona", "Comas")
        self.clientes.resolver_cambios()
        self.assertEqual(self.app.db.uno("clientes", cid)["nombre"], "Ana")               # sigue como estaba
        self.assertEqual(self.sin_avisos(), [])

    def test_al_pulsar_nuevo_lo_que_se_editaba_se_guarda_solo(self):
        cid = self.cliente_guardado("Ana")
        self.clientes.form.poner_valor("zona", "Comas")
        self.clientes.vista_actual = "lista"
        self.clientes.elegir_pestana("ficha")                                             # pestaña «Nuevo cliente»
        self.assertEqual(self.app.db.uno("clientes", cid)["zona"], "Comas")
        self.assertIsNone(self.clientes.id_actual)
        self.assertEqual(self.sin_avisos(), [])

    def test_al_cerrar_lo_escrito_se_guarda_solo_y_no_se_pregunta_nada(self):
        self.escribir_cliente("Luis")
        self.app.cerrar()
        with sqlite3.connect(agencia.DB_PATH) as con:
            self.assertEqual(con.execute("SELECT nombre FROM clientes").fetchone()[0], "Luis")
        self.assertEqual(self.sin_avisos(), [])
        with self.assertRaises(agencia.tk.TclError):
            self.root.winfo_exists()

    def test_el_borrador_sobrevive_al_cierre_y_reaparece_al_abrir_el_programa(self):
        self.clientes.form.poner_valor("zona", "Lince")
        self.clientes.form.poner_valor("ninos", "2 niños")
        self.app.cerrar()                                                                 # incompleto: queda como borrador
        self.assertTrue(os.path.exists(agencia.ruta_borradores()))
        self.assertEqual(self.sin_avisos(), [])
        raiz = agencia.tk.Tk()
        raiz.withdraw()
        try:
            otra = agencia.App(raiz)                                                      # se abre el programa otra vez
            self.assertEqual((otra.clientes.form.valor("zona"), otra.clientes.form.valor("ninos")), ("Lince", "2 niños"))
            self.assertEqual(otra.db.todos("clientes"), [])
            raiz.update()
        finally:
            raiz.destroy()

    def test_un_archivo_de_borradores_roto_no_impide_abrir(self):
        Path(agencia.ruta_borradores()).write_text("{ no es json")
        raiz = agencia.tk.Tk()
        raiz.withdraw()
        try:
            otra = agencia.App(raiz)
            self.assertEqual(otra.clientes.form.valor("zona"), "")
            raiz.update()
        finally:
            raiz.destroy()

    def asignacion_cobrada(self):
        cid = self.cliente_guardado("Ana")
        tid = self.app.db.insertar("trabajadoras", {"nombre": "Rosa", "telefono": "1"})
        aid = self.app.db.insertar("colocaciones", {
            "cliente_id": str(cid), "trabajadora_id": str(tid), "estado": "Activa", "comision": "300.00",
            "comision_pagada": "1", "fecha_pago": "28/09/2026", "contrato_firmado": "1"})
        self.app.refrescar_todo()
        return cid, tid, aid

    def test_borrar_avisa_de_lo_que_se_pierde_y_deja_una_copia_para_recuperarlo(self):
        cid, tid, aid = self.asignacion_cobrada()
        self.clientes.seleccionar(cid); self.clientes.al_seleccionar()
        self.clientes.eliminar()
        aviso = self.mensajes[-1][1]
        self.assertIn("1 comisión cobrada", aviso)
        self.assertIn("S/ 300.00", aviso)
        self.assertIn("1 contrato firmado", aviso)
        self.assertIn("copia de seguridad", aviso)
        self.assertEqual(self.app.db.todos("clientes"), [])
        self.assertEqual(self.app.db.todos("colocaciones"), [])
        previas = [c for c in listar_copias([(self.respaldos, "Programa")]) if c["tipo"] == "Antes de borrar"]
        self.assertEqual(len(previas), 1)
        self.assertEqual((previas[0]["clientes"], previas[0]["colocaciones"]), (1, 1))
        # y desde la copia se recupera todo, comisión cobrada incluida
        self.assertTrue(self.app.restaurar_copia(previas[0]))
        self.assertEqual([c["nombre"] for c in self.app.db.todos("clientes")], ["Ana"])
        self.assertEqual(self.app.db.todos("colocaciones")[0]["comision_pagada"], "1")

    def test_no_se_borra_si_la_persona_dice_que_no(self):
        cid = self.cliente_guardado("Ana")
        self.respuestas["askyesno"] = False
        self.clientes.eliminar()
        self.assertEqual(len(self.app.db.todos("clientes")), 1)

    def test_si_no_se_puede_hacer_la_copia_previa_no_se_borra_sin_permiso(self):
        cid = self.cliente_guardado("Ana")
        self.respuestas["askyesno"] = True
        with mock.patch.object(agencia, "respaldar", return_value={"archivo": None, "externas": [],
                                                                    "errores": ["disco lleno"], "omitido": None}):
            self.assertTrue(self.app.copia_antes_de_borrar())      # responde «sí, borrar igualmente»
            self.respuestas["askyesno"] = False
            self.assertFalse(self.app.copia_antes_de_borrar())     # responde «no»
        self.assertIn("disco lleno", self.mensajes[-1][1])

    def test_deshacer_asignacion_tambien_hace_copia_previa(self):
        cid, tid, aid = self.asignacion_cobrada()
        contratos = self.app.contratos
        contratos.deshacer(self.app.db.uno("colocaciones", aid))
        self.assertIn("comisión cobrada", self.mensajes[-1][1])
        self.assertEqual(self.app.db.todos("colocaciones"), [])
        self.assertEqual(len(self.nombres_de_copia("antes-de-borrar")), 1)

    def nombres_de_copia(self, tipo):
        if not os.path.isdir(self.respaldos):
            return []                                # todavía no se hizo ninguna copia
        return [n for n in os.listdir(self.respaldos) if n.startswith(f"agencia-{tipo}-")]

    def test_al_cerrar_queda_una_copia_al_dia_dentro_y_fuera_del_programa(self):
        self.cliente_guardado("Ana")
        self.app.cerrar()
        self.assertEqual(len(self.nombres_de_copia("auto")), 1)
        externas = [n for n in os.listdir(self.externa) if n.endswith(".db")]
        self.assertEqual(len(externas), 1)
        self.assertTrue(os.path.exists(os.path.join(self.externa, "Datos legibles", "Clientes.csv")))

    def test_restaurar_guarda_antes_lo_que_habia_y_limpia_los_formularios(self):
        self.cliente_guardado("Ana")
        copia = self.app.hacer_copia("manual")
        self.clientes.nuevo()
        self.cliente_guardado("Beto")
        copias = listar_copias([(self.respaldos, "Programa")])
        elegida = next(c for c in copias if c["tipo"] == "Manual")
        self.assertTrue(self.app.restaurar_copia(elegida))
        self.assertEqual([c["nombre"] for c in self.app.db.todos("clientes")], ["Ana"])
        previa = [c for c in listar_copias([(self.respaldos, "Programa")]) if c["tipo"] == "Antes de restaurar"]
        self.assertEqual(previa[0]["clientes"], 2)                    # lo que había (Ana y Beto) quedó guardado
        self.assertIsNone(self.clientes.id_actual)

    def test_ofrecer_recuperacion_cuando_el_programa_esta_vacio(self):
        self.cliente_guardado("Ana")
        self.app.hacer_copia("auto")
        self.app.db.eliminar("clientes", self.clientes.id_actual)
        self.app.refrescar_todo()
        oferta = buscar_restauracion(agencia.DB_PATH, [(self.respaldos, "Programa")])
        self.assertEqual(oferta["clientes"], 1)
        self.respuestas["askyesno"] = False                           # «No, gracias»: no toca nada
        self.app.ofrecer_recuperacion(oferta)
        self.assertEqual(self.app.db.todos("clientes"), [])
        self.respuestas["askyesno"] = True
        self.app.ofrecer_recuperacion(oferta)
        self.assertEqual([c["nombre"] for c in self.app.db.todos("clientes")], ["Ana"])

    def asignar_con(self, meses_guardados):
        self.clientes.nuevo()
        self.escribir_cliente("Ana")
        self.assertNotIn("meses_garantia", self.clientes.form.tipos)            # ya no se pide en el formulario
        self.assertNotIn("estado", self.clientes.form.tipos)
        self.assertTrue(self.clientes.guardar())
        cid = self.clientes.id_actual
        self.assertEqual(self.app.db.uno("clientes", cid)["estado"], "Pendiente")   # lo completa el propio programa
        if meses_guardados:                                                     # dato guardado por versiones anteriores
            self.app.db.actualizar("clientes", cid, {"meses_garantia": meses_guardados})
        return self.asignar_cliente_guardado(cid)

    def asignar_cliente_guardado(self, cid):
        tid = self.app.db.insertar("trabajadoras", {"nombre": "Rosa", "telefono": "1", "estado": "Disponible"})
        self.app.refrescar_todo()
        self.app.abrir_area(None)
        enlazar = self.app.enlazar
        enlazar.t_clientes.selection_set(str(cid))
        enlazar.cargar_candidatas()
        enlazar.t_trab.selection_set(str(tid))
        mostrados = []

        def dialogo(master, numero, valores, al_guardar, nombres=None):
            mostrados.append(dict(valores))
            al_guardar(dict(valores))
        with mock.patch.object(agencia, "DialogoContrato", dialogo):
            enlazar.asignar()
        return mostrados[0], self.app.db.todos("colocaciones")[0]

    def test_los_meses_de_garantia_se_proponen_en_el_contrato_y_alli_se_cambian(self):
        for guardado, meses, garantia in ((None, "2", "Sí"), ("3 meses", "3", "Sí"), ("Sin garantía", "0", "No")):
            self.tearDown(); self.setUp()
            en_dialogo, asignacion = self.asignar_con(guardado)
            self.assertEqual(en_dialogo["meses_garantia"], meses)             # lo que aparece en el diálogo del contrato
            self.assertEqual((asignacion["meses_garantia"], asignacion["garantia"]), (meses, garantia))

    def crear_area(self, nombre):
        preguntas = []

        def pedir(parent, titulo, pregunta, *a, **k):
            preguntas.append(pregunta)
            return nombre
        with mock.patch.object(agencia, "pedir_texto", pedir):
            self.app.nueva_area()
        self.assertLessEqual(len(preguntas), 1)                     # solo se pide el nombre, nada más

    def test_una_area_nueva_aparece_en_los_cuadros_y_en_los_desplegables(self):
        self.assertEqual(len(self.app.areas.tarjetas.winfo_children()), 6)
        self.crear_area("Jardinería")
        self.assertIn("Jardinería", agencia.AREAS)
        self.assertEqual(agencia.AREAS["Jardinería"], ("Jardinería", ""))
        self.assertEqual(len(self.app.areas.tarjetas.winfo_children()), 7)                 # un cuadro más
        for formulario in (self.clientes.form, self.app.trabajadoras.form):                # «Tipo de servicio» y «Especialidad»
            self.assertIn("Jardinería", formulario.widgets["tipo_servicio"]["values"])
            self.assertEqual(list(formulario.widgets["tipo_servicio"]["values"]), agencia.TIPOS_SERVICIO)
        self.assertEqual([f["nombre"] for f in self.app.db.todos("areas")].count("Jardinería"), 1)
        # se puede usar de verdad: un cliente y una trabajadora de esa área aparecen al asignar
        self.escribir_cliente("Ana")
        self.clientes.form.poner_valor("tipo_servicio", "Jardinería")
        self.assertTrue(self.clientes.guardar())
        self.app.abrir_area("Jardinería")
        self.assertEqual(self.app.enlazar.lbl_titulo.cget("text"), "Jardinería")
        self.assertEqual(len(self.app.enlazar.t_clientes.get_children()), 1)

    def test_no_se_crean_areas_repetidas_vacias_ni_demasiado_largas(self):
        antes = len(self.app.db.todos("areas"))
        for nombre in ("", "   ", "niñera", "NIÑERAS", "Cocina", "x" * 41):
            self.crear_area(nombre)
        self.assertEqual(len(self.app.db.todos("areas")), antes)
        self.assertGreaterEqual(len(self.mensajes), 6)
        self.crear_area("  Mascotas   y   plantas ")                                     # los espacios de más se limpian
        self.assertIn("Mascotas y plantas", agencia.AREAS)

    def test_cancelar_al_crear_un_area_no_deja_nada(self):
        antes = len(self.app.db.todos("areas"))
        with mock.patch.object(agencia, "pedir_texto", lambda *a, **k: None):
            self.app.nueva_area()
        self.assertEqual(len(self.app.db.todos("areas")), antes)

    def test_eliminar_un_area_sin_uso_la_quita_de_todos_lados_y_deja_una_copia(self):
        self.crear_area("Jardinería")
        self.assertTrue(self.app.eliminar_area("Jardinería"))
        self.assertNotIn("Jardinería", agencia.AREAS)
        self.assertNotIn("Jardinería", self.clientes.form.widgets["tipo_servicio"]["values"])
        self.assertEqual(len(self.app.areas.tarjetas.winfo_children()), 6)
        primeras = self.nombres_de_copia("antes-de-borrar")
        self.assertEqual(len(primeras), 1)                           # las áreas creadas también son datos propios
        con = sqlite3.connect(Path(self.respaldos) / primeras[0])
        try:
            self.assertEqual(con.execute("SELECT nombre FROM areas WHERE nombre = 'Jardinería'").fetchone(),
                             ("Jardinería",))
        finally:
            con.close()
        self.cliente_guardado("Ana")
        self.crear_area("Mascotas")
        self.assertTrue(self.app.eliminar_area("Mascotas"))
        posteriores = self.nombres_de_copia("antes-de-borrar")
        self.assertGreaterEqual(len(posteriores), 1)
        recuperable = False
        for nombre in posteriores:
            con = sqlite3.connect(Path(self.respaldos) / nombre)
            try:
                recuperable |= (con.execute("SELECT nombre FROM areas WHERE nombre = 'Mascotas'").fetchone() ==
                                ("Mascotas",) and con.execute("SELECT nombre FROM clientes").fetchone() == ("Ana",))
            finally:
                con.close()
        self.assertTrue(recuperable)                                  # la copia contiene el área y el cliente anteriores

    def test_no_se_elimina_un_area_que_tiene_clientes_o_trabajadoras(self):
        self.escribir_cliente("Ana")
        self.clientes.form.poner_valor("tipo_servicio", "Niñera")
        self.assertTrue(self.clientes.guardar())
        self.app.db.insertar("trabajadoras", {"nombre": "Rosa", "telefono": "1", "tipo_servicio": "Niñera"})
        self.assertFalse(self.app.eliminar_area("Niñera"))
        self.assertIn("1 cliente y 1 trabajadora", self.mensajes[-1][1])
        self.assertIn("Niñera", agencia.AREAS)
        self.assertIn("Niñera", [f["nombre"] for f in self.app.db.todos("areas")])

    def test_siempre_queda_al_menos_un_area(self):
        for nombre in list(agencia.AREAS)[:-1]:
            self.assertTrue(self.app.eliminar_area(nombre))
        self.assertFalse(self.app.eliminar_area(list(agencia.AREAS)[0]))
        self.assertIn("al menos un área", self.mensajes[-1][1])
        self.assertEqual(len(agencia.AREAS), 1)

    def test_restaurar_una_copia_devuelve_las_areas_de_esa_copia(self):
        self.cliente_guardado("Ana")
        self.app.hacer_copia("manual")
        self.crear_area("Jardinería")
        self.assertIn("Jardinería", self.clientes.form.widgets["tipo_servicio"]["values"])
        elegida = next(c for c in listar_copias([(self.respaldos, "Programa")]) if c["tipo"] == "Manual")
        self.assertTrue(self.app.restaurar_copia(elegida))
        self.assertNotIn("Jardinería", agencia.AREAS)
        self.assertNotIn("Jardinería", self.clientes.form.widgets["tipo_servicio"]["values"])
        self.assertEqual(len(self.app.areas.tarjetas.winfo_children()), 6)

    def test_el_formulario_del_cliente_no_pide_garantia_ni_estado_pero_el_programa_los_maneja(self):
        for oculto in ("estado", "meses_garantia", "garantia"):
            self.assertNotIn(oculto, self.clientes.form.tipos)
        self.escribir_cliente("Ana")
        self.assertTrue(self.clientes.guardar())
        cid = self.clientes.id_actual
        self.assertEqual(self.app.db.uno("clientes", cid)["estado"], "Pendiente")
        self.app.db.actualizar("clientes", cid, {"estado": "Colocado"})                  # lo cambia el flujo de asignación
        self.app.refrescar_todo()
        self.clientes.seleccionar(cid); self.clientes.al_seleccionar()
        self.clientes.form.poner_valor("zona", "Lince")
        self.assertTrue(self.clientes.guardar())                                          # editar otros datos no lo pisa
        self.assertEqual(self.app.db.uno("clientes", cid)["estado"], "Colocado")
        self.assertEqual(self.app.db.uno("clientes", cid)["zona"], "Lince")
        self.assertFalse(self.clientes.cambios_sin_guardar())

    def campo_servicio(self, formulario=None):
        return (formulario or self.clientes.form).widgets["tipo_servicio"]

    def escribir_en(self, campo, texto):
        from types import SimpleNamespace
        campo.set(texto)
        campo._tecla(SimpleNamespace(keysym=texto[-1] if texto else "BackSpace"))

    def test_el_tipo_de_servicio_se_escribe_y_sugiere_y_tambien_abre_la_lista_completa(self):
        for formulario in (self.clientes.form, self.app.trabajadoras.form):               # Tipo de servicio y Especialidad
            campo = self.campo_servicio(formulario)
            self.assertIsInstance(campo, agencia.ComboAutocompletar)
            self.assertEqual(str(campo.cget("state")), "normal")                          # se puede escribir
            self.assertEqual(campo.opciones(), agencia.TIPOS_SERVICIO)                    # y la lista completa sigue ahí
        campo = self.campo_servicio()
        self.escribir_en(campo, "cam")
        self.assertTrue(campo.lista.winfo_manager())
        self.assertEqual(list(campo.lista.get(0, "end")), ["Cama adentro", "Cama afuera"])
        self.escribir_en(campo, "camax")
        self.assertFalse(campo.lista.winfo_manager())                                        # sin coincidencias: se cierra
        self.escribir_en(campo, "")
        self.assertFalse(campo.lista.winfo_manager())

    def test_las_sugerencias_nunca_quedan_pegadas_al_salir_del_campo(self):
        from types import SimpleNamespace
        campo = self.campo_servicio()
        # 1) clic en cualquier otra parte (un fondo no le quita el foco al campo)
        self.escribir_en(campo, "c")
        self.assertTrue(campo.lista.winfo_manager())
        campo._clic_fuera(SimpleNamespace(widget=campo.lista))                            # clic en la propia lista: sigue
        self.assertTrue(campo.lista.winfo_manager())
        campo._clic_fuera(SimpleNamespace(widget=self.clientes))                          # clic en otro lado: se cierra
        self.assertFalse(campo.lista.winfo_manager())
        # 2) mientras el campo tiene el teclado siguen abiertas y se sigue vigilando
        self.escribir_en(campo, "c")
        with mock.patch.object(campo, "_tiene_foco", return_value=True):
            campo._vigilar()
            self.assertTrue(campo.lista.winfo_manager())
            self.assertIsNotNone(campo._tarea)
        # 3) el campo pierde el teclado: se cierran; pero si el foco solo parpadea y vuelve, siguen
        foco = iter([False, True, False, False])
        with mock.patch.object(campo, "_tiene_foco", side_effect=lambda: next(foco)):
            campo._vigilar(); campo._vigilar()
            self.assertTrue(campo.lista.winfo_manager())                                  # falló, volvió: sigue abierta
            campo._vigilar(); campo._vigilar()
        self.assertFalse(campo.lista.winfo_manager())
        self.assertIsNone(campo._tarea)                                                   # y se deja de vigilar
        # 4) al borrar todo lo escrito, o si ya no hay coincidencias, también se cierran
        self.escribir_en(campo, "f")
        self.assertTrue(campo.lista.winfo_manager())
        self.escribir_en(campo, "fa")                                                     # «fa» ya no coincide con nada
        self.assertFalse(campo.lista.winfo_manager())
        self.escribir_en(campo, "c")
        self.escribir_en(campo, "")
        self.assertFalse(campo.lista.winfo_manager())

    def test_las_sugerencias_van_dentro_del_formulario_junto_al_campo_y_no_encima(self):
        campo = self.campo_servicio()
        self.escribir_en(campo, "c")
        self.assertEqual(campo.lista.winfo_manager(), "pack")                             # forma parte del formulario
        self.assertIs(campo.lista.master, campo.master)                                   # en la misma celda del campo
        orden = campo.master.pack_slaves()
        self.assertEqual(orden.index(campo.lista), orden.index(campo) + 1)                # justo debajo del campo
        self.assertEqual(campo.lista.cget("height"), len(campo.sugeridas))                # tantas líneas como sugerencias
        self.campo_servicio().event_generate("<Escape>")
        campo._cerrar()
        self.assertFalse(campo.lista.winfo_manager())

    def test_al_cambiar_de_pantalla_las_sugerencias_se_cierran_y_el_teclado_deja_el_campo(self):
        campo = self.campo_servicio()
        campo.focus_force()
        self.escribir_en(campo, "c")
        self.assertTrue(campo.lista.winfo_manager())
        self.app.mostrar(self.app.areas)                       # las pantallas están apiladas: el campo no debe quedar activo
        self.assertNotEqual(str(self.root.tk.call("focus")), str(campo))
        campo._vigilar(); campo._vigilar()                     # (en la ventana real también se cierra al perder el foco)
        self.assertFalse(campo.lista.winfo_manager())

    def test_elegir_una_sugerencia_con_el_teclado_o_con_el_raton(self):
        campo = self.campo_servicio()
        self.assertEqual(campo._mover(-1), "break")                                       # Arriba sin lista: no hace nada
        self.assertFalse(campo.lista is not None and campo.lista.winfo_manager())
        self.assertEqual(campo._mover(1), "break")                                        # Abajo sin lista: muestra todas
        self.assertEqual(campo.sugeridas, agencia.TIPOS_SERVICIO)
        self.assertEqual(campo.lista.winfo_manager(), "pack")
        campo._cerrar()
        self.escribir_en(campo, "cama")
        self.assertEqual(campo._mover(1), "break")
        self.assertEqual(campo._mover(1), "break")
        self.assertEqual(campo._mover(1), "break")                                        # da la vuelta: 1.º, 2.º, 1.º
        self.assertEqual(campo._aceptar(None), "break")
        self.assertEqual(campo.get(), "Cama adentro")
        self.assertFalse(campo.lista.winfo_manager())
        self.escribir_en(campo, "cama")
        campo._mover(-1)                                                                  # desde arriba: la última
        campo._aceptar(None)
        self.assertEqual(campo.get(), "Cama afuera")
        self.escribir_en(campo, "nin")
        from types import SimpleNamespace
        self.assertEqual(campo._clic(SimpleNamespace(y=2)), "break")                      # clic en la primera
        self.assertEqual(campo.get(), "Niñera")
        self.escribir_en(campo, "coc")
        self.assertEqual(campo._aceptar(None), "break")                                   # Enter sin mover: la primera
        self.assertEqual(campo.get(), "Cocinera")
        self.assertIsNone(campo._aceptar(None))                                           # sin sugerencias: Enter no hace nada

    def test_al_salir_del_campo_se_completa_o_corrige_lo_escrito(self):
        campo = self.campo_servicio()
        with mock.patch.object(campo, "_foco_actual", return_value=".otro_campo"):        # el foco pasó a otro campo
            for escrito, esperado in (("nin", "Niñera"), ("COCINA", "Cocinera"), ("cama afuera", "Cama afuera"),
                                      ("cama", "cama"), ("xyz", "xyz"), ("", "")):        # ambiguo o desconocido: no se toca
                campo.set(escrito)
                campo._completar()
                self.assertEqual(campo.get(), esperado, escrito)

    def test_un_parpadeo_del_foco_no_reescribe_lo_que_se_esta_escribiendo(self):
        campo = self.campo_servicio()
        for foco in ("", str(campo)):              # el foco salió un instante de la aplicación, o sigue en el campo
            with mock.patch.object(campo, "_foco_actual", return_value=foco):
                campo.set("Niñer")                  # a medias, mientras se borra o se escribe
                campo._completar()
                self.assertEqual(campo.get(), "Niñer", repr(foco))
                campo.set("nin")
                campo._completar()
                self.assertEqual(campo.get(), "nin", repr(foco))

    def test_el_menu_nativo_de_macos_nunca_se_abre_y_el_clic_solo_sirve_para_escribir(self):
        from types import SimpleNamespace
        campo = self.campo_servicio()
        self.root.tk.eval("set ::abiertos 0; proc ttk::combobox::Post {w} {incr ::abiertos}")   # cuenta las aperturas nativas
        # clics reales en toda la superficie del campo, con todas las variantes: nada abre el menú nativo
        for x in range(0, 120, 8):
            for y in range(0, 44, 4):
                campo.event_generate("<Shift-Button-1>", x=x, y=y)
                for _ in range(3):                                                        # clic, doble clic y triple clic
                    campo.event_generate("<Button-1>", x=x, y=y)
        self.assertEqual(int(self.root.tk.eval("set ::abiertos")), 0)
        # un clic fuera de la flecha (borde, relleno o texto) solo coloca el cursor: cierra sugerencias y no muestra la lista
        for elemento in ("Combobox.padding", "Combobox.textarea", "Combobox.field", ""):
            self.escribir_en(campo, "c")
            with mock.patch.object(campo, "_elemento", return_value=elemento):
                self.assertEqual(campo._pulsar(SimpleNamespace(x=3, y=3)), "break")
            self.assertFalse(campo.lista.winfo_manager(), elemento)
        # la flecha sí muestra la lista completa (dentro del formulario) y otro clic en la flecha la oculta
        with mock.patch.object(campo, "_elemento", return_value="Combobox.downarrow"):
            campo._pulsar(SimpleNamespace(x=500, y=20))
            self.assertEqual(campo.lista.winfo_manager(), "pack")
            self.assertEqual(campo.sugeridas, agencia.TIPOS_SERVICIO)
            campo._pulsar(SimpleNamespace(x=500, y=20))
            self.assertFalse(campo.lista.winfo_manager())
        campo._alternar_lista()                                                           # Alt+Abajo hace lo mismo
        self.assertEqual(campo.lista.winfo_manager(), "pack")
        self.assertEqual(int(self.root.tk.eval("set ::abiertos")), 0)

    def test_al_guardar_solo_se_aceptan_areas_reales_y_se_guarda_su_nombre(self):
        self.escribir_cliente("Ana")
        self.clientes.form.poner_valor("tipo_servicio", "NINERAS")
        self.assertTrue(self.clientes.guardar())
        self.assertEqual(self.app.db.uno("clientes", self.clientes.id_actual)["tipo_servicio"], "Niñera")
        self.assertEqual(self.clientes.form.valor("tipo_servicio"), "Niñera")
        self.assertFalse(self.clientes.cambios_sin_guardar())
        self.clientes.nuevo()
        self.escribir_cliente("Beto")
        self.clientes.form.poner_valor("tipo_servicio", "Astronauta")
        self.assertFalse(self.clientes.guardar())
        self.assertIn("«Astronauta» no es un área", self.mensajes[-1][1])
        self.assertEqual(len(self.app.db.todos("clientes")), 1)
        self.clientes.form.poner_valor("tipo_servicio", "")                                # sin área también se puede guardar
        self.assertTrue(self.clientes.guardar())

    def test_la_trabajadora_tambien_valida_su_especialidad(self):
        t = self.app.trabajadoras
        t.form.poner_valor("nombre", "Rosa"); t.form.poner_valor("telefono", "1")
        t.form.poner_valor("tipo_servicio", "cocina")
        self.assertTrue(t.guardar())
        self.assertEqual(self.app.db.uno("trabajadoras", t.id_actual)["tipo_servicio"], "Cocinera")
        t.nuevo()
        t.form.poner_valor("nombre", "Ana"); t.form.poner_valor("telefono", "2")
        t.form.poner_valor("tipo_servicio", "nada")
        self.assertFalse(t.guardar())

    def test_las_sugerencias_incluyen_las_areas_nuevas(self):
        self.crear_area("Jardinería")
        campo = self.campo_servicio()
        self.escribir_en(campo, "jar")
        self.assertEqual(list(campo.lista.get(0, "end")), ["Jardinería"])
        self.eliminar_y_verificar = self.app.eliminar_area("Jardinería")
        self.escribir_en(campo, "jar")
        self.assertFalse(campo.lista.winfo_manager())

    def foto_lista(self, pagina):
        return [(iid, tuple(pagina.lista.item(iid, "values")), tuple(pagina.lista.item(iid, "tags")))
                for iid in pagina.lista.get_children()]

    def reconstruir_lista(self, pagina):
        pagina._lista_fuente = pagina._lista_render_fuente = None
        pagina.cargar_lista()

    def crear_clientes(self, n):
        for i in range(n):
            self.app.db.insertar("clientes", {"nombre": f"Cliente {i}", "telefono": f"9{i:03d}", "zona": "Lince",
                                              "estado": "Pendiente", "tipo_servicio": "Niñera"})
        self.app.refrescar_todo()
        self.root.update()

    def test_al_editar_un_cliente_la_lista_actualiza_solo_esa_fila_y_queda_como_reconstruida(self):
        self.crear_clientes(25)
        p = self.clientes
        llamadas = []
        original = p.valores_fila
        with mock.patch.object(p, "valores_fila", side_effect=lambda f: (llamadas.append(f["id"]), original(f))[1]):
            self.app.db.actualizar("clientes", 7, {"zona": "Comas", "nombre": "Nombre nuevo"})
            self.app.db.actualizar("clientes", 12, {"telefono": "999"})
            self.app.db.actualizar("clientes", 7, {"zona": "Ate"})               # la misma fila dos veces
            p.cargar_lista()
        self.assertEqual(sorted(llamadas), [7, 12])                                       # solo las editadas, no las 25
        incremental = self.foto_lista(p)
        self.assertIn("Nombre nuevo", " ".join(incremental[[f[0] for f in incremental].index("7")][1]))
        self.reconstruir_lista(p)
        self.assertEqual(incremental, self.foto_lista(p))                                 # idéntica a reconstruirla toda

    def test_la_lista_siempre_coincide_con_una_reconstruccion_completa_en_operaciones_al_azar(self):
        import random
        azar = random.Random(5)
        self.crear_clientes(30)
        p = self.clientes
        for paso in range(60):
            ids = [f["id"] for f in self.app.db.todos("clientes")]
            operacion = azar.choice(["editar"] * 6 + ["insertar", "borrar", "lote_fallido", "buscar"])
            busqueda = ""
            if operacion == "editar":
                for _ in range(azar.randint(1, 3)):
                    self.app.db.actualizar("clientes", azar.choice(ids), {"zona": azar.choice(["Lince", "Ate", "Comas"]),
                                                                          "nombre": f"Nombre {azar.randint(0, 99)}"})
            elif operacion == "insertar":
                self.app.db.insertar("clientes", {"nombre": f"Nuevo {paso}", "telefono": "1", "estado": "Pendiente"})
            elif operacion == "borrar" and len(ids) > 5:
                self.app.db.eliminar("clientes", azar.choice(ids))
            elif operacion == "lote_fallido":
                with self.assertRaises(RuntimeError):
                    with self.app.db.lote():
                        self.app.db.actualizar("clientes", azar.choice(ids), {"zona": "Fallida"})
                        raise RuntimeError("x")
            elif operacion == "buscar":
                busqueda = azar.choice(["lince", "nombre 1", "zzz"])
            with mock.patch.object(p.busqueda, "texto", return_value=busqueda):
                p.cargar_lista()
                obtenida = self.foto_lista(p)
                self.reconstruir_lista(p)
                self.assertEqual(obtenida, self.foto_lista(p), f"paso {paso}: {operacion}")

    def test_guardar_desde_el_formulario_no_reconstruye_la_lista(self):
        self.crear_clientes(20)
        p = self.clientes
        self.app.mostrar(p)
        p.seleccionar(5); p.al_seleccionar()
        p.form.poner_valor("zona", "Barranco")
        llamadas = []
        original = p.valores_fila
        with mock.patch.object(p, "valores_fila", side_effect=lambda f: (llamadas.append(f["id"]), original(f))[1]):
            self.assertTrue(p.guardar())
        self.assertEqual(llamadas, [5])
        self.assertIn("Barranco", " ".join(self.foto_lista(p)[[f[0] for f in self.foto_lista(p)].index("5")][1]))

    def esperar_copia(self, segundos=5):
        import time
        fin = time.time() + segundos
        while self.app._copiando and time.time() < fin:
            self.root.update()
            time.sleep(0.01)
        self.assertFalse(self.app._copiando, "la copia en segundo plano no terminó")

    def test_la_copia_en_segundo_plano_no_detiene_la_ventana_y_deja_su_resultado(self):
        import time
        self.cliente_guardado("Ana")
        version = self.app.db.version
        original = agencia.respaldar

        def lenta(*a, **k):
            time.sleep(0.6)                                       # una copia lenta (disco lento, muchos datos)
            return original(*a, **k)
        with mock.patch.object(agencia, "respaldar", lenta):
            t0 = time.perf_counter()
            self.app.hacer_copia_en_segundo_plano("auto")
            self.assertLess(time.perf_counter() - t0, 0.1)        # la ventana sigue libre, no espera a la copia
            self.assertTrue(self.app._copiando)
            self.app.hacer_copia_en_segundo_plano("auto")          # mientras hay una en marcha, no se lanza otra
            self.esperar_copia()
        self.assertEqual(len(self.nombres_de_copia("auto")), 1)
        self.assertEqual(self.app._version_copiada, version)
        self.assertEqual(len([n for n in os.listdir(self.externa) if n.endswith(".db")]), 1)

    def test_no_hay_boton_de_copias_y_la_copia_automatica_es_cada_24_horas(self):
        def textos(w):
            yield from ([w.cget("text")] if "text" in w.keys() else [])
            for h in w.winfo_children():
                yield from textos(h)
        self.assertNotIn("Copias de seguridad", list(textos(self.app.lateral)))
        self.assertEqual(agencia.COPIA_CADA_MS, 24 * 60 * 60 * 1000)
        atajo = "<Command-Shift-Key-B>" if sys.platform == "darwin" else "<Control-Shift-Key-B>"
        self.assertTrue(self.root.bind_all(atajo))                              # queda el atajo para restaurar

    def test_un_error_en_la_copia_de_fondo_se_avisa_y_no_deja_el_programa_bloqueado(self):
        self.cliente_guardado("Ana")
        with mock.patch.object(agencia, "registrar_error"), \
                mock.patch.object(agencia, "respaldar", side_effect=OSError("disco lleno")):   # sin escribir en el registro real
            self.app.hacer_copia_en_segundo_plano("auto")
            self.esperar_copia()
        self.assertFalse(self.app._copiando)                       # se puede volver a intentar
        with mock.patch.object(agencia, "registrar_error") as registro:
            with mock.patch.object(agencia, "respaldar", side_effect=OSError("otra vez")):
                self.app.hacer_copia_en_segundo_plano("auto")
                self.esperar_copia()
            self.assertTrue(registro.called)

    def test_las_copias_se_hacen_de_una_en_una_aunque_lleguen_a_la_vez(self):
        import threading
        self.cliente_guardado("Ana")
        resultados, errores = [], []

        def hacer(motivo):
            try:
                resultados.append(agencia.respaldar(motivo, agencia.DB_PATH, self.respaldos, externas=[self.externa]))
            except BaseException as error:
                errores.append(error)
        hilos = [threading.Thread(target=hacer, args=("auto",)) for _ in range(4)]
        for h in hilos: h.start()
        for h in hilos: h.join()
        self.assertEqual(errores, [])
        self.assertTrue(all(r["archivo"] or r["errores"] == [] for r in resultados))
        self.assertEqual([r["errores"] for r in resultados], [[]] * 4)                    # ninguna pisó a otra
        self.assertFalse([n for n in os.listdir(self.externa) if n.endswith(".tmp")])

    def test_ventana_de_copias_muestra_las_copias_y_permite_hacer_una(self):
        self.cliente_guardado("Ana")
        dialogo = agencia.DialogoCopias(self.root, self.app)
        self.assertEqual(len(dialogo.copias), 0)
        self.assertIn("Todavía no hay copias", dialogo.estado.cget("text"))
        dialogo.copiar_ahora()
        self.assertEqual({c["donde"] for c in dialogo.copias}, {"Programa", "Documentos"})   # la del programa y la externa
        manual = next(c for c in dialogo.copias if c["donde"] == "Programa")
        self.assertEqual((manual["tipo"], manual["clientes"]), ("Manual", 1))
        self.assertIn("Copia hecha y verificada", self.mensajes[-1][1])
        self.assertIn("✓ al", dialogo.estado.cget("text"))
        dialogo.destroy()


if __name__ == "__main__":
    unittest.main()
