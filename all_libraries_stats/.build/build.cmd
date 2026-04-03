@echo off
REM Build script for Extract Generator plugin
REM This script creates a ZIP file ready for installation in Calibre

setlocal enabledelayedexpansion

set PLUGIN_NAME=all_libraries_stats
set PLUGIN_VERSION=1.0.5
set BUILD_DIR=%~dp0..
set OUTPUT_DIR=%BUILD_DIR%\..\..\build

if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"

REM Create the ZIP file
echo Building %PLUGIN_NAME% v%PLUGIN_VERSION%...

REM Change to plugin directory
cd /d "%BUILD_DIR%"

REM Create ZIP file with all necessary files
powershell -Command "Compress-Archive -Path __init__.py, action.py, analyzer.py, config.py, jobs.py, validate_plugin.py, plugin-import-name-%PLUGIN_NAME%.txt, README.md, CHANGELOG.md, images -DestinationPath '%OUTPUT_DIR%\%PLUGIN_NAME%-v%PLUGIN_VERSION%.zip' -Force"

if %ERRORLEVEL% EQU 0 (
    echo Build successful! 
    echo Output: %OUTPUT_DIR%\%PLUGIN_NAME%-v%PLUGIN_VERSION%.zip
) else (
    echo Build failed!
    exit /b 1
)

endlocal
