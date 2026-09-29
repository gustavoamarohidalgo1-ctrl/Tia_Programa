"""Estados y vínculos de negocio con SQLite temporal; no abre ventanas ni datos reales."""
import sqlite3
import tempfile
import threading
import unittest
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import agencia


class FiabilidadEstadosTest(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory(prefix="estados-ficticios-")
        self.ruta = Path(self.temporal.name) / "agencia.db"
        self.db = agencia.BaseDatos(str(self.ruta))
        self.app = self.aplicacion(self.db)

    @staticmethod
    def aplicacion(db):
        app = agencia.App.__new__(agencia.App)
        app.db = db
        app._reemplazos = (-1, {})
        return app

    def tearDown(self):
        self.db.con.close()
        self.temporal.cleanup()

    def cliente(self, estado="Buscando"):
        return self.db.insertar("clientes", {"nombre": "Cliente ficticio", "estado": estado})

    def trabajadora(self, estado="Disponible"):
        return self.db.insertar("trabajadoras", {"nombre": "Trabajadora ficticia", "estado": estado})

    def enlace(self, cliente, trabajadora, **cambios):
        datos = {"cliente_id": str(cliente), "trabajadora_id": str(trabajadora), "estado": "En proceso",
                 "fecha_enlace": "01/01/2026", "fecha_contrato": "10/01/2026",
                 "garantia": "Sí", "meses_garantia": "1", "comision": "500", "sueldo_acordado": "1000"}
        if "dias_garantia" in agencia.claves(agencia.CAMPOS_COLOCACION):
            datos.update(meses_garantia="0", dias_garantia="30")
        datos.update(cambios)
        return self.db.insertar("colocaciones", datos)

    def fila(self, id_):
        return self.db.uno("colocaciones", id_)

    def estado(self, tabla, id_):
        return self.db.uno(tabla, id_)["estado"]

    def cadena_historica(self):
        c1, c2 = self.cliente("Colocado"), self.cliente("Colocado")
        t1, t2 = self.trabajadora("Trabajando"), self.trabajadora("Trabajando")
        antiguo = self.enlace(c1, t1, estado="Reemplazo solicitado")
        hijo = self.enlace(c1, t2, estado="Activa", reemplazo_de=str(antiguo))
        otro = self.enlace(c2, t1, estado="Activa")
        return c1, c2, t1, t2, antiguo, hijo, otro

    def test_deshacer_historico_no_libera_personas_con_otro_trabajo(self):
        c1, c2, t1, t2, antiguo, hijo, otro = self.cadena_historica()
        self.assertTrue(self.app.deshacer_enlace(self.fila(antiguo)))
        self.assertEqual(self.fila(antiguo)["estado"], "Cancelada")
        self.assertEqual(self.fila(hijo)["reemplazo_de"], str(antiguo))
        for tabla, ids, estado in (("clientes", (c1, c2), "Colocado"),
                                   ("trabajadoras", (t1, t2), "Trabajando")):
            for id_ in ids:
                self.assertEqual(self.estado(tabla, id_), estado)
        self.assertEqual(self.fila(otro)["estado"], "Activa")

    def test_deshacer_respeta_reserva_pendiente_y_prioriza_trabajo_activo(self):
        cli, t = self.cliente("Colocado"), self.trabajadora("Trabajando")
        activo = self.enlace(cli, t, estado="Activa")
        pendiente = self.enlace(cli, t)
        self.app.deshacer_enlace(self.fila(activo))
        self.assertEqual(self.estado("clientes", cli), "En entrevista")
        self.assertEqual(self.estado("trabajadoras", t), "En proceso")
        self.app.deshacer_enlace(self.fila(pendiente))
        self.assertEqual(self.estado("clientes", cli), "Buscando")
        self.assertEqual(self.estado("trabajadoras", t), "Disponible")

    def test_deshacer_historico_conserva_estados_manuales_sin_ocupaciones(self):
        cli, t = self.cliente("Cancelado"), self.trabajadora("No disponible")
        anterior = self.enlace(cli, t, estado="Cancelada")
        self.app.deshacer_enlace(self.fila(anterior))
        self.assertEqual(self.estado("clientes", cli), "Cancelado")
        self.assertEqual(self.estado("trabajadoras", t), "No disponible")

    def test_deshacer_reemplazante_reabre_solicitud_original(self):
        cli, t1, t2 = self.cliente("Colocado"), self.trabajadora(), self.trabajadora("Trabajando")
        anterior = self.enlace(cli, t1, estado="Reemplazo solicitado")
        hijo = self.enlace(cli, t2, estado="Activa", reemplazo_de=str(anterior))
        self.assertIsNone(self.app.reemplazo_pendiente(cli))
        self.app.deshacer_enlace(self.fila(hijo))
        self.assertEqual(self.app.reemplazo_pendiente(cli)["id"], anterior)

    def test_eliminar_saliente_conserva_antecedente_sin_referencia_colgante(self):
        c1, c2, t1, t2, antiguo, hijo, otro = self.cadena_historica()
        persona = self.db.uno("trabajadoras", t1)
        relacionados = [c for c in self.db.todos("colocaciones") if c["trabajadora_id"] == str(t1)]
        self.assertTrue(self.app.eliminar_persona("trabajadoras", t1, relacionados, persona))
        self.assertIsNone(self.db.uno("trabajadoras", t1))
        self.assertEqual(self.fila(antiguo)["estado"], "Cancelada")
        self.assertEqual(self.fila(antiguo)["trabajadora_id"], "")
        self.assertEqual(self.fila(hijo)["reemplazo_de"], str(antiguo))
        self.assertEqual(self.estado("clientes", c1), "Colocado")
        self.assertEqual(self.estado("trabajadoras", t2), "Trabajando")
        self.assertEqual(self.estado("clientes", c2), "Buscando")
        self.assertIsNone(self.fila(otro))

    def test_borrado_revalida_nuevas_asignaciones_y_no_borra_persona(self):
        cli, t = self.cliente(), self.trabajadora()
        persona = self.db.uno("trabajadoras", t)
        otra = agencia.BaseDatos(str(self.ruta))
        try:
            enlace = otra.insertar("colocaciones", {"cliente_id": str(cli), "trabajadora_id": str(t), "estado": "Activa"})
            with self.assertRaisesRegex(ValueError, "cambiaron"):
                self.app.eliminar_persona("trabajadoras", t, [], persona)
            self.assertIsNotNone(self.db.uno("trabajadoras", t))
            self.assertIsNotNone(self.fila(enlace))
        finally:
            otra.con.close()

    def test_borrado_revalida_persona_editada_desde_otra_instancia(self):
        t = self.trabajadora()
        persona = self.db.uno("trabajadoras", t)
        with sqlite3.connect(self.ruta) as otra:
            otra.execute("UPDATE trabajadoras SET telefono='999000111' WHERE id=?", (t,))
        with self.assertRaises(ValueError):
            self.app.eliminar_persona("trabajadoras", t, [], persona)
        self.assertEqual(self.db.uno("trabajadoras", t)["telefono"], "999000111")

    def test_fallo_de_borrado_revierte_enlaces_persona_e_indice(self):
        cli, t = self.cliente("Colocado"), self.trabajadora("Trabajando")
        enlace = self.enlace(cli, t, estado="Activa")
        self.app._indice_ocupaciones()
        persona, relacionados = self.db.uno("trabajadoras", t), [self.fila(enlace)]
        original = self.db.eliminar
        def eliminar(tabla, id_):
            if tabla == "trabajadoras":
                raise RuntimeError("fallo simulado")
            original(tabla, id_)
        with patch.object(self.db, "eliminar", side_effect=eliminar):
            with self.assertRaises(RuntimeError):
                self.app.eliminar_persona("trabajadoras", t, relacionados, persona)
        self.assertEqual(self.estado("clientes", cli), "Colocado")
        self.assertEqual(self.estado("trabajadoras", t), "Trabajando")
        self.assertEqual(self.fila(enlace)["estado"], "Activa")
        self.assertEqual(self.app._vinculos_ocupantes("trabajadoras", t), {str(enlace): "Activa"})

    def test_deshacer_revalida_pago_y_contrato_modificados(self):
        cli, t = self.cliente(), self.trabajadora()
        enlace = self.enlace(cli, t)
        antiguo = self.fila(enlace)
        with sqlite3.connect(self.ruta) as otra:
            otra.execute("UPDATE colocaciones SET comision_pagada='1', contrato_firmado='1' WHERE id=?", (enlace,))
        with self.assertRaisesRegex(ValueError, "cambió"):
            self.app.deshacer_enlace(antiguo)
        self.assertEqual(self.fila(enlace)["comision_pagada"], "1")
        self.assertEqual(self.fila(enlace)["contrato_firmado"], "1")

    def test_asignar_rechaza_ocupacion_aunque_perfil_diga_disponible(self):
        cli, otro, t = self.cliente(), self.cliente(), self.trabajadora()
        self.enlace(cli, t, estado="Activa")
        with self.assertRaisesRegex(ValueError, "disponibilidad"):
            self.app.crear_asignacion({"cliente_id": str(otro), "trabajadora_id": str(t), "estado": "En proceso"})
        self.assertEqual(len(self.db.todos("colocaciones")), 1)

    def test_asignar_rechaza_cliente_ocupado_aunque_diga_buscando(self):
        cli, t1, t2 = self.cliente(), self.trabajadora(), self.trabajadora()
        self.enlace(cli, t1, estado="Garantía cumplida")
        with self.assertRaises(ValueError):
            self.app.crear_asignacion({"cliente_id": str(cli), "trabajadora_id": str(t2), "estado": "En proceso"})

    def test_dos_instancias_concurrentes_no_reservan_la_misma_trabajadora(self):
        clientes, t = (self.cliente(), self.cliente()), self.trabajadora()
        barrera, resultados = threading.Barrier(2), []
        def reservar(cli):
            db = agencia.BaseDatos(str(self.ruta))
            app = self.aplicacion(db)
            try:
                db.todos("clientes")
                db.todos("trabajadoras")
                app._indice_ocupaciones()
                barrera.wait(timeout=5)
                try:
                    resultados.append(("ok", app.crear_asignacion({"cliente_id": str(cli), "trabajadora_id": str(t),
                                                                  "estado": "En proceso"})))
                except ValueError:
                    resultados.append(("rechazado", cli))
            except BaseException as error:
                resultados.append(("error", repr(error)))
            finally:
                db.con.close()
        hilos = [threading.Thread(target=reservar, args=(cli,)) for cli in clientes]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join(timeout=15)
            self.assertFalse(hilo.is_alive())
        self.assertEqual(sorted(r[0] for r in resultados), ["ok", "rechazado"], resultados)
        self.db.cambio_externo()
        self.assertEqual(len(self.db.todos("colocaciones")), 1)
        self.assertEqual(self.estado("trabajadoras", t), "En proceso")

    def test_asignacion_fallida_revierte_ocupacion_y_nuevo_vinculo(self):
        cli, t = self.cliente(), self.trabajadora()
        datos = {"cliente_id": str(cli), "trabajadora_id": str(t), "estado": "En proceso"}
        with patch.object(self.app, "sincronizar", side_effect=RuntimeError("fallo")):
            with self.assertRaises(RuntimeError):
                self.app.crear_asignacion(datos, ocupacion="Nuevo oficio")
        self.assertEqual(datos, {"cliente_id": str(cli), "trabajadora_id": str(t), "estado": "En proceso"})
        self.assertEqual(self.db.todos("colocaciones"), [])
        self.assertEqual(self.db.uno("clientes", cli)["ocupacion"], "")
        self.assertEqual(self.app._vinculos_ocupantes("trabajadoras", t), {})

    def test_reemplazo_de_otro_cliente_o_de_si_mismo_no_oculta_solicitud(self):
        cli, otro, t = self.cliente(), self.cliente(), self.trabajadora()
        pendiente = self.enlace(cli, t, estado="Reemplazo solicitado")
        self.enlace(otro, t, estado="Cancelada", reemplazo_de=str(pendiente))
        self.db.actualizar("colocaciones", pendiente, {"reemplazo_de": str(pendiente)})
        self.assertEqual(self.app.reemplazo_pendiente(cli)["id"], pendiente)
        self.assertNotIn(str(pendiente), self.app.reemplazos_atendidos(self.db.todos("colocaciones")))

    def test_reemplazo_revalida_condiciones_cambiadas_en_dialogo(self):
        cli, t1, t2 = self.cliente(), self.trabajadora(), self.trabajadora()
        pendiente = self.enlace(cli, t1, estado="Reemplazo solicitado")
        esperado = self.fila(pendiente)
        self.db.actualizar("colocaciones", pendiente, {"meses_garantia": "6"})
        with self.assertRaisesRegex(ValueError, "condiciones"):
            self.app.crear_asignacion({"cliente_id": str(cli), "trabajadora_id": str(t2),
                                      "estado": "En proceso", "reemplazo_de": str(pendiente)},
                                     reemplazo_esperado=esperado)
        self.assertEqual(len(self.db.todos("colocaciones")), 1)

    def test_inicio_manual_conserva_fecha_real_y_garantia_desde_contrato(self):
        cli, t = self.cliente("En entrevista"), self.trabajadora("En proceso")
        enlace = self.enlace(cli, t)
        self.assertTrue(self.app.iniciar_asignacion(self.fila(enlace), date(2026, 1, 20)))
        actual = self.fila(enlace)
        esperado = agencia.vencimiento_garantia(date(2026, 1, 10), actual).strftime(agencia.FMT_FECHA)
        self.assertEqual(actual["fecha_inicio"], "20/01/2026")
        self.assertEqual(actual["fin_garantia"], esperado)
        self.assertEqual(self.estado("trabajadoras", t), "Trabajando")
        self.assertEqual(self.estado("clientes", cli), "Colocado")

    def test_inicio_revalida_estado_cambiado_y_no_resucita_reemplazo(self):
        cli, t = self.cliente("En entrevista"), self.trabajadora("En proceso")
        enlace = self.enlace(cli, t)
        antiguo = self.fila(enlace)
        with sqlite3.connect(self.ruta) as otra:
            otra.execute("UPDATE colocaciones SET estado='Reemplazo solicitado' WHERE id=?", (enlace,))
        self.assertFalse(self.app.iniciar_asignacion(antiguo, date(2026, 1, 20)))
        self.assertEqual(self.fila(enlace)["estado"], "Reemplazo solicitado")
        self.assertEqual(self.fila(enlace)["fecha_inicio"], "")

    def test_inicio_rechaza_persona_eliminada_y_ocupacion_duplicada(self):
        cli, t = self.cliente("En entrevista"), self.trabajadora("En proceso")
        enlace = self.enlace(cli, t)
        otro = self.cliente("Colocado")
        self.enlace(otro, t, estado="Activa")
        self.assertFalse(self.app.iniciar_asignacion(self.fila(enlace), date(2026, 1, 20)))
        self.db.eliminar("trabajadoras", t)
        self.assertFalse(self.app.iniciar_asignacion(self.fila(enlace), date(2026, 1, 20)))
        self.assertEqual(self.fila(enlace)["estado"], "En proceso")

    def test_inicio_automatico_salta_huerfano_y_reintenta_tras_reparacion(self):
        cli = self.cliente("En entrevista")
        enlace = self.enlace(cli, 999, contrato_firmado="1")
        self.app.iniciar_contratos_firmados()
        self.assertEqual(self.fila(enlace)["estado"], "En proceso")
        self.db.insertar("trabajadoras", {"id": 999, "nombre": "Persona restaurada", "estado": "En proceso"})
        self.app.iniciar_contratos_firmados()
        self.assertEqual(self.fila(enlace)["estado"], "Activa")

    def test_inicio_automatico_conserva_bloqueo_manual_y_reintenta_al_cambiarlo(self):
        cli, t = self.cliente("En entrevista"), self.trabajadora("No disponible")
        enlace = self.enlace(cli, t, contrato_firmado="1")
        self.app.iniciar_contratos_firmados()
        self.assertEqual(self.fila(enlace)["estado"], "En proceso")
        self.assertEqual(self.estado("trabajadoras", t), "No disponible")
        self.db.actualizar("trabajadoras", t, {"estado": "En proceso"})
        self.app.iniciar_contratos_firmados()
        self.assertEqual(self.fila(enlace)["estado"], "Activa")

    def test_reemplazo_y_cumplimiento_no_sobrescriben_cambios_ajenos(self):
        cli, t = self.cliente("Colocado"), self.trabajadora("Trabajando")
        enlace = self.enlace(cli, t, estado="Activa")
        antiguo = self.fila(enlace)
        self.db.actualizar("colocaciones", enlace, {"estado": "Reemplazo solicitado"})
        for accion in (self.app.solicitar_reemplazo, self.app.cumplir_garantia):
            with self.assertRaises(ValueError):
                accion(antiguo)
        self.assertEqual(self.fila(enlace)["estado"], "Reemplazo solicitado")

    def test_cierre_automatico_revalida_despues_de_cambio_externo(self):
        cli, t = self.cliente("Colocado"), self.trabajadora("Trabajando")
        enlace = self.enlace(cli, t, estado="Activa", fin_garantia="01/01/2026")
        self.db.todos("colocaciones")
        with sqlite3.connect(self.ruta) as otra:
            otra.execute("UPDATE colocaciones SET estado='Reemplazo solicitado' WHERE id=?", (enlace,))
        self.app.cerrar_garantias_vencidas()
        self.assertEqual(self.fila(enlace)["estado"], "Reemplazo solicitado")

    def test_indice_incorpora_ediciones_reversiones_y_sustitucion_externa(self):
        cli, t = self.cliente(), self.trabajadora()
        enlace = self.enlace(cli, t)
        self.assertEqual(self.app._vinculos_ocupantes("trabajadoras", t), {str(enlace): "En proceso"})
        with self.assertRaises(RuntimeError):
            with self.db.lote():
                self.db.actualizar("colocaciones", enlace, {"estado": "Cancelada"})
                self.assertEqual(self.app._vinculos_ocupantes("trabajadoras", t), {})
                raise RuntimeError("revertir")
        self.assertEqual(self.app._vinculos_ocupantes("trabajadoras", t), {str(enlace): "En proceso"})
        with sqlite3.connect(self.ruta) as otra:
            otra.execute("UPDATE colocaciones SET estado='Activa' WHERE id=?", (enlace,))
        with self.app.cambio_de_estados():
            self.assertEqual(self.app._vinculos_ocupantes("trabajadoras", t), {str(enlace): "Activa"})

    def test_no_recorre_todas_las_colocaciones_en_cada_persona_del_lote(self):
        ids = [(self.cliente("En entrevista"), self.trabajadora("En proceso")) for _ in range(12)]
        for cli, t in ids:
            self.enlace(cli, t, contrato_firmado="1")
        sql = []
        self.db.con.set_trace_callback(sql.append)
        self.app.iniciar_contratos_firmados()
        self.db.con.set_trace_callback(None)
        barridos = [s for s in sql if s.startswith("SELECT id, cliente_id, trabajadora_id, estado FROM colocaciones")]
        self.assertEqual(len(barridos), 1)
        self.assertTrue(all(c["estado"] == "Activa" for c in self.db.todos("colocaciones")))

    def test_formulario_no_permite_disponibilidad_con_vinculo_activo(self):
        cli, t = self.cliente("Colocado"), self.trabajadora("Trabajando")
        self.enlace(cli, t, estado="Activa")
        pagina = agencia.PaginaTrabajadoras.__new__(agencia.PaginaTrabajadoras)
        pagina.app, pagina.db, pagina.id_actual = self.app, self.db, t
        for estado in ("Disponible", "No disponible", "En proceso"):
            self.assertIn("asignación", pagina.validar_extra({"estado": estado}))
        self.assertIsNone(pagina.validar_extra({"estado": "Trabajando"}))

    def test_inicio_incorpora_firma_externa_entre_lectura_y_reserva(self):
        personas = [(self.cliente("En entrevista"), self.trabajadora("En proceso")) for _ in range(2)]
        ids = [self.enlace(*personas[0], contrato_firmado="1"), self.enlace(*personas[1], contrato_firmado="0")]
        self.db.todos("colocaciones")
        original = self.app.cambio_de_estados
        ejecutado = False
        @contextmanager
        def reservar():
            nonlocal ejecutado
            if not ejecutado:
                ejecutado = True
                with sqlite3.connect(self.ruta) as otra:
                    otra.execute("UPDATE colocaciones SET contrato_firmado='1' WHERE id=?", (ids[1],))
            with original():
                yield
        with patch.object(self.app, "cambio_de_estados", side_effect=reservar):
            self.app.iniciar_contratos_firmados()
        self.assertEqual([self.fila(i)["estado"] for i in ids], ["Activa", "Activa"])

    def test_cierre_incorpora_vencimiento_externo_entre_lectura_y_reserva(self):
        personas = [(self.cliente("Colocado"), self.trabajadora("Trabajando")) for _ in range(2)]
        ids = [self.enlace(*personas[0], estado="Activa", fin_garantia="01/01/2026"),
               self.enlace(*personas[1], estado="Activa", fin_garantia="01/01/9999")]
        self.db.todos("colocaciones")
        original = self.app.cambio_de_estados
        @contextmanager
        def reservar():
            with sqlite3.connect(self.ruta) as otra:
                otra.execute("UPDATE colocaciones SET fin_garantia='01/01/2026' WHERE id=?", (ids[1],))
            with original():
                yield
        with patch.object(self.app, "cambio_de_estados", side_effect=reservar):
            self.app.cerrar_garantias_vencidas()
        self.assertEqual([self.fila(i)["estado"] for i in ids], ["Garantía cumplida", "Garantía cumplida"])

    def test_callback_asignar_conserva_campos_al_rechazar_y_reintentar(self):
        cli, t = self.cliente(), self.trabajadora()
        self.db.actualizar("clientes", cli, {"sueldo_ofrecido": "1000"})
        pagina = SimpleNamespace(db=self.db, app=self.app,
                                 elegidos=lambda: (self.db.uno("clientes", cli), self.db.uno("trabajadoras", t)),
                                 after_idle=Mock())
        self.app.refrescar_todo = Mock()
        self.app.abrir_asignaciones = Mock()
        with patch.object(agencia, "DialogoContrato") as dialogo:
            agencia.PaginaEnlazar.asignar(pagina)
        valores, confirmar = dialogo.call_args.args[2:4]
        valores = dict(valores, ocupacion="Oficio elegido")
        anterior = dict(valores)
        with patch.object(self.app, "crear_asignacion", side_effect=ValueError("Cambio simultáneo")), \
                patch.object(agencia.messagebox, "showwarning"):
            self.assertFalse(confirmar(valores))
        self.assertEqual(valores, anterior)
        self.assertTrue(confirmar(valores))
        self.assertEqual(valores, anterior)
        self.assertEqual(len(self.db.todos("colocaciones")), 1)
        self.assertEqual(self.db.uno("clientes", cli)["ocupacion"], "Oficio elegido")

    def test_inicio_automatico_dato_antiguo_fuera_de_calendario_no_bloquea_validos(self):
        personas = [(self.cliente("En entrevista"), self.trabajadora("En proceso")) for _ in range(2)]
        valido = self.enlace(*personas[0], contrato_firmado="1")
        invalido = self.enlace(*personas[1], contrato_firmado="1", meses_garantia="99999999999999999")
        if "dias_garantia" in agencia.claves(agencia.CAMPOS_COLOCACION):
            self.db.actualizar("colocaciones", invalido, {"dias_garantia": "0"})
        self.app.iniciar_contratos_firmados()
        self.assertEqual(self.fila(valido)["estado"], "Activa")
        self.assertEqual(self.fila(invalido)["estado"], "En proceso")


if __name__ == "__main__":
    unittest.main()
