# Agencia de Empleos — Servicio Exclusivo

Aplicación de escritorio para registrar clientes y trabajadoras, gestionar áreas y asignaciones, preparar y firmar contratos, cobrar comisiones y administrar garantías. **Versión de distribución: 1.7.1.**

## Descargar e instalar

Los instaladores incluyen Python; no hace falta instalarlo por separado.

| Equipo | Instalador |
| --- | --- |
| Windows 10 u 11 de 64 bits | [Agencia-de-Empleos-Windows-x64.exe](instaladores/Agencia-de-Empleos-Windows-x64.exe) |
| Mac con chip Apple Silicon, macOS 11.0 o posterior | [Agencia-de-Empleos-Mac-arm64.dmg](instaladores/Agencia-de-Empleos-Mac-arm64.dmg) |

En GitHub, abra el archivo correspondiente y use **Download raw file** para descargarlo. En Mac, abra el DMG y arrastre la aplicación a Aplicaciones. Consulte [LEEME.txt](LEEME.txt) para instalación y uso.

Las huellas de los dos paquetes verificados están en [SHA256SUMS.txt](instaladores/SHA256SUMS.txt).

## Ejecutar desde el código

Requiere Python con Tk 8.6 o posterior y SQLite. Se comprobó con Python 3.12 y 3.14. La aplicación utiliza la biblioteca estándar de Python.

```sh
python agencia.py --datos ./datos-locales
```

En Windows también puede usar [Iniciar.bat](Iniciar.bat). En Mac, [Crear_App_Mac.command](Crear_App_Mac.command) crea un lanzador junto al código; su requisito de macOS depende del Python instalado en ese equipo.

## Datos y actualizaciones

Cada cambio confirmado se guarda en SQLite. El programa mantiene copias locales y externas, permite elegir una carpeta adicional y conserva borradores de registros nuevos incompletos.

Los instaladores guardan la información en una carpeta separada:

- Windows: `%LOCALAPPDATA%\Agencia de Empleos`.
- Mac: `~/Library/Application Support/Agencia de Empleos`.

Guarde su trabajo y cierre la aplicación antes de actualizarla. La instalación normal conserva la carpeta de datos. Si utilizaba una versión con `agencia.db` junto al programa, conserve esa carpeta, cree un respaldo desde la aplicación original y restáurelo desde el panel de respaldos de la nueva instalación.

Este repositorio contiene únicamente el programa y sus instaladores. Los registros reales, documentos de clientes, contratos generados, respaldos, configuración y borradores permanecen fuera de Git. `.gitignore` utiliza una lista explícita de archivos permitidos.

## Pruebas

Las **309 pruebas de Servicio Exclusivo** pasaron en una copia independiente con Python 3.12, sin errores de callbacks ni pruebas omitidas. Usan registros ficticios y bases temporales; son independientes de otros proyectos. Con Python que incluya Tk y una sesión gráfica disponible:

```sh
python -m unittest discover -v
```

Las pruebas del constructor de Windows requieren `makensis`. La comprobación del recurso de versión portable necesita PyInstaller; las pruebas de recreación del lanzador utilizan las herramientas de macOS.

Las mejoras de 1.7.1 incluyen comprobación de cambios simultáneos, conservación del ejemplar firmado, protección del importe ya cobrado, redondeo decimal y preparación verificada de copias y restauraciones. Los instaladores de Mac se probaron con arranques nuevos y actualización desde datos ficticios de 1.7.0. Los instaladores Windows se compilaron e inspeccionaron; su ejecución en un equipo Windows sigue pendiente.

## Construir instaladores

- [Crear_EXE.bat](Crear_EXE.bat): genera el portable `Agencia.exe` desde Windows en un entorno temporal.
- [crear_instalador_windows.sh](instaladores/construccion/crear_instalador_windows.sh): construye el instalador Windows desde un Mac con las herramientas indicadas en el script.
- [crear_instalador_mac.sh](instaladores/construccion/crear_instalador_mac.sh): construye y verifica el DMG desde un Mac con Apple Silicon.

Los paquetes incluyen el código y los recursos gráficos de Servicio Exclusivo; los datos operativos se mantienen separados.
