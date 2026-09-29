@echo off
setlocal
cd /d "%~dp0" || goto carpeta_error
if not exist "agencia.py" goto archivo_error

set "PY=py"
set "PY_OPCIONES=-3"
set "PYW=pyw"
where py >nul 2>nul
if not errorlevel 1 goto verificar_python
set "PY=python"
set "PY_OPCIONES="
set "PYW=pythonw"
where python >nul 2>nul
if errorlevel 1 goto python_error

:verificar_python
"%PY%" %PY_OPCIONES% -c "import tkinter, sqlite3" >nul 2>nul
if errorlevel 1 goto python_error
where "%PYW%" >nul 2>nul
if errorlevel 1 goto abrir_consola
start "" "%PYW%" %PY_OPCIONES% "%~dp0agencia.py"
if errorlevel 1 goto inicio_error
exit /b 0

:abrir_consola
"%PY%" %PY_OPCIONES% "%~dp0agencia.py"
if errorlevel 1 goto inicio_error
exit /b 0

:python_error
echo No se encontro Python 3 con tkinter y sqlite3.
echo Instalelo desde https://www.python.org/downloads/
echo Marque "Add Python to PATH" y deje activado "tcl/tk and IDLE".
goto fallar
:archivo_error
echo No se encontro agencia.py junto a Iniciar.bat.
goto fallar
:carpeta_error
echo No se pudo abrir la carpeta del programa.
goto fallar
:inicio_error
echo No se pudo iniciar Agencia de Empleos. Revise errores.log en la carpeta de datos.
:fallar
pause
exit /b 1
