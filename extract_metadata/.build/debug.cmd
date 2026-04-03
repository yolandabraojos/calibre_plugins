@echo off
REM Debug script for Extract Generator plugin
REM This script launches Calibre in debug mode with the plugin

setlocal

set PLUGIN_DIR=%~dp0..

REM Run calibre-debug to test the plugin
echo Starting Calibre debug mode for Extract Generator plugin...
echo Plugin location: %PLUGIN_DIR%

cd /d "%PLUGIN_DIR%"
calibre-debug -e __init__.py

endlocal
