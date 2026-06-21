@echo off
REM Verifica los ZIP maestros existentes (no reconstruye).
setlocal
cd /d "%~dp0"
where py >nul 2>nul && (py -3 build_plugins.py --verify) || (python build_plugins.py --verify)
set RC=%ERRORLEVEL%
pause
exit /b %RC%
