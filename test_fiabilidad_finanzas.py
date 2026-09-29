"""Fiabilidad financiera con datos ficticios; todas las bases viven en temporales."""
import importlib.util
from datetime import date
from decimal import Decimal
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

IMPORTACION = tempfile.TemporaryDirectory(prefix="finanzas-importacion-")
FUENTE = Path(__file__).resolve().parent / "agencia.py"
spec = importlib.util.spec_from_file_location("agencia_pruebas_finanzas", FUENTE)
ag = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ag
with mock.patch.dict(os.environ, {"AGENCIA_DATOS": IMPORTACION.name}):
    sys.path.insert(0, str(FUENTE.parent))
    try:
        spec.loader.exec_module(ag)
    finally:
        sys.path.pop(0)


def condiciones(**cambios):
    datos = dict(fecha_contrato="29/09/2026", comision="300", sueldo_acordado="1800",
                 porcentaje="", meses_garantia="2")
    if hasattr(ag, "plazo_garantia"):
        datos["dias_garantia"] = "0"
    return dict(datos, **cambios)


def dialogo(datos, callback=None):
    return SimpleNamespace(form=SimpleNamespace(obtener=lambda: dict(datos)),
                           al_guardar=callback or mock.Mock(), destroy=mock.Mock())


class ImportesYPlazos(unittest.TestCase):
    def test_no_finitos_y_desbordamientos_se_rechazan_sin_excepciones(self):
        for valor in ("nan", "inf", "-inf", "1e9999", float("nan"), float("inf"), 10 ** 5000, []):
            with self.subTest(tipo=type(valor).__name__):
                self.assertIsNone(ag.leer_numero(valor))
                self.assertIsNone(ag.leer_decimal(valor))
                self.assertEqual(ag.dinero(valor), "________")
                self.assertEqual(ag.dinero_corto(valor), "-")

    def test_formato_monetario_conserva_separadores_y_centavos(self):
        for texto in ("S/ 1,234.56", "S/ 1.234,56", "1234,56", "1234.56"):
            self.assertEqual(ag.leer_decimal(texto), Decimal("1234.56"))
            self.assertEqual(ag.dinero(texto), "S/ 1,234.56")

    def test_redondeo_decimal_a_par_sin_error_binario(self):
        self.assertEqual(ag.importe_texto("2.675"), "2.68")
        self.assertEqual(ag.importe_texto("2.685"), "2.68")
        self.assertEqual(ag.importe_texto("1.005"), "1.00")
        self.assertEqual(ag.importe_texto("1.015"), "1.02")
        self.assertEqual(ag.dinero(2.675), "S/ 2.68")
        self.assertEqual(ag.monto_por_porcentaje("101.5", "1"), "1.02")
        self.assertEqual(ag.porcentaje_de("1.015", "100"), "1.02")

    def test_calculos_finitos_grandes_sin_topes_comerciales(self):
        monto = ag.monto_por_porcentaje("50", "1e308")
        self.assertEqual(Decimal(monto), Decimal("5e307"))
        self.assertEqual(ag.monto_por_porcentaje("200", "1000"), "2000.00")
        self.assertIsNone(ag.monto_por_porcentaje("1e308", "1e308"))
        self.assertEqual(ag.porcentaje_de("1e308", "1e-308"), "")
        self.assertIsNone(ag.validar_condiciones_financieras(condiciones(comision="1e308", sueldo_acordado="")))
        self.assertIsNone(ag.validar_condiciones_financieras(condiciones(comision="2000", porcentaje="200", sueldo_acordado="1000")))

    def test_porcentaje_impreso_conserva_el_entero_original(self):
        self.assertIn("9007199254740993 %", ag.porcentaje_en_letras("9007199254740993"))
        self.assertEqual(ag.porcentaje_en_letras("12.5"), "12.5 %")

    def test_aviso_de_borrado_coincide_con_total_financiero_decimal(self):
        def filas(*montos):
            return [dict(comision=monto, comision_pagada="1", contrato_firmado="0") for monto in montos]
        self.assertIn("S/ 3.02", ag.describir_perdida(filas("2", "1.015")))
        self.assertIn(ag.dinero(Decimal("2e308")), ag.describir_perdida(filas("1e308", "1e308")))

    def test_el_dialogo_rechaza_importes_invalidos_antes_del_callback(self):
        casos = [dict(comision=x) for x in ("-300", "nan", "inf", "1e9999")]
        casos += [dict(sueldo_acordado=x) for x in ("-1", "0", "nan", "inf")]
        casos += [dict(porcentaje=x) for x in ("-1", "nan", "inf")]
        casos += [dict(comision="1e308", sueldo_acordado="1e-308")]
        with mock.patch.object(ag.messagebox, "showwarning"):
            for cambio in casos:
                with self.subTest(cambio=cambio):
                    d = dialogo(condiciones(**cambio))
                    self.assertFalse(ag.DialogoContrato.guardar(d))
                    d.al_guardar.assert_not_called()
                    d.destroy.assert_not_called()

    def test_el_dialogo_valida_vencimiento_y_entero_antes_de_guardar(self):
        casos = [dict(meses_garantia=x) for x in ("100000", "-1", "1.5", "nan")]
        casos += [dict(fecha_contrato="31/12/9999", meses_garantia="1")]
        if hasattr(ag, "plazo_garantia"):
            casos += [dict(meses_garantia="0", dias_garantia=x) for x in ("999999999", "-1", "1.5")]
        with mock.patch.object(ag.messagebox, "showwarning"):
            for cambio in casos:
                with self.subTest(cambio=cambio):
                    d = dialogo(condiciones(**cambio))
                    self.assertFalse(ag.DialogoContrato.guardar(d))
                    d.al_guardar.assert_not_called()
        datos = condiciones(fecha_contrato="31/12/9999", meses_garantia="0")
        self.assertIsNone(ag.validar_condiciones_financieras(datos))

    def test_guardar_redondea_comision_y_admite_reemplazo_sin_costo(self):
        for monto, esperado in (("2.675", "2.68"), ("0", "0.00")):
            d = dialogo(condiciones(comision=monto))
            self.assertTrue(ag.DialogoContrato.guardar(d))
            self.assertEqual(d.al_guardar.call_args.args[0]["comision"], esperado)
            d.destroy.assert_called_once()

    def test_rechazo_del_callback_conserva_dialogo_y_datos(self):
        d = dialogo(condiciones(), mock.Mock(return_value=False))
        self.assertFalse(ag.DialogoContrato.guardar(d))
        d.destroy.assert_not_called()
        self.assertEqual(d.form.obtener()["comision"], "300")

    def test_origen_contractual_unico_y_alternativas(self):
        c = dict(condiciones(), fecha_enlace="25/09/2026", estado="En proceso", contrato_firmado="1")
        real = date(2026, 10, 1)
        self.assertEqual(ag.origen_garantia(c, real), date(2026, 9, 29))
        fin = ag.vencimiento_garantia(ag.origen_garantia(c, real), c)
        self.assertEqual(ag.inicio_por_firma(c)["fin_garantia"], fin.strftime(ag.FMT_FECHA))
        self.assertEqual(fin, date(2026, 11, 29))
        self.assertEqual(ag.origen_garantia({}, real), real)
        self.assertEqual(ag.origen_garantia({"fecha_enlace": "25/09/2026"}, real), date(2026, 9, 25))

    def test_plazo_historico_y_fin_de_mes_se_conservan(self):
        self.assertEqual(ag.sumar_meses(date(2028, 1, 31), 1), date(2028, 2, 29))
        with self.assertRaises(ValueError):
            ag.sumar_meses(date(2026, 1, 31), 100000)
        if hasattr(ag, "plazo_garantia"):
            c = dict(condiciones(meses_garantia="0", dias_garantia="30"), garantia="Sí")
            self.assertEqual(ag.vencimiento_garantia(date(2026, 1, 31), c), date(2026, 3, 2))
            self.assertEqual(ag.plazo_garantia(c), (30, "días"))


class ComisionesAisladas(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory(prefix="finanzas-operaciones-")
        self.ruta = Path(self.temporal.name) / "agencia.db"
        self.db = ag.BaseDatos(self.ruta)
        self.otra = ag.BaseDatos(self.ruta)
        self.id = self.db.insertar("colocaciones", dict(comision="300", sueldo_acordado="1800",
                                  porcentaje="16.67", comision_pagada="0", fecha_pago="", estado="Activa",
                                  fecha_contrato="29/09/2026", notas="Original"))
        nombres = ("_comision_actual", "_guardar_finanzas", "pagada", "no_pagada", "cambiar_monto")
        clase = type("PaginaFinancieraFicticia", (), {n: getattr(ag.PaginaComisiones, n) for n in nombres})
        clase._campos_financieros = ag.PaginaComisiones._campos_financieros
        self.pagina = clase()
        self.pagina.db = self.db
        self.info = mock.patch.object(ag.messagebox, "showinfo").start()
        self.warning = mock.patch.object(ag.messagebox, "showwarning").start()
        self.fecha = mock.patch.object(ag, "hoy", return_value="29/09/2026").start()
        self.addCleanup(mock.patch.stopall)

    def tearDown(self):
        self.db.con.close()
        self.otra.con.close()
        self.temporal.cleanup()

    def fila(self):
        registro = self.db.con.execute("SELECT * FROM colocaciones WHERE id=?", (self.id,)).fetchone()
        return self.db._fila(registro) if registro else None

    def test_comision_cobrada_conserva_importe_y_fecha_sin_abrir_editor(self):
        self.db.actualizar("colocaciones", self.id, dict(comision_pagada="1", fecha_pago="20/09/2026"))
        antes = self.fila()
        with mock.patch.object(ag, "pedir_texto", side_effect=["1800", "", "900"]) as pedir:
            self.assertFalse(self.pagina.cambiar_monto(antes))
            pedir.assert_not_called()
        self.assertEqual(self.fila(), antes)
        self.assertEqual(ag.resumen_ganancias([self.fila()], [], date(2026, 9, 29))["cobrado_total"], 300)

    def test_editor_concurrente_no_sobrescribe_monto_ajeno(self):
        antes = self.fila()
        respuestas = iter(["1800", "", "600"])
        def escribir(*args):
            valor = next(respuestas)
            if valor == "600":
                self.otra.actualizar("colocaciones", self.id, {"comision": "900"})
            return valor
        with mock.patch.object(ag, "pedir_texto", side_effect=escribir):
            self.assertFalse(self.pagina.cambiar_monto(antes))
        self.assertEqual(self.fila()["comision"], "900")

    def test_cobro_durante_edicion_se_conserva(self):
        antes = self.fila()
        respuestas = iter(["1800", "", "600"])
        def escribir(*args):
            valor = next(respuestas)
            if valor == "600":
                self.otra.actualizar("colocaciones", self.id, dict(comision_pagada="1", fecha_pago="25/09/2026"))
            return valor
        with mock.patch.object(ag, "pedir_texto", side_effect=escribir):
            self.assertFalse(self.pagina.cambiar_monto(antes))
        actual = self.fila()
        self.assertEqual((actual["comision"], actual["comision_pagada"], actual["fecha_pago"]),
                         ("300", "1", "25/09/2026"))

    def test_nota_concurrente_se_conserva_y_permite_edicion_financiera(self):
        antes = self.fila()
        respuestas = iter(["1800", "50"])
        def escribir(*args):
            valor = next(respuestas)
            if valor == "50":
                self.otra.actualizar("colocaciones", self.id, {"notas": "Nota de otra ventana"})
            return valor
        with mock.patch.object(ag, "pedir_texto", side_effect=escribir):
            self.assertTrue(self.pagina.cambiar_monto(antes))
        actual = self.fila()
        self.assertEqual(actual["comision"], "900.00")
        self.assertEqual(actual["porcentaje"], "50")
        self.assertEqual(actual["notas"], "Nota de otra ventana")

    def test_asignacion_borrada_durante_editor_no_se_recrea(self):
        antes = self.fila()
        respuestas = iter(["1800", "50"])
        def borrar(*args):
            valor = next(respuestas)
            if valor == "50":
                self.otra.eliminar("colocaciones", self.id)
            return valor
        with mock.patch.object(ag, "pedir_texto", side_effect=borrar):
            self.assertFalse(self.pagina.cambiar_monto(antes))
        self.assertIsNone(self.fila())

    def test_revertir_cobro_no_borra_un_pago_concurrente(self):
        self.db.actualizar("colocaciones", self.id, dict(comision_pagada="1", fecha_pago="20/09/2026"))
        antes = self.fila()
        def confirmar(*args, **kwargs):
            self.otra.actualizar("colocaciones", self.id, dict(fecha_pago="25/09/2026"))
            return True
        with mock.patch.object(ag.messagebox, "askyesno", side_effect=confirmar):
            self.assertFalse(self.pagina.no_pagada(antes))
        self.assertEqual((self.fila()["comision_pagada"], self.fila()["fecha_pago"]), ("1", "25/09/2026"))

    def test_seleccion_antigua_no_vuelve_a_fechar_un_pago(self):
        antes = self.fila()
        self.otra.actualizar("colocaciones", self.id, dict(comision_pagada="1", fecha_pago="20/09/2026"))
        self.assertFalse(self.pagina.pagada(antes))
        self.assertEqual(self.fila()["fecha_pago"], "20/09/2026")

    def test_cobro_y_reversion_normales_respetan_totales(self):
        self.assertTrue(self.pagina.pagada(self.fila()))
        actual = self.fila()
        self.assertEqual((actual["comision_pagada"], actual["fecha_pago"]), ("1", "29/09/2026"))
        self.fecha.return_value = "30/09/2026"
        self.assertFalse(self.pagina.pagada(actual))
        self.assertEqual(self.fila()["fecha_pago"], "29/09/2026")
        with mock.patch.object(ag.messagebox, "askyesno", return_value=True):
            self.assertTrue(self.pagina.no_pagada(self.fila()))
        self.assertEqual(self.fila()["fecha_pago"], "")
        resumen = ag.resumen_ganancias([self.fila()], [], date(2026, 9, 29))
        self.assertEqual((resumen["cobrado_total"], resumen["por_cobrar"]), (0, 300))

    def test_no_se_cobran_importes_invalidos_o_no_positivos(self):
        for monto in ("-300", "nan", "inf", "1e9999", "0", ""):
            self.db.actualizar("colocaciones", self.id, {"comision": monto})
            self.assertFalse(self.pagina.pagada(self.fila()))
            self.assertEqual((self.fila()["comision_pagada"], self.fila()["fecha_pago"]), ("0", ""))

    def test_editor_adaptable_y_centavos_decimales(self):
        with mock.patch.object(ag, "pedir_texto", side_effect=["1", "", "2.675"]):
            self.assertTrue(self.pagina.cambiar_monto(self.fila()))
        self.assertEqual((self.fila()["comision"], self.fila()["porcentaje"]), ("2.68", "268"))
        with mock.patch.object(ag, "pedir_texto", side_effect=["1", "101.5"]):
            self.assertTrue(self.pagina.cambiar_monto(self.fila()))
        self.assertEqual(self.fila()["comision"], "1.02")
        with mock.patch.object(ag, "pedir_texto", side_effect=["1000", "200"]):
            self.assertTrue(self.pagina.cambiar_monto(self.fila()))
        self.assertEqual(self.fila()["comision"], "2000.00")
        with mock.patch.object(ag, "pedir_texto", side_effect=["1800", "", "2.675"]):
            self.assertTrue(self.pagina.cambiar_monto(self.fila()))
        self.assertEqual(self.fila()["comision"], "2.68")

    def test_sueldo_negativo_no_genera_porcentaje_ni_escribe(self):
        antes = self.fila()
        with mock.patch.object(ag, "pedir_texto", side_effect=["-1800", "", "300"]):
            self.assertFalse(self.pagina.cambiar_monto(antes))
        self.assertEqual(self.fila(), antes)

    def test_release_fallido_no_deja_cobro_pendiente_de_commit(self):
        real = self.db.con
        class ConexionQueFalla:
            fallo = False
            def execute(proxy, sql, parametros=()):
                if sql.startswith("RELEASE") and not proxy.fallo:
                    proxy.fallo = True
                    raise sqlite3.OperationalError("Fallo de confirmación simulado")
                return real.execute(sql, parametros)
            def __getattr__(proxy, nombre):
                return getattr(real, nombre)
        self.db.con = ConexionQueFalla()
        self.assertFalse(self.pagina.pagada(self.fila()))
        self.db.insertar("clientes", {"nombre": "Registro ficticio posterior"})
        self.assertEqual((self.fila()["comision_pagada"], self.fila()["fecha_pago"]), ("0", ""))
        self.assertTrue(self.pagina.pagada(self.fila()))


class ResumenDecimal(unittest.TestCase):
    def filas(self, montos):
        return [dict(id=i, comision=m, comision_pagada="1", fecha_pago="29/09/2026",
                     cliente_id="1", trabajadora_id="1") for i, m in enumerate(montos, 1)]

    def test_suma_centavos_exactos_y_api_float_normal(self):
        resumen = ag.resumen_ganancias(self.filas(["0.1", "0.2"]), [], date(2026, 9, 29))
        self.assertEqual(resumen["cobrado_total"], 0.3)
        self.assertIsInstance(resumen["cobrado_total"], float)
        self.assertEqual(ag.dinero(resumen["cobrado_mes"]), "S/ 0.30")

    def test_sumatorio_desbordado_conserva_decimal_coherente(self):
        resumen = ag.resumen_ganancias(self.filas(["1e308", "1e308"]), [], date(2026, 9, 29))
        self.assertEqual(resumen["cobrado_total"], Decimal("2e308"))
        for clave in ("cobrado_total", "por_cobrar", "cobrado_semana", "cobrado_mes", "cobrado_anio"):
            self.assertIsInstance(resumen[clave], Decimal)
        self.assertTrue(all(isinstance(n, Decimal) for n in resumen["por_area"].values()))
        self.assertTrue(all(isinstance(n, Decimal) for n in resumen["meses_anio"]))
        self.assertTrue(all(isinstance(p["monto"], Decimal) for p in resumen["historial"]))
        self.assertNotIn("inf", ag.dinero(resumen["cobrado_total"]).lower())

    def test_la_vista_renderiza_totales_decimales_grandes(self):
        try:
            root = ag.tk.Tk()
        except ag.tk.TclError as error:
            self.skipTest(str(error))
        root.withdraw()
        try:
            ag.aplicar_tema(root)
            resumen = ag.resumen_ganancias(self.filas(["1e308", "1e308"]), [], date(2026, 9, 29))
            app = SimpleNamespace(db=SimpleNamespace(), resumen_financiero=lambda: resumen,
                                  mostrar=mock.Mock(), comisiones=None)
            pagina = ag.PaginaGanancias(root, app)
            pagina.refrescar()
            root.update_idletasks()
            self.assertEqual(pagina.cifras["cobrado_total"].cget("text"), ag.dinero(Decimal("2e308")))
            self.assertTrue(pagina.lista_pagos.get_children())
        finally:
            for tarea in root.tk.call("after", "info"):
                root.tk.call("after", "cancel", tarea)
            root.destroy()


if __name__ == "__main__":
    unittest.main()
