@echo off
REM Build script for Book Classifier plugin
REM This script creates a ZIP file ready for installation in Calibre

setlocal enabledelayedexpansion

set PLUGIN_NAME=book_classifier
set PLUGIN_VERSION=2.0.0
set BUILD_DIR=%~dp0..
set OUTPUT_DIR=%BUILD_DIR%\..\..\.build

if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"

REM Create the ZIP file
echo Building %PLUGIN_NAME% v%PLUGIN_VERSION%...

REM Change to plugin directory
cd /d "%BUILD_DIR%"

REM Create ZIP file with all necessary files
echo Including files:
echo   - Python modules (action.py, classifier.py, config.py, jobs.py, fetcher.py, thema_mapper.py, __init__.py)
echo   - Data files (thema_codes.json, thema_mappings.json, clasificacion_libros.json)
echo   - Plugin metadata (plugin-import-name-book_classifier.txt)
echo   - Images folder
echo   - README.md

powershell -Command "Compress-Archive -Path __init__.py, action.py, classifier.py, config.py, jobs.py, fetcher.py, thema_mapper.py, thema_codes.json, thema_mappings.json, clasificacion_libros.json, plugin-import-name-%PLUGIN_NAME%.txt, images, README.md -DestinationPath '%OUTPUT_DIR%\%PLUGIN_NAME%-v%PLUGIN_VERSION%.zip' -Force"

if %ERRORLEVEL% EQU 0 (
    echo.
    echo Build successful! 
    echo Output: %OUTPUT_DIR%\%PLUGIN_NAME%-v%PLUGIN_VERSION%.zip
    echo.
    echo Next steps:
    echo 1. Copy the ZIP file to Calibre's plugin directory
    echo 2. Use Calibre's "Preferences" ^> "Plugins" to install it
    echo.
) else (
    echo Build failed!
    exit /b 1
)

endlocal
