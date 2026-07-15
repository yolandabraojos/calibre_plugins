@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ==================================================
echo    Book Classifier  -  Rescate con IA (GLM/z.ai)
echo ==================================================
echo.

REM --- Comprobar Python ---
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] No se encuentra Python. Instalalo desde https://python.org
  echo         o ejecuta en PowerShell:  winget install Python.Python.3.12
  echo.
  pause
  exit /b 1
)

REM --- Comprobar el script y el CSV ---
if not exist "llm_rescue.py" (
  echo [ERROR] No encuentro llm_rescue.py en esta carpeta.
  pause
  exit /b 1
)
if not exist "clasificacion_resultado.csv" (
  echo [ERROR] No encuentro clasificacion_resultado.csv en esta carpeta.
  pause
  exit /b 1
)

REM --- Pedir la clave ---
echo Necesitas una clave gratuita de z.ai. Menu perfil, API Keys.
set "ZAI_API_KEY="
set /p "ZAI_API_KEY=Pega tu clave y pulsa Enter: "
if "%ZAI_API_KEY%"=="" (
  echo [ERROR] No has introducido ninguna clave.
  pause
  exit /b 1
)

REM --- Elegir modo ---
echo.
echo   1 = Prueba rapida de 30 libros  [prueba.csv]
echo   2 = Biblioteca completa         [rescatados.csv]
echo.
set "MODO="
set /p "MODO=Elige 1 o 2: "

if "%MODO%"=="2" (
  set "OUT=rescatados.csv"
  set "LIMIT="
) else (
  set "OUT=prueba.csv"
  set "LIMIT=--limit 30"
)

echo.
echo Ejecutando con GLM-4.5-Flash... puede tardar; se puede cerrar y reanudar.
echo.
python llm_rescue.py --in clasificacion_resultado.csv --out "%OUT%" --provider glm --temas-file book_classifier\mood_rules.json --batch 10 %LIMIT%

echo.
if errorlevel 1 (
  echo [AVISO] El proceso termino con errores. Revisa los mensajes de arriba.
) else (
  echo Listo. Resultado guardado en: %OUT%
)
echo.
pause
endlocal
