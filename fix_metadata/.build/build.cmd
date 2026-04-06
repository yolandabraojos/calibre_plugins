@echo off
REM Build script for Fix Metadata plugin

setlocal enabledelayedexpansion

set PLUGIN_NAME=fix_metadata
set PLUGIN_VERSION=1.0.0
set BUILD_DIR=%~dp0..
set OUTPUT_DIR=%BUILD_DIR%\..\..\.build

if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"

echo Building %PLUGIN_NAME% v%PLUGIN_VERSION%...

cd /d "%BUILD_DIR%"

powershell -Command "Compress-Archive -Path __init__.py, action.py, extractor.py, jobs.py, fix_title.py, fix_author.py, plugin-import-name-%PLUGIN_NAME%.txt, images -DestinationPath '%OUTPUT_DIR%\%PLUGIN_NAME%-v%PLUGIN_VERSION%.zip' -Force"

if %ERRORLEVEL% EQU 0 (
    echo Build successful!
    echo Output: %OUTPUT_DIR%\%PLUGIN_NAME%-v%PLUGIN_VERSION%.zip
) else (
    echo Build failed!
    exit /b 1
)

endlocal
