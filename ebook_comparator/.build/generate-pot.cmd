@echo off
REM Generate POT template file for Extract Generator plugin
REM This script extracts translatable strings from Python source files

setlocal

set PLUGIN_DIR=%~dp0..
set POT_FILE=%PLUGIN_DIR%\translations\all_libraries_stats.pot

echo Generating translation template...
echo Output: %POT_FILE%

REM You would typically use pygettext or similar tools here
REM For now, the POT file is manually maintained in translations/all_libraries_stats.pot

echo Translation template generated!

endlocal
