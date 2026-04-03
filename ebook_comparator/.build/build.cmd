@echo off
REM Build script for Extract Generator plugin
REM This script creates a ZIP file ready for installation in Calibre

setlocal enabledelayedexpansion

set PLUGIN_NAME=ebook_comparator
set PLUGIN_VERSION=2.4.0
set BUILD_DIR=%~dp0..
set OUTPUT_DIR=%BUILD_DIR%\..\..\.build

if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"

REM Create the ZIP file
echo Building %PLUGIN_NAME% v%PLUGIN_VERSION%...

REM Change to plugin directory
cd /d "%BUILD_DIR%"

REM Create ZIP file with all necessary files
powershell -Command "Compress-Archive -Path __init__.py, extractor.py, comparator.py, ui.py, action.py, jobs.py, plugin.svg, plugin-import-name-%PLUGIN_NAME%.txt -DestinationPath '%OUTPUT_DIR%\%PLUGIN_NAME%-v%PLUGIN_VERSION%.zip' -Force"

if %ERRORLEVEL% EQU 0 (
    echo Build successful! 
    echo Output: %OUTPUT_DIR%\%PLUGIN_NAME%-v%PLUGIN_VERSION%.zip
) else (
    echo Build failed!
    exit /b 1
)

endlocal
