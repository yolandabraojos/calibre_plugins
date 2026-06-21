@echo off
REM Genera y verifica los ZIP maestros de todos los plugins.
REM Uso:  build.cmd            (todos)
REM       build.cmd book_classifier ebook_comparator   (solo esos)
setlocal
cd /d "%~dp0"
where py >nul 2>nul && (py -3 build_plugins.py %*) || (python build_plugins.py %*)
set RC=%ERRORLEVEL%
echo.
if %RC%==0 (echo ZIPs generados y verificados: INTEGRO) else (echo ATENCION: revisa los avisos de arriba)
pause
exit /b %RC%
