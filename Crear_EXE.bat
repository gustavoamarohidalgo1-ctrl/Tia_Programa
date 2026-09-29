@echo off
setlocal
cd /d "%~dp0" || goto fallar
for %%F in (agencia.py logo.png icono.png icono.ico instaladores\construccion\version_windows.txt) do if not exist "%%F" (
  echo Falta %%F en la carpeta del programa.
  goto fallar
)

set "PY=py"
set "PY_OPCIONES=-3"
where py >nul 2>nul
if not errorlevel 1 goto verificar_python
set "PY=python"
set "PY_OPCIONES="
where python >nul 2>nul
if errorlevel 1 goto python_error

:verificar_python
"%PY%" %PY_OPCIONES% -c "import tkinter, sqlite3, venv"
if errorlevel 1 goto python_error
set "TRABAJO=%TEMP%\agencia-exe-%RANDOM%-%RANDOM%"
if exist "%TRABAJO%" goto fallar
mkdir "%TRABAJO%"
if errorlevel 1 goto fallar
"%PY%" %PY_OPCIONES% -m venv "%TRABAJO%\venv"
if errorlevel 1 goto fallar
"%TRABAJO%\venv\Scripts\python.exe" -m pip install --disable-pip-version-check pyinstaller
if errorlevel 1 goto fallar
"%TRABAJO%\venv\Scripts\python.exe" -m PyInstaller --noconfirm --onefile --windowed --name Agencia --icon "%~dp0icono.ico" --version-file "%~dp0instaladores\construccion\version_windows.txt" --add-data "%~dp0logo.png;." --add-data "%~dp0icono.png;." --add-data "%~dp0icono.ico;." --distpath "%TRABAJO%\dist" --workpath "%TRABAJO%\build" --specpath "%TRABAJO%" "%~dp0agencia.py"
if errorlevel 1 goto fallar
if not exist "%TRABAJO%\dist\Agencia.exe" goto fallar
set "NUEVO=%~dp0Agencia-nuevo-%RANDOM%-%RANDOM%.exe"
set "ANTERIOR=%~dp0Agencia-anterior-%RANDOM%-%RANDOM%.exe"
if exist "%NUEVO%" goto fallar
if exist "%ANTERIOR%" goto fallar
copy /y "%TRABAJO%\dist\Agencia.exe" "%NUEVO%"
if errorlevel 1 goto fallar
set "HABIA_ANTERIOR="
if not exist "%~dp0Agencia.exe" goto publicar
move /y "%~dp0Agencia.exe" "%ANTERIOR%"
if errorlevel 1 goto fallar
set "HABIA_ANTERIOR=1"
:publicar
move /y "%NUEVO%" "%~dp0Agencia.exe"
if not errorlevel 1 goto publicado
if defined HABIA_ANTERIOR move /y "%ANTERIOR%" "%~dp0Agencia.exe"
goto fallar
:publicado
if defined HABIA_ANTERIOR echo La version anterior se conserva en: %ANTERIOR%
rmdir /s /q "%TRABAJO%"
echo.
echo Listo: Agencia.exe esta en esta carpeta y contiene su logo e iconos.
echo Conserve agencia.db junto al EXE para continuar usando los datos actuales.
pause
exit /b 0

:python_error
echo No se encontro Python 3 con tkinter, sqlite3 y venv.
echo Instalelo desde https://www.python.org/downloads/
echo Marque "Add Python to PATH" y deje activado "tcl/tk and IDLE".
:fallar
echo.
echo No se pudo crear Agencia.exe. Revise el error mostrado arriba.
if defined TRABAJO echo Los archivos de construccion se conservan en: %TRABAJO%
pause
exit /b 1
