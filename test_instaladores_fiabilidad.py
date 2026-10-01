"""Comprueba instaladores de Servicio Exclusivo con recursos ficticios, sin generar entregables."""
from pathlib import Path
import ast
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest


RAIZ = Path(__file__).resolve().parent
VERSION = re.search(r'^VERSION = "([0-9.]+)"', (RAIZ / "agencia.py").read_text(encoding="utf-8"), re.M).group(1)


class InstaladoresProtegidos(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "darwin", "Crear_App_Mac.command solo se ejecuta en Mac")
    def test_launcher_rechaza_proceso_vivo_antes_de_tocar_bundle(self):
        for proyecto, marca, ejecutable in ((RAIZ, "Agencia de Empleos", "Agencia"),):
            with self.subTest(proyecto=proyecto.name), tempfile.TemporaryDirectory(prefix="launcher-fiabilidad-") as tmp:
                temporal = Path(tmp)
                script = temporal / "Crear_App_Mac.command"
                shutil.copy2(proyecto / script.name, script)
                app = temporal / f"{marca}.app"
                (app / "Contents").mkdir(parents=True)
                metadata = app / "Contents/Info.plist"
                metadata.write_bytes(b"Bundle anterior ficticio e intacto")
                antes = {p.relative_to(temporal): p.read_bytes() for p in temporal.rglob("*") if p.is_file()}
                proceso = subprocess.Popen([sys.executable, "-c", "import time; print('listo', flush=True); time.sleep(30)",
                                            str(app / f"Contents/MacOS/{ejecutable}")],
                                           stdout=subprocess.PIPE, text=True)
                try:
                    self.assertEqual(proceso.stdout.readline().strip(), "listo")
                    resultado = subprocess.run(["/bin/bash", str(script)], capture_output=True, text=True, timeout=10)
                    self.assertNotEqual(resultado.returncode, 0)
                    self.assertIn("Procesos activos: " + str(proceso.pid), resultado.stderr)
                    despues = {p.relative_to(temporal): p.read_bytes() for p in temporal.rglob("*") if p.is_file()}
                    self.assertEqual(despues, antes)
                    self.assertEqual(set(temporal.iterdir()), {script, app})
                finally:
                    proceso.terminate()
                    proceso.wait(timeout=10)
                    proceso.stdout.close()

    def test_exe_portable_tiene_version_y_publica_sin_sobrescribir_anterior(self):
        for proyecto, marca in ((RAIZ, "Agencia de Empleos"),):
            with self.subTest(proyecto=proyecto.name):
                metadata = ast.parse((proyecto / "instaladores/construccion/version_windows.txt").read_text(encoding="utf-8"))
                cadenas = {n.args[0].value: n.args[1].value for n in ast.walk(metadata)
                           if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "StringStruct"}
                self.assertEqual(cadenas["ProductName"], marca)
                self.assertEqual(cadenas["ProductVersion"], VERSION)          # la misma de agencia.py
                self.assertEqual(cadenas["FileVersion"], VERSION)
                fijo = next(n for n in ast.walk(metadata) if isinstance(n, ast.Call)
                            and isinstance(n.func, ast.Name) and n.func.id == "FixedFileInfo")
                numeros = tuple(int(n) for n in (VERSION.split(".") + ["0"] * 4)[:4])
                self.assertEqual({k.arg: ast.literal_eval(k.value) for k in fijo.keywords
                                  if k.arg in ("filevers", "prodvers")}, {"filevers": numeros, "prodvers": numeros})
                bat = (proyecto / "Crear_EXE.bat").read_bytes()
                self.assertEqual(bat.count(b"\n"), bat.count(b"\r\n"))
                texto = bat.decode("ascii")
                self.assertIn("--version-file", texto)
                nombre = re.search(r"--name ([A-Za-z0-9_-]+)\b", texto).group(1)
                salida_compilada = "%TRABAJO%\\dist\\" + nombre + ".exe"
                self.assertIn('if not exist "' + salida_compilada + '"', texto)
                origen_publicado = re.search(r'^copy /y "([^"]+)" "%NUEVO%"', texto, re.MULTILINE).group(1)
                self.assertEqual(origen_publicado, salida_compilada)
                self.assertIn('move /y "%NUEVO%"', texto)
                self.assertIn('if defined HABIA_ANTERIOR move', texto)
                self.assertNotIn('copy /y "%TRABAJO%\\dist', texto.split('set "NUEVO=', 1)[0])

    def test_guion_principal_compila_con_guardias_y_staging(self):
        compilador = shutil.which("makensis")
        if not compilador:
            self.skipTest("No hay compilador NSIS en este equipo")
        for proyecto in (RAIZ,):
            with self.subTest(proyecto=proyecto.name), tempfile.TemporaryDirectory(prefix="nsis-fiabilidad-") as tmp:
                temporal = Path(tmp)
                runtime = temporal / "runtime"
                app = temporal / "app"
                runtime.mkdir()
                app.mkdir()
                (runtime / "pythonw.exe").write_bytes(b"Recurso ficticio; no ejecutable")
                (app / "iniciar.pyw").write_text("# Recurso ficticio\n")
                original = (proyecto / "icono.ico").read_bytes()
                cantidad = struct.unpack("<H", original[4:6])[0]
                entradas = [struct.unpack("<BBBBHHII", original[6+16*i:22+16*i]) for i in range(cantidad)]
                entradas = [e for e in entradas if e[0] != 0]
                posicion = 6 + 16*len(entradas)
                tabla = b""
                imagenes = b""
                for ancho, alto, color, reservado, plano, bits, tamano, offset in entradas:
                    tabla += struct.pack("<BBBBHHII", ancho, alto, color, reservado, plano, bits,
                                         tamano, posicion+len(imagenes))
                    imagenes += original[offset:offset+tamano]
                icono = temporal / "icono.ico"
                icono.write_bytes(struct.pack("<HHH", 0, 1, len(entradas)) + tabla + imagenes)
                fuente = proyecto / "instaladores/construccion/instalador.nsi"
                guion = temporal / "fixture.nsi"
                guion.write_bytes(b"\xef\xbb\xbf" + fuente.read_bytes())
                salida = temporal / "fixture.exe"
                compilacion = subprocess.run([
                    compilador, "-V3", f"-DRAIZ={proyecto}", f"-DAPLICACION={app}",
                    f"-DRUNTIME={runtime}", f"-DVERSION={VERSION}", f"-DSALIDA={salida}",
                    f"-DICONO={icono}", str(guion)], capture_output=True, text=True,
                    env={**os.environ, "LC_ALL": "en_US.UTF-8"}, timeout=30)
                self.assertEqual(compilacion.returncode, 0, compilacion.stdout + compilacion.stderr)
                self.assertTrue(salida.is_file())
                contenido = salida.read_bytes()
                self.assertTrue(contenido.startswith(b"MZ"))

    def test_guardias_preceden_borrados_y_datos_no_se_incluyen_en_staging(self):
        for proyecto in (RAIZ,):
            with self.subTest(proyecto=proyecto.name):
                fuente = (proyecto / "instaladores/construccion/instalador.nsi").read_text(encoding="utf-8")
                instalar = fuente.split('Section "Instalar"', 1)[1].split("SectionEnd", 1)[0]
                self.assertNotIn('RMDir /r "$INSTDIR\\runtime"', instalar)
                self.assertNotIn('RMDir /r "$INSTDIR\\app"', instalar)
                self.assertLess(instalar.index("Call ComprobarArchivosEnUso"), instalar.index("File /r"))
                self.assertLess(instalar.index("Call ComprobarDatosHeredados"), instalar.index("File /r"))
                # La versión anterior se aparta (con reintentos) antes de escribir la nueva...
                apartar = instalar.index('StrCpy $Destino "${ANTERIOR}\\runtime"')
                self.assertLess(apartar, instalar.index("File /r"))
                self.assertIn("Call MoverConReintentos", instalar[apartar:apartar + 120])
                self.assertIn("StrCmp $Movido 1 0 no_se_pudo_apartar", instalar)
                # ...y la nueva se escribe en su lugar: nunca se mueve un árbol recién extraído (el antivirus lo retiene).
                self.assertNotIn("Rename", instalar)
                self.assertIn('SetOutPath "$INSTDIR\\runtime"', instalar)
                self.assertIn("Goto extraccion_incompleta", instalar)
                self.assertIn("Call RestaurarVersionAnterior", instalar.split("no_se_pudo_apartar:", 1)[1])
                desinstalar = fuente.split('Section "Uninstall"', 1)[1]
                self.assertLess(desinstalar.index("Call un.ComprobarArchivosEnUso"), desinstalar.index("RMDir /r"))
                self.assertLess(desinstalar.index("Call un.ComprobarDatosHeredados"), desinstalar.index("RMDir /r"))
                guardia = (proyecto / "instaladores/construccion/archivos_en_uso.nsh").read_text(encoding="utf-8")
                # Sin Restart Manager (los antivirus lo asocian con programas dañinos y bloqueaban el instalador):
                # el programa abierto se detecta porque Windows no deja abrir para escritura sus archivos cargados.
                self.assertNotIn("rstrtmgr", guardia)
                # Como el 1.6.3 que la tía instaló sin problemas: nada de plugins antes de la primera ventana (los
                # antivirus miran con lupa un instalador sin firma que carga código de TEMP al arrancar).
                inicio = guardia.split("Function ${PREFIJO}.onInit", 1)[1].split("FunctionEnd", 1)[0]
                self.assertNotIn("System::", inicio)
                self.assertNotIn("RunningX64", inicio)
                self.assertNotIn("CoCreateInstance", fuente + guardia)
                self.assertNotIn("Win\\COM.nsh", fuente)
                self.assertIn('FileOpen $R7 "$Origen" a', guardia)
                reintentos = guardia.split("Function ${PREFIJO}MoverConReintentos", 1)[1].split("FunctionEnd", 1)[0]
                self.assertIn("Sleep", reintentos)
                self.assertIn("Function .onInstFailed", guardia)
                self.assertNotIn("RmShutdown", guardia)
                for recurso in ("agencia.db", "contratos", "respaldos", "configuracion.json", "borradores.json", "errores.log"):
                    self.assertIn(recurso, guardia)

    def test_los_constructores_toman_la_version_de_agencia_py(self):
        for archivo in ("instaladores/construccion/crear_instalador_windows.sh",
                        "instaladores/construccion/crear_instalador_mac.sh", "Crear_App_Mac.command"):
            with self.subTest(archivo=archivo):
                texto = (RAIZ / archivo).read_text(encoding="utf-8")
                self.assertIn("agencia.py", texto)
                self.assertNotRegex(texto, r'(VERSION:-|Version": )"?\d+\.\d+')     # ningún número escrito a mano


if __name__ == "__main__":
    unittest.main()
