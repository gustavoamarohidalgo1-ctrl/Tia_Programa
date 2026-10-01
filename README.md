# Agencia de Empleos — Servicio Exclusivo

Aplicación de escritorio para registrar clientes y trabajadoras, gestionar áreas y asignaciones, preparar y firmar contratos, cobrar comisiones y administrar garantías. **Versiones de distribución: Windows 1.8.0 · Mac 1.7.1.**

## Descargar e instalar

Los instaladores incluyen Python; no hace falta instalarlo por separado.

| Equipo | Instalador |
| --- | --- |
| Windows 10 u 11 de 64 bits (también 8.1) | [Agencia-de-Empleos-Windows-x64.exe](instaladores/Agencia-de-Empleos-Windows-x64.exe) |
| Mac con chip Apple Silicon, macOS 11.0 o posterior | [Agencia-de-Empleos-Mac-arm64.dmg](instaladores/Agencia-de-Empleos-Mac-arm64.dmg) |

En GitHub, abra el archivo correspondiente y use **Download raw file** para descargarlo. En Mac, abra el DMG y arrastre la aplicación a Aplicaciones. Consulte [LEEME.txt](LEEME.txt) para instalación y uso.

### Windows: si aparece un aviso

Si lo recibe por **WhatsApp**, no lo abra desde dentro de WhatsApp (la aplicación de Windows no ejecuta archivos `.exe` y no muestra nada): guárdelo en **Descargas** y ábralo desde allí con doble clic. Tras el doble clic puede tardar unos segundos en aparecer, mientras el antivirus lo revisa.

El instalador no está firmado digitalmente, así que Windows puede advertir la primera vez:

- **Edge:** «no se descarga habitualmente» → menú **…** → **Conservar**.
- **SmartScreen:** «Windows protegió su PC» → **Más información** → **Ejecutar de todas formas**.
- **Control inteligente de aplicaciones** (Windows 11, poco común): bloquea cualquier instalador sin firma y no ofrece continuar; hay que desactivarlo en Seguridad de Windows → Control de aplicaciones y navegador.

No pide permisos de administrador. Si antes usaba `Iniciar.bat` o `Agencia.exe` con `agencia.db` junto al programa, la versión instalada ofrece traer esos datos la primera vez que se abre (o después con **Ctrl+Shift+B → Traer datos de otro archivo…**). Si el programa no llegara a abrir, el motivo queda en `arranque.log`, dentro de la carpeta de datos.

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

Las **361 pruebas** pasan en macOS (se omiten 4 que son solo de Windows); en Windows x64 las ejecuta el flujo de GitHub Actions. Usan registros ficticios y bases temporales, y nunca la carpeta de datos real aunque se ejecuten desde el proyecto; son independientes de otros proyectos. `test_windows.py` cubre comportamientos propios de Windows (archivos retenidos por el antivirus, CSV abiertos en Excel, rutas de red, datos de la versión portable); las marcadas «solo Windows» se omiten en otros sistemas. Con Python que incluya Tk y una sesión gráfica disponible:

```sh
python -m unittest discover -v
```

Las pruebas del constructor de Windows requieren `makensis`; las pruebas de recreación del lanzador utilizan las herramientas de macOS.

Las mejoras de 1.7.1 incluyen comprobación de cambios simultáneos, conservación del ejemplar firmado, protección del importe ya cobrado, redondeo decimal y preparación verificada de copias y restauraciones. Los instaladores de Mac se probaron con arranques nuevos y actualización desde datos ficticios de 1.7.0.

### Pruebas en Windows real

El flujo [Windows x64](.github/workflows/windows.yml) de GitHub Actions ejecuta el instalador en Windows Server 2022 y 2025 (x64) en cada cambio:

- instalación con sus ventanas (Siguiente, Instalar, Terminar y apertura final) y en silencio;
- apertura desde el acceso directo del menú Inicio, recorrido completo del programa (registros, asignación, contrato, copias, CSV, restauración, impresión) y cierre con la X;
- actualización encima con y sin datos, negativa a actualizar con el programa abierto y desinstalación que conserva los datos;
- actualización desde una base 1.7.0 con contratos firmados;
- antivirus de Windows con protección en tiempo real encendida, con ocho actualizaciones seguidas;
- cuentas estándar sin administrador, incluida una con tildes, eñe y espacio (`C:\Users\José Peña`);
- pantallas al 100 %, 125 % y 150 % comprobando que ningún botón ni opción del menú lateral quede cortado;
- las pruebas con Python 3.12, 3.13, 3.14 y con el Python incluido en el instalador, más `Iniciar.bat` y `Crear_EXE.bat`.

### Cambios de 1.8.0 (instalador de Windows 1.8.0; el de Mac sigue en 1.7.1)

- «Imprimir» pregunta si el contrato se abre en Word (.docx) o en PDF (en el navegador). Ambos se generan solo con la biblioteca estándar, a partir del mismo documento que se firma; si el equipo no tiene Word, esa opción aparece desactivada.
- El contrato ya no se imprime solo. Hasta la 1.7.2 la página guardada lanzaba la impresión al cargarse: cada clic en «Imprimir» y cada pestaña restaurada o recargada por el navegador sacaba otra copia. Al arrancar, el programa quita esa impresión automática de los contratos `.html` que dejaron versiones anteriores, y tras abrir el contrato la pantalla dice dónde se abrió.
- Las firmas con nombre se achican según el largo del nombre y pueden pasar a otro renglón: ya no se salen de la hoja (ni hacen que el navegador achique toda la página), tampoco en contratos firmados antes.
- «Contratos» está en el menú lateral, debajo de Áreas, con las pestañas Por firmar y Firmados y todas sus acciones (firmar, imprimir, datos del contrato, registrar inicio, deshacer). Ya no hay botón «Ver asignaciones»: al confirmar una asignación se abre Contratos con ella elegida. En pantallas bajas (1366×768) las opciones del menú se acercan para que entren todas.
- Fichas más cortas: la de la trabajadora ya no tiene la sección «Estado» (estado y notas) y la del cliente ya no pide «¿Para cuándo la necesita?» ni «Notas». El estado de la trabajadora lo pone el programa según sus asignaciones y se sigue viendo en la lista. Lo ya escrito en esos campos se conserva en la base y en las copias .csv, y una base nueva mantiene las mismas columnas. Una trabajadora que estuviera «No disponible» (solo se podía poner a mano) pasa al estado de sus asignaciones, para que no quede fuera de las listas sin forma de volver.
- Un sueldo escrito «1.500» se entiende como mil quinientos.
- Si una ficha ya guardada tiene un dato inválido, al salir se dice cuál y se ofrece volver a lo guardado (antes ni la X cerraba el programa).
- La carpeta adicional de copias solo se usa si es la elegida: no se escriben datos en otro USB que tome su letra, y uno desconectado no avisa en cada arranque. Al traer datos de la versión portable también se trae esa carpeta.
- La versión se ve en el menú lateral y en `errores.log`; los constructores la toman de `agencia.py`.
- Instalador de Windows: un archivo que no se pudo escribir ya no se puede «Omitir», cualquier error al copiar deja la versión anterior, el aviso no dice «no se modificó nada» si no pudo volver atrás, y un instalador más viejo advierte antes de reemplazar uno más nuevo.

### Cambios de Windows 1.7.2

- El instalador ya no mueve archivos recién escritos (el antivirus los retiene y la actualización fallaba): aparta la versión instalada con reintentos, escribe la nueva en su lugar y, si algo falla, deja todo como estaba.
- Los errores de arranque quedan en `arranque.log` y se muestran; antes el programa se cerraba sin decir nada.
- Ofrece traer los datos de la versión portable (`Iniciar.bat` o `Agencia.exe`).
- Un CSV abierto en Excel ya no anula la copia externa; las carpetas de red funcionan para copias; los botones de «Copias de seguridad» y «Eliminar área» ya no quedan fuera de la ventana; las ventanas respetan la escala de pantalla y la barra de tareas.
- El acceso directo se puede anclar a la barra de tareas y el programa ignora variables de Python o Tcl de otros programas.

## Construir instaladores

- [Crear_EXE.bat](Crear_EXE.bat): genera el portable `Agencia.exe` desde Windows en un entorno temporal.
- [crear_instalador_windows.sh](instaladores/construccion/crear_instalador_windows.sh): construye el instalador Windows desde un Mac con las herramientas indicadas en el script.
- [crear_instalador_mac.sh](instaladores/construccion/crear_instalador_mac.sh): construye y verifica el DMG desde un Mac con Apple Silicon.

Los paquetes incluyen el código y los recursos gráficos de Servicio Exclusivo; los datos operativos se mantienen separados.
