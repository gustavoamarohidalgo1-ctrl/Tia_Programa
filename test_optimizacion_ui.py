"""Regresiones de listas reutilizadas sobre SQLite y Tk reales con datos ficticios."""
import os
import tempfile
import sqlite3
import unittest
from contextlib import ExitStack
from datetime import timedelta
from pathlib import Path
from unittest import mock

if not os.environ.get("AGENCIA_DATOS"):      # nunca la carpeta de datos real, aunque se pruebe desde el proyecto
    os.environ["AGENCIA_DATOS"] = tempfile.mkdtemp(prefix="agencia-pruebas-")

import agencia


class OptimizacionInterfazTest(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory(prefix="agencia-ui-test-")
        self.carpeta = Path(self.temporal.name)
        self.parches = ExitStack()
        for nombre, ruta in (("DB_PATH", "agencia.db"), ("CONFIG_PATH", "configuracion.json"),
                             ("CARPETA_RESPALDOS", "respaldos"), ("CARPETA_CONTRATOS", "contratos"),
                             ("ERRORES_PATH", "errores.log")):
            self.parches.enter_context(mock.patch.object(agencia, nombre, str(self.carpeta / ruta)))
        self.parches.enter_context(mock.patch.object(agencia, "carpetas_externas", return_value=[]))
        self.parches.enter_context(mock.patch.object(agencia, "maximizar", return_value=None))
        self.parches.enter_context(mock.patch.object(agencia.App, "hacer_copia_en_segundo_plano", return_value=None))
        self.parches.enter_context(mock.patch.object(agencia.App, "vigilar_cambios", return_value=None))
        self.avisos = []
        for nombre in ("showinfo", "showwarning", "showerror", "askyesno"):
            self.parches.enter_context(mock.patch.object(agencia.messagebox, nombre,
                side_effect=lambda titulo, texto, **kw: self.avisos.append((titulo, texto)) and False))
        try:
            self.root = agencia.tk.Tk()
        except agencia.tk.TclError:
            self.parches.close()
            self.temporal.cleanup()
            self.skipTest("Tk necesita una pantalla disponible")
        self.root.withdraw()
        self.app = agencia.App(self.root)
        self.db = self.app.db
        self.area = next(iter(agencia.AREAS))

    def tearDown(self):
        # Cancelar en Tcl conserva los comandos Python para que destroy los limpie una sola vez.
        if not getattr(self, "_raiz_destruida", False):
            for timer in self.root.tk.call("after", "info"):
                self.root.tk.call("after", "cancel", timer)
        self.db.con.close()
        if not getattr(self, "_raiz_destruida", False):
            self.root.destroy()
        self.parches.close()
        agencia.restablecer_areas()
        self.temporal.cleanup()

    def clientes(self, cantidad=40):
        with self.db.lote():
            ids = [self.db.insertar("clientes", {
                "nombre": f"Cliente {i:03d} {'GrupoA' if i % 2 else 'GrupoB'}", "telefono": f"999{i:06d}",
                "tipo_servicio": self.area, "estado": "Pendiente", "sueldo_ofrecido": "1800"})
                for i in range(cantidad)]
        self.app.clientes.cargar_lista()
        return ids

    def trabajadora(self, nombre="Zeta", **datos):
        return self.db.insertar("trabajadoras", dict({"nombre": nombre, "telefono": "999",
            "tipo_servicio": self.area, "estado": "Disponible", "doc_dni": "1"}, **datos))

    def asignacion(self, cliente, trabajadora, **datos):
        return self.db.insertar("colocaciones", dict({"cliente_id": str(cliente),
            "trabajadora_id": str(trabajadora), "estado": "En proceso", "comision": "900",
            "sueldo_acordado": "1800", "garantia": "Sí", "meses_garantia": "2",
            "comision_pagada": "0", "contrato_firmado": "0", "fecha_enlace": agencia.hoy()}, **datos))

    def buscar(self, texto):
        p = self.app.clientes
        p.busqueda.vacio = False
        p.busqueda.var.set(texto)
        p.cargar_lista()

    def foto(self, tabla):
        return [(iid, tabla.item(iid, "values"), tabla.item(iid, "tags")) for iid in tabla.get_children()]

    def test_buscar_reutiliza_filas_y_respeta_orden_y_colores_alternos(self):
        ids = self.clientes()
        tabla = self.app.clientes.lista
        inicial = self.foto(tabla)
        with mock.patch.object(tabla, "insert", wraps=tabla.insert) as insertar, \
             mock.patch.object(tabla, "delete", wraps=tabla.delete) as borrar:
            self.buscar("GrupoA")
            visibles = tabla.get_children()
            self.assertEqual(visibles, tuple(str(i) for i in reversed(ids) if (i - ids[0]) % 2))
            self.assertTrue(tabla.exists(str(ids[0])))  # Se mantiene desprendida, sin duplicarla al volver.
            for indice, iid in enumerate(visibles):
                self.assertEqual(tabla.item(iid, "tags"), ("impar" if indice % 2 else "par",))
            self.buscar("")
            self.assertEqual(self.foto(tabla), inicial)
            insertar.assert_not_called()
            borrar.assert_not_called()

    def test_busqueda_consulta_campos_guardados_no_visibles(self):
        ids = self.clientes(3)
        self.db.actualizar("clientes", ids[1], {"meses_garantia": "8675309"})
        self.buscar("8675309")
        self.assertEqual(self.app.clientes.lista.get_children(), (str(ids[1]),))

    def test_edicion_con_filtro_actualiza_un_indice_y_la_pertenencia(self):
        ids = self.clientes(20)
        p = self.app.clientes
        self.buscar("unico")
        with mock.patch.object(p, "_entrada_de_lista", wraps=p._entrada_de_lista) as entrada:
            self.db.actualizar("clientes", ids[7], {"zona": "Unico"})
            p.cargar_lista()
            self.assertEqual(entrada.call_count, 1)
        self.assertEqual(p.lista.get_children(), (str(ids[7]),))
        with mock.patch.object(p, "_sincronizar_tabla", wraps=p._sincronizar_tabla) as sincronizar:
            self.db.actualizar("clientes", ids[7], {"zona": "Unico revisado"})
            p.cargar_lista()
            sincronizar.assert_not_called()  # Misma pertenencia: sólo se toca la fila editada.
        self.assertIn("Unico revisado", " ".join(p.lista.item(str(ids[7]), "values")))
        self.db.actualizar("clientes", ids[7], {"zona": "Otro"})
        p.cargar_lista()
        self.assertEqual(p.lista.get_children(), ())
        self.db.actualizar("clientes", ids[7], {"zona": "Otro revisado"})
        p.cargar_lista()
        self.buscar("Otro revisado")
        self.assertEqual(p.lista.get_children(), (str(ids[7]),))
        self.assertIn("Otro revisado", " ".join(p.lista.item(str(ids[7]), "values")))

    def test_borrar_filas_visibles_y_ocultas_limpia_memoria_y_seleccion(self):
        ids = self.clientes(4)
        self.buscar("GrupoA")
        p = self.app.clientes
        p.lista.selection_set(str(ids[1]))
        with self.db.lote():
            self.db.eliminar("clientes", ids[0])
            self.db.eliminar("clientes", ids[1])
        p.cargar_lista()
        self.assertFalse(p.lista.exists(str(ids[0])))
        self.assertFalse(p.lista.exists(str(ids[1])))
        self.assertEqual(p.lista.selection(), ())
        self.assertNotIn(str(ids[0]), p._lista_estado["filas"])

    def test_refresco_y_filtro_conservan_seleccion_y_desplazamiento(self):
        ids = self.clientes(40)
        p = self.app.clientes
        p.lista.selection_set(str(ids[20]))
        p.lista.focus(str(ids[20]))
        p.lista.yview_moveto(.35)
        p.lista.column("nombre", width=2000)
        p.lista.xview_moveto(.2)
        antes = p.lista.yview()[0]
        horizontal = p.lista.xview()[0]
        self.buscar("Cliente")
        self.assertEqual(p.lista.selection(), (str(ids[20]),))
        self.assertAlmostEqual(p.lista.yview()[0], antes, places=2)
        self.assertAlmostEqual(p.lista.xview()[0], horizontal, places=2)
        self.assertEqual(p.lista.focus(), str(ids[20]))
        self.db.actualizar("clientes", ids[3], {"zona": "Cambio"})
        p.cargar_lista()
        self.assertEqual(p.lista.selection(), (str(ids[20]),))
        self.assertAlmostEqual(p.lista.yview()[0], antes, places=2)
        self.assertAlmostEqual(p.lista.xview()[0], horizontal, places=2)
        self.buscar("sin coincidencias")
        self.assertEqual(p.lista.selection(), ())
        self.assertEqual(p.lista.focus(), "")

    def test_cambiar_cliente_no_reconstruye_candidatas_y_mantiene_trabajadora(self):
        ids = self.clientes(3)
        tid = self.trabajadora()
        for i in range(10):
            self.trabajadora(f"Candidata {i}")
        e = self.app.enlazar
        e.poner_area(self.area)
        e.cargar_candidatas()
        e.t_trab.selection_set(str(tid))
        with mock.patch.object(e.t_trab, "insert", wraps=e.t_trab.insert) as insertar, \
             mock.patch.object(e.t_trab, "delete", wraps=e.t_trab.delete) as borrar, \
             mock.patch.object(agencia, "docs_presentados", wraps=agencia.docs_presentados) as documentos:
            for cid in ids:
                e.t_clientes.selection_set(str(cid))
                e.cargar_candidatas()
                self.assertEqual(e.elegidos()[0]["id"], cid)
                self.assertEqual(e.elegidos()[1]["id"], tid)
            insertar.assert_not_called()
            borrar.assert_not_called()
            # El perfil seleccionado sí consulta documentos; todas las otras filas se reutilizan.
            self.assertGreaterEqual(documentos.call_count, len(ids))
            self.assertLessEqual(documentos.call_count, 2 * len(ids))

    def test_candidatas_se_actualizan_por_documentos_disponibilidad_y_area(self):
        cid = self.clientes(1)[0]
        tid = self.trabajadora("Zeta")
        otra = next(a for a in agencia.AREAS if a != self.area)
        extra = self.trabajadora("Alfa", tipo_servicio=otra)
        e = self.app.enlazar
        e.poner_area(self.area, cid)
        e.cargar_candidatas()
        self.assertEqual(e.t_trab.get_children(), (str(tid),))
        e.otras_areas.set(True)
        e.cargar_candidatas()
        self.assertEqual(e.t_trab.get_children(), (str(extra), str(tid)))
        e.t_trab.selection_set(str(tid))
        self.db.actualizar("trabajadoras", tid, {"doc_dni": "0"})
        e.refrescar()
        e.cargar_candidatas()
        self.assertIn("0/", e.t_trab.item(str(tid), "values")[-1])
        self.db.actualizar("trabajadoras", tid, {"estado": "Ocupada"})
        e.refrescar()
        e.cargar_candidatas()
        self.assertEqual(e.t_trab.get_children(), (str(extra),))
        self.assertEqual(e.t_trab.selection(), ())

    def test_cliente_forzado_y_reemplazo_refrescan_sin_perder_semantica(self):
        cid = self.clientes(1)[0]
        tid = self.trabajadora()
        e = self.app.enlazar
        self.db.actualizar("clientes", cid, {"estado": "Colocado"})
        e.poner_area(self.area, cid)
        self.assertEqual(e.t_clientes.get_children(), (str(cid),))
        e.refrescar()
        self.assertEqual(e.t_clientes.get_children(), ())
        self.db.actualizar("clientes", cid, {"estado": "Pendiente"})
        enlace = self.asignacion(cid, tid, estado="Reemplazo solicitado")
        e.refrescar()
        self.assertIn("reemplazo", e.t_clientes.item(str(cid), "values")[0])
        self.asignacion(cid, tid, reemplazo_de=str(enlace))
        e.refrescar()
        self.assertNotIn("reemplazo", e.t_clientes.item(str(cid), "values")[0])

    def test_enlaces_refrescar_y_contar_comparten_filtros_y_filas(self):
        cid = self.clientes(1)[0]
        tid = self.trabajadora()
        aid = self.asignacion(cid, tid)
        p = self.app.contratos
        p.refrescar()
        p.lista.selection_set(str(aid))
        with mock.patch.object(p, "en_filtro", wraps=p.en_filtro) as filtrar, \
             mock.patch.object(p, "valores", wraps=p.valores) as valores, \
             mock.patch.object(p.lista, "insert", wraps=p.lista.insert) as insertar:
            for _ in range(4):
                self.assertEqual(p.contar(), 1)
                p.refrescar()
            filtrar.assert_not_called()
            valores.assert_not_called()
            insertar.assert_not_called()
        self.assertEqual(p.lista.selection(), (str(aid),))

    def test_cambios_de_nombre_y_enlace_invalidan_valores_y_filtros(self):
        cid = self.clientes(1)[0]
        tid = self.trabajadora()
        aid = self.asignacion(cid, tid)
        p = self.app.contratos
        p.refrescar()
        self.db.actualizar("clientes", cid, {"nombre": "Nombre nuevo"})
        p.refrescar()
        self.assertIn("Nombre nuevo", " ".join(p.lista.item(str(aid), "values")))
        self.db.actualizar("colocaciones", aid, {"contrato_firmado": "1"})
        p.refrescar()
        self.assertEqual(p.contar(), 0)
        self.assertEqual(p.lista.get_children(), ())
        p.poner_filtro("firmados")
        self.assertEqual(p.lista.get_children(), (str(aid),))

    def test_cambio_de_dia_invalida_garantia_aunque_no_cambie_sqlite(self):
        cid = self.clientes(1)[0]
        tid = self.trabajadora()
        self.asignacion(cid, tid, estado="Activa", fecha_inicio=agencia.hoy(), fin_garantia=agencia.hoy())
        p = self.app.garantias
        p.refrescar()
        hoy = agencia.date.today()
        with mock.patch.object(agencia, "date", wraps=agencia.date) as fecha:
            fecha.today.return_value = hoy + timedelta(days=1)
            with mock.patch.object(p, "en_filtro", wraps=p.en_filtro) as filtrar:
                p.refrescar()
                self.assertGreater(filtrar.call_count, 0)
            self.assertEqual(p.contar(), 0)
            self.assertIn("Cumplida", " ".join(map(str, p.valores(self.db.todos("colocaciones")[0]))))

    def test_ganancias_reutiliza_paneles_y_comparte_resumen_con_comisiones(self):
        cid = self.clientes(1)[0]
        tid = self.trabajadora()
        aid = self.asignacion(cid, tid, comision_pagada="1", fecha_pago=agencia.hoy())
        g = self.app.ganancias
        with mock.patch.object(agencia, "resumen_ganancias", wraps=agencia.resumen_ganancias) as calcular:
            self.app.comisiones.refrescar()
            g.refrescar()
            self.assertEqual(calcular.call_count, 1)
            widgets = tuple(g.lista_areas.winfo_children())
            pagos = self.foto(g.lista_pagos)
            g.refrescar()
            self.assertEqual(tuple(g.lista_areas.winfo_children()), widgets)
            self.assertEqual(self.foto(g.lista_pagos), pagos)
            self.assertEqual(calcular.call_count, 1)
        self.db.actualizar("colocaciones", aid, {"comision": "600"})
        g.refrescar()
        self.assertEqual(tuple(g.lista_areas.winfo_children()), widgets)
        self.assertIn(agencia.dinero(600), g.lista_pagos.item(str(aid), "values")[-1])
        self.db.actualizar("colocaciones", aid, {"comision_pagada": "0"})
        g.refrescar()
        self.assertEqual(g.lista_pagos.get_children(), ())
        self.assertTrue(g.sin_pagos.winfo_manager())

    def test_snapshot_formulario_no_sobrescribe_cambios_externos_no_editados(self):
        cid = self.clientes(1)[0]
        p = self.app.clientes
        p.lista.selection_set(str(cid))
        p.al_seleccionar()
        self.db.actualizar("clientes", cid, {"zona": "Actualizada fuera"})
        self.assertFalse(p.cambios_sin_guardar())
        p.form.poner_valor("nombre", "Nombre editado")
        self.assertTrue(p.guardar())
        self.assertEqual(self.db.uno("clientes", cid)["zona"], "Actualizada fuera")
        self.assertEqual(self.db.uno("clientes", cid)["nombre"], "Nombre editado")
        self.assertFalse(p.cambios_sin_guardar())

    def test_conflicto_de_edicion_conserva_formulario_y_bloquea_cambio(self):
        cid = self.clientes(1)[0]
        p = self.app.clientes
        p.lista.selection_set(str(cid))
        p.al_seleccionar()
        p.form.poner_valor("nombre", "Mi cambio")
        self.db.actualizar("clientes", cid, {"nombre": "Cambio externo"})
        self.assertFalse(p.resolver_cambios())
        self.assertEqual(p.form.obtener()["nombre"], "Mi cambio")
        self.assertEqual(self.db.uno("clientes", cid)["nombre"], "Cambio externo")
        self.assertEqual(self.avisos[-1][0], "Cambios simultáneos")

    def test_destruir_raiz_cancela_timers_y_cierra_sqlite(self):
        timer = self.root.after(60_000, lambda: None)
        self.assertIn(timer, self.root.tk.call("after", "info"))
        self.root.destroy()
        self._raiz_destruida = True
        self.assertNotIn(timer, self.root.tk.call("after", "info"))
        with self.assertRaises(sqlite3.ProgrammingError):
            self.db.con.execute("SELECT 1")

    def test_candidatas_diferidas_usan_ultima_revision_de_varios_refrescos(self):
        self.clientes(1)
        tid = self.trabajadora("Primera versión")
        e = self.app.enlazar
        e.refrescar()
        e.cargar_candidatas()
        for nombre in ("Segunda versión", "Última versión"):
            self.db.actualizar("trabajadoras", tid, {"nombre": nombre})
            e.refrescar()  # Varias reconstrucciones de fuentes antes de ejecutar after_idle.
        e.cargar_candidatas()
        self.assertIn("Última versión", e.t_trab.item(str(tid), "values")[0])

    def test_guardar_y_seleccionar_no_eligen_filas_ocultas_por_busqueda(self):
        cid = self.clientes(1)[0]
        p = self.app.clientes
        p.seleccionar(cid)
        p.al_seleccionar()
        self.buscar("sin coincidencias")
        self.assertTrue(p.lista.exists(str(cid)))
        p.seleccionar(cid)
        self.assertEqual(p.lista.selection(), ())
        p.form.poner_valor("zona", "Edición con búsqueda activa")
        self.assertTrue(p.guardar())
        self.assertEqual(p.lista.selection(), ())
        self.assertEqual(self.db.uno("clientes", cid)["zona"], "Edición con búsqueda activa")

    def test_insercion_nativa_preserva_texto_literal_tags_y_orden(self):
        tabla = agencia.ttk.Treeview(self.root, columns=("a", "b"), show="headings")
        iid = "fila ; {$}[]"
        valores = ("Árbol ; [literal] {$variable}" + chr(10) + "Línea nueva 😀", 'Comillas " y \\ barra')
        estado = {}
        agencia.Pagina._sincronizar_tabla(tabla, estado, [(iid, valores, ("alerta", "impar"))])
        self.assertEqual(tabla.get_children(), (iid,))
        self.assertEqual(tabla.item(iid, "values"), valores)
        self.assertEqual(tabla.item(iid, "tags"), ("alerta", "impar"))
        agencia.Pagina._sincronizar_tabla(tabla, estado, [("segunda", ("0007", ""), ()),
                                                        (iid, valores, ("alerta", "impar"))])
        self.assertEqual(tabla.get_children(), ("segunda", iid))
        self.assertEqual(tabla.item("segunda", "values"), ("0007", ""))
        self.assertEqual(tuple(tabla.item("segunda", "tags")), ())
        tabla.destroy()


if __name__ == "__main__":
    unittest.main()
