#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Script de validación para All Libraries Stats Plugin.

Este script verifica que el plugin esté correctamente estructurado
y que todos los archivos necesarios estén presentes con el contenido correcto.

Uso:
    python validate_plugin.py

"""

from __future__ import unicode_literals, division, absolute_import, print_function

import os
import sys

def check_file_exists(path, description):
    """Verifica si un archivo existe."""
    if os.path.isfile(path):
        print("✓ Encontrado: {}".format(description))
        return True
    else:
        print("✗ FALTA: {} ({})".format(description, path))
        return False

def check_directory_exists(path, description):
    """Verifica si un directorio existe."""
    if os.path.isdir(path):
        print("✓ Encontrado: {}".format(description))
        return True
    else:
        print("✗ FALTA: {} ({})".format(description, path))
        return False

def validate_plugin_structure(plugin_dir):
    """Valida la estructura del plugin."""
    print("=" * 60)
    print("Validando estructura del plugin All Libraries Stats")
    print("=" * 60)
    print()
    
    all_good = True
    
    # Verificar directorio principal
    if not os.path.isdir(plugin_dir):
        print("✗ ERROR: El directorio del plugin no existe: {}".format(plugin_dir))
        return False
    
    print("Directorio del plugin: {}".format(plugin_dir))
    print()
    
    # Archivos requeridos
    print("Archivos requeridos:")
    all_good &= check_file_exists(
        os.path.join(plugin_dir, '__init__.py'),
        "Archivo __init__.py"
    )
    all_good &= check_file_exists(
        os.path.join(plugin_dir, 'config.py'),
        "Archivo config.py"
    )
    all_good &= check_file_exists(
        os.path.join(plugin_dir, 'action.py'),
        "Archivo action.py"
    )
    all_good &= check_file_exists(
        os.path.join(plugin_dir, 'plugin-import-name-all_libraries_stats.txt'),
        "Archivo plugin-import-name-*.txt"
    )
    print()
    
    # Archivos de documentación
    print("Archivos de documentación:")
    all_good &= check_file_exists(
        os.path.join(plugin_dir, 'README.md'),
        "README.md"
    )
    all_good &= check_file_exists(
        os.path.join(plugin_dir, 'CHANGELOG.md'),
        "CHANGELOG.md"
    )
    all_good &= check_file_exists(
        os.path.join(plugin_dir, 'QUICK_START.md'),
        "QUICK_START.md"
    )
    all_good &= check_file_exists(
        os.path.join(plugin_dir, 'EXAMPLES.md'),
        "EXAMPLES.md"
    )
    all_good &= check_file_exists(
        os.path.join(plugin_dir, 'TECHNICAL_DOCS.md'),
        "TECHNICAL_DOCS.md"
    )
    print()
    
    # Directorios opcionales
    print("Directorios opcionales:")
    check_directory_exists(
        os.path.join(plugin_dir, 'translations'),
        "Directorio translations/"
    )
    check_directory_exists(
        os.path.join(plugin_dir, 'images'),
        "Directorio images/"
    )
    print()
    
    # Validar contenido de archivos clave
    print("Validando contenido de archivos:")
    init_path = os.path.join(plugin_dir, '__init__.py')
    if os.path.isfile(init_path):
        with open(init_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            if 'ActionAllLibrariesStats' in content:
                print("✓ __init__.py contiene ActionAllLibrariesStats")
            else:
                print("✗ __init__.py NO contiene ActionAllLibrariesStats")
                all_good = False
            
            if 'all_libraries_stats.action:AllLibrariesStatsAction' in content:
                print("✓ __init__.py referencia action.AllLibrariesStatsAction")
            else:
                print("✗ __init__.py NO referencia action.AllLibrariesStatsAction")
                all_good = False
    
    config_path = os.path.join(plugin_dir, 'config.py')
    if os.path.isfile(config_path):
        with open(config_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            if 'ConfigWidget' in content:
                print("✓ config.py contiene ConfigWidget")
            else:
                print("✗ config.py NO contiene ConfigWidget")
                all_good = False
            
            if 'KEY_LIBRARIES_PATH' in content:
                print("✓ config.py contiene configuración de rutas")
            else:
                print("✗ config.py NO contiene configuración esperada")
                all_good = False
    
    action_path = os.path.join(plugin_dir, 'action.py')
    if os.path.isfile(action_path):
        with open(action_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            if 'AllLibrariesStatsAction' in content:
                print("✓ action.py contiene AllLibrariesStatsAction")
            else:
                print("✗ action.py NO contiene AllLibrariesStatsAction")
                all_good = False
            
            if '_find_libraries' in content:
                print("✓ action.py contiene método _find_libraries")
            else:
                print("✗ action.py NO contiene _find_libraries")
                all_good = False
            
            if '_collect_author_stats' in content:
                print("✓ action.py contiene método _collect_author_stats")
            else:
                print("✗ action.py NO contiene _collect_author_stats")
                all_good = False
    
    print()
    print("=" * 60)
    if all_good:
        print("✓ VALIDACIÓN EXITOSA: Plugin está correctamente estructurado")
    else:
        print("✗ VALIDACIÓN FALLIDA: El plugin tiene problemas")
    print("=" * 60)
    
    return all_good

def validate_libraries_path(libraries_path):
    """Valida una ruta de librerías."""
    print()
    print("=" * 60)
    print("Validando estructura de librerías")
    print("=" * 60)
    print()
    
    if not os.path.isdir(libraries_path):
        print("✗ ERROR: Ruta no existe: {}".format(libraries_path))
        return False
    
    print("Ruta de librerías: {}".format(libraries_path))
    print()
    
    libraries = []
    try:
        for item in os.listdir(libraries_path):
            item_path = os.path.join(libraries_path, item)
            if os.path.isdir(item_path):
                metadata_db = os.path.join(item_path, 'metadata.db')
                if os.path.isfile(metadata_db):
                    print("✓ Encontrada librería: {} (metadata.db presente)".format(item))
                    libraries.append(item)
                else:
                    print("✗ Directorio '{}' no tiene metadata.db".format(item))
    except Exception as e:
        print("✗ Error al leer directorio: {}".format(str(e)))
        return False
    
    print()
    if libraries:
        print("Total de librerías encontradas: {}".format(len(libraries)))
        print()
        return True
    else:
        print("✗ ERROR: No se encontraron librerías válidas")
        print("  Verifica que:")
        print("  1. La ruta es correcta")
        print("  2. Hay subdirectorios dentro de la ruta")
        print("  3. Cada subdirectorio contiene un archivo 'metadata.db'")
        return False

if __name__ == '__main__':
    # Validar plugin
    plugin_path = os.path.dirname(os.path.abspath(__file__))
    success = validate_plugin_structure(plugin_path)
    
    # Validar librerías (opcional, si se proporciona como argumento)
    if len(sys.argv) > 1:
        libraries_path = sys.argv[1]
        validate_libraries_path(libraries_path)
    else:
        print()
        print("Tip: Puedes validar tu estructura de librerías ejecutando:")
        print("  python validate_plugin.py <ruta_padre_librerías>")
    
    sys.exit(0 if success else 1)
