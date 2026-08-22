@echo off
REM ---------------------------------------------------------------------------
REM Cambia el TIPO de una columna personalizada de Calibre CONSERVANDO valores.
REM
REM Caso tipico: #subtitle se creo como "Long text, like comments" y se quiere
REM como "Text, column shown in the Tag browser".  Calibre no deja cambiar el
REM tipo, asi que el script exporta los valores, borra la columna, la recrea
REM con el tipo nuevo, reescribe los valores (pasando el HTML a texto plano) y
REM lo verifica releyendo la biblioteca.
REM
REM CIERRA CALIBRE ANTES: esto ESCRIBE en la biblioteca.
REM
REM   convertir_columna.cmd --list                        ver las columnas
REM   convertir_columna.cmd --column subtitle --dry-run   ensayo, no toca nada
REM   convertir_columna.cmd --column subtitle             hacerlo
REM   convertir_columna.cmd --column subtitle --to comments        vuelta atras
REM   convertir_columna.cmd --restore "columnas_out\subtitle_XXX.json"
REM
REM Por defecto usa la ultima biblioteca que abrio Calibre.  Para otra, vale el
REM NOMBRE que Calibre muestra en "Cambiar biblioteca", no hace falta la ruta:
REM   convertir_columna.cmd --list-libraries              cuales conozco
REM   convertir_columna.cmd --column subtitle -l "Mi Biblioteca"
REM   convertir_columna.cmd --column subtitle -l "D:\Bibliotecas\Mi Lib"
REM   convertir_columna.cmd --column subtitle --all-libraries
REM   --root "D:\Bibliotecas"   busca ahi las que Calibre no recuerde
REM   (ojo: no termines las rutas en \ dentro de las comillas)
REM
REM Deja una copia de los valores en columnas_out\<columna>_<fecha>.json y un
REM respaldo metadata.db.bak-<fecha> dentro de la biblioteca.
REM
REM Necesita el interprete de Calibre (usa su API), asi que va por calibre-debug.
REM ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"
set "SCRIPT=%~dp0scripts\convert_column.py"
if "%~1"=="" goto ayuda

set "CDBG="
where calibre-debug >nul 2>nul
if not errorlevel 1 set "CDBG=calibre-debug"
if not defined CDBG if exist "%PROGRAMFILES%\Calibre2\calibre-debug.exe" set "CDBG=%PROGRAMFILES%\Calibre2\calibre-debug.exe"
if not defined CDBG if exist "%PROGRAMFILES(X86)%\Calibre2\calibre-debug.exe" set "CDBG=%PROGRAMFILES(X86)%\Calibre2\calibre-debug.exe"
if not defined CDBG if exist "%PROGRAMFILES%\Calibre\calibre-debug.exe" set "CDBG=%PROGRAMFILES%\Calibre\calibre-debug.exe"
if not defined CDBG goto nocalibre
"%CDBG%" -e "%SCRIPT%" -- %*
goto end

:nocalibre
echo No encuentro calibre-debug.
echo Anade la carpeta de Calibre al PATH (suele ser "%PROGRAMFILES%\Calibre2").
goto end

:ayuda
echo Indica que hacer. Ejemplos:
echo.
echo   convertir_columna.cmd --list-libraries
echo   convertir_columna.cmd --list
echo   convertir_columna.cmd --column subtitle --dry-run
echo   convertir_columna.cmd --column subtitle -l "Mi Biblioteca"
echo   convertir_columna.cmd --column subtitle
echo.
echo Cierra Calibre antes de convertir.
echo.
:end
echo.
pause
