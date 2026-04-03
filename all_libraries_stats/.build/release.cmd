@echo off
REM Release script for Extract Generator plugin
REM This script prepares the plugin for release

setlocal

echo Extract Generator Plugin - Release Script
echo ========================================

REM Version information
set VERSION=1.0.0
set DATE=%date%

echo Version: %VERSION%
echo Date: %DATE%

REM Check if all files are present
echo.
echo Checking files...
set PLUGIN_DIR=%~dp0..

if not exist "%PLUGIN_DIR%\__init__.py" (
    echo ERROR: __init__.py not found!
    exit /b 1
)

if not exist "%PLUGIN_DIR%\action.py" (
    echo ERROR: action.py not found!
    exit /b 1
)

if not exist "%PLUGIN_DIR%\config.py" (
    echo ERROR: config.py not found!
    exit /b 1
)

if not exist "%PLUGIN_DIR%\extractor.py" (
    echo ERROR: extractor.py not found!
    exit /b 1
)

if not exist "%PLUGIN_DIR%\README.md" (
    echo ERROR: README.md not found!
    exit /b 1
)

echo All files present!

REM Create release directory
set RELEASE_DIR=%PLUGIN_DIR%\..\..\..\..\release\all_libraries_stats-%VERSION%
if not exist "%RELEASE_DIR%" mkdir "%RELEASE_DIR%"

REM Copy files to release directory
echo.
echo Copying files to release directory...
xcopy "%PLUGIN_DIR%\*" "%RELEASE_DIR%" /E /I /Y

echo.
echo Release prepared at: %RELEASE_DIR%
echo.
echo Next steps:
echo 1. Create ZIP file: all_libraries_stats-%VERSION%.zip
echo 2. Test in Calibre
echo 3. Upload to plugin repository
echo.

endlocal
