@echo off
REM ---------------------------------------------------------------------------
REM Une los fragmentos "_split_NNN" que dejo una conversion de Calibre.
REM
REM Son los libros que el informe de duplicados marca como
REM "esta partido en muchos fragmentos por una conversion".
REM Reconvertirlos NO los arregla: el paso Split de Calibre solo puede partir
REM mas, nunca junta. Hay que fusionar los ficheros, que es lo que hace esto
REM con la misma API que el boton "Combinar" del editor de Calibre.
REM
REM PASO 1 - INFORME (no toca nada, Calibre puede estar abierto):
REM     merge.cmd --root "D:\Bibliotecas"
REM
REM PASO 2 - FUSION (cierra Calibre antes):
REM     merge.cmd --root "D:\Bibliotecas" --apply
REM
REM Antes de sustituir nada se guarda una copia del EPUB original en
REM dedupe_out\fragmentos_unidos_<fecha>\ y se comprueba que el TEXTO del libro
REM no ha cambiado. Un libro cuyo texto cambie NO se instala.
REM
REM La fusion NO cruza un capitulo: un fragmento que arranca con un titulo
REM (h1-h6) abre fichero nuevo, aunque quepa de sobra en el limite de tamano.
REM Dentro de un mismo capitulo, ademas, respeta un tope por fichero (260 KB,
REM el 'flow_size' de Calibre): si el capitulo es muy largo sale en varios
REM ficheros, no en uno solo enorme.
REM
REM Otras opciones utiles:
REM     --ids 1,2,3           probar con unos pocos libros
REM     --dry-run             con --apply: fusiona y verifica, pero no instala
REM     --min-splits 10       bajar el umbral (por defecto 20 fragmentos)
REM     --max-merged-kb 500   permitir ficheros fusionados mas grandes
REM     -l "D:\Lib A"         una biblioteca concreta
REM   (ojo: no termines las rutas en \ dentro de las comillas)
REM ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"
set "SCRIPT=%~dp0ebook_comparator\merge_splits.py"
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
echo [merge] Tu Python no tiene lxml: uso el interprete de Calibre.
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
echo Indica que bibliotecas. Ejemplos:
echo.
echo   merge.cmd --root "D:\Bibliotecas"                 (informe)
echo   merge.cmd --root "D:\Bibliotecas" --apply         (fusiona, Calibre cerrado)
echo   merge.cmd -l "D:\Lib" --ids 1041,2031 --apply     (prueba con dos libros)
echo.
:end
echo.
pause
