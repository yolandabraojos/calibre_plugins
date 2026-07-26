@echo off
REM ---------------------------------------------------------------------------
REM Duplicados EXACTOS (100%) en tus bibliotecas de Calibre, sin abrir Calibre.
REM
REM FASE 1 - ESCANEO (lento; Calibre puede estar abierto, es solo lectura):
REM     dedupe.cmd --root "D:\Bibliotecas"
REM   -> deja un informe HTML y un plan .plan.json
REM
REM FASE 2 - BORRADO (segundos; cierra Calibre antes):
REM     dedupe.cmd --apply "duplicados_20260726_101500.plan.json"
REM
REM Otras opciones utiles:
REM     --doctor                          comprobar el entorno y salir
REM     --list-libraries                  solo listar lo que encontraria
REM     -l "D:\Lib A" -l "E:\Lib B"       bibliotecas concretas
REM     --prefer-library "D:\Principal"   conservar siempre la copia de ahi
REM     --skip-cross                      no borrar entre bibliotecas distintas
REM   (ojo: no termines las rutas en \ dentro de las comillas)
REM
REM Elige interprete solo: el Python del sistema si tiene lxml, y si no el que
REM trae Calibre (que lo incluye siempre). Sin lxml el texto extraido seria
REM distinto y se perderian duplicados, asi que no se ejecuta sin el.
REM ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"
set "SCRIPT=%~dp0ebook_comparator\dedupe_cli.py"
if "%~1"=="" goto ayuda

where python >nul 2>nul
if errorlevel 1 goto usecalibre
python -c "import lxml" >nul 2>nul
if errorlevel 1 goto usecalibre
python "%SCRIPT%" %*
goto end

:usecalibre
set "CDBG="
where calibre-debug >nul 2>nul
if not errorlevel 1 set "CDBG=calibre-debug"
if not defined CDBG if exist "%PROGRAMFILES%\Calibre2\calibre-debug.exe" set "CDBG=%PROGRAMFILES%\Calibre2\calibre-debug.exe"
if not defined CDBG if exist "%PROGRAMFILES(X86)%\Calibre2\calibre-debug.exe" set "CDBG=%PROGRAMFILES(X86)%\Calibre2\calibre-debug.exe"
if not defined CDBG goto nointerp
echo [dedupe] Tu Python no tiene lxml: uso el interprete de Calibre.
echo.
"%CDBG%" -e "%SCRIPT%" -- %*
goto end

:nointerp
echo No encuentro ningun interprete valido.
echo.
echo Necesitas UNA de estas dos cosas:
echo   1) Instalar lxml en tu Python:   python -m pip install lxml
echo   2) Tener calibre-debug accesible: anade la carpeta de Calibre al PATH
echo      (suele ser "%PROGRAMFILES%\Calibre2")
goto end

:ayuda
echo Indica que analizar. Ejemplos:
echo.
echo   dedupe.cmd --doctor
echo   dedupe.cmd --root "D:\Bibliotecas" --list-libraries
echo   dedupe.cmd --root "D:\Bibliotecas"
echo   dedupe.cmd --apply "duplicados_XXXXXXXX_XXXXXX.plan.json"
echo.
:end
echo.
pause
