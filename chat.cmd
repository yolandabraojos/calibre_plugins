@echo off
REM ---------------------------------------------------------------------------
REM Clasificar por el CHAT WEB en vez de por la API (creditos de la web).
REM
REM   chat.cmd exportar --in biblioteca.csv --lote 40
REM       genera chat_out\lote_NNN.csv (los libros) y lote_NNN.txt (el prompt).
REM       Adjunta el .csv en el chat, pega el .txt y guarda la respuesta como
REM       chat_out\respuesta_NNN.csv
REM
REM   chat.cmd importar --in chat_out --revision chat_out\revision.csv
REM       valida lo que devolvio el modelo y deja un CSV para que lo revises.
REM
REM   chat.cmd importar --in chat_out --aplicar
REM       lo escribe en Calibre (CIERRA CALIBRE ANTES; hace respaldo).
REM
REM Exporta el catalogo CSV de Calibre INCLUYENDO la columna id.
REM ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"
set "SCRIPT=%~dp0scripts\chat_lotes.py"
if "%~1"=="" goto ayuda

echo %* | find /i "--aplicar" >nul
if errorlevel 1 goto sinCalibre

set "CDBG="
where calibre-debug >nul 2>nul
if not errorlevel 1 set "CDBG=calibre-debug"
if not defined CDBG if exist "%PROGRAMFILES%\Calibre2\calibre-debug.exe" set "CDBG=%PROGRAMFILES%\Calibre2\calibre-debug.exe"
if not defined CDBG if exist "%PROGRAMFILES(X86)%\Calibre2\calibre-debug.exe" set "CDBG=%PROGRAMFILES(X86)%\Calibre2\calibre-debug.exe"
if not defined CDBG goto nocalibre
"%CDBG%" -e "%SCRIPT%" -- %*
goto end

:sinCalibre
python "%SCRIPT%" %*
goto end

:nocalibre
echo No encuentro calibre-debug (hace falta solo para --aplicar).
echo Anade la carpeta de Calibre al PATH (suele ser "%PROGRAMFILES%\Calibre2").
goto end

:ayuda
echo Indica que hacer. Ejemplos:
echo.
echo   chat.cmd exportar --in biblioteca.csv --lote 40
echo   chat.cmd importar --in chat_out --revision chat_out\revision.csv
echo   chat.cmd importar --in chat_out --aplicar
echo.
:end
echo.
pause
