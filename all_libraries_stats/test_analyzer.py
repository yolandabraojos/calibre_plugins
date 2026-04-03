#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Test script para debugging del plugin All Libraries Stats.
Útil para investigar problemas sin ejecutar el plugin completo en Calibre.

Uso:
    python test_analyzer.py <ruta_padre_de_librerías1> [ruta_padre_de_librerías2] ...

Ejemplo:
    python test_analyzer.py "C:\_Calibre Library"
    python test_analyzer.py "C:\_Calibre Library" "D:\Mis Librerías"
"""

from __future__ import unicode_literals, division, absolute_import, print_function

import sys
import os
import sqlite3
from collections import defaultdict
import time

# Colores para terminal
class Color:
    RESET = '\033[0m'
    BOLD = '\033[1m'
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'

def print_header(text):
    """Imprime un encabezado."""
    print("\n" + Color.BOLD + Color.CYAN + "=" * 70 + Color.RESET)
    print(Color.BOLD + Color.CYAN + text + Color.RESET)
    print(Color.BOLD + Color.CYAN + "=" * 70 + Color.RESET + "\n")

def print_success(text):
    """Imprime un mensaje de éxito."""
    print(Color.GREEN + "  ✓ " + text + Color.RESET)

def print_error(text):
    """Imprime un mensaje de error."""
    print(Color.RED + "  ✗ " + text + Color.RESET)

def print_warning(text):
    """Imprime un mensaje de advertencia."""
    print(Color.YELLOW + "  ⚠ " + text + Color.RESET)

def print_info(text):
    """Imprime un mensaje de información."""
    print(Color.BLUE + "  ℹ " + text + Color.RESET)

def find_libraries(libraries_path):
    """Encuentra todas las librerías en una ruta padre."""
    libraries = []
    
    try:
        for item in os.listdir(libraries_path):
            item_path = os.path.join(libraries_path, item)
            if os.path.isdir(item_path):
                metadata_db = os.path.join(item_path, 'metadata.db')
                if os.path.isfile(metadata_db):
                    libraries.append((item, item_path))
    except Exception as e:
        print_error("No se pudo leer directorio: {}".format(str(e)))
        return []
    
    return sorted(libraries)

def validate_library(lib_name, lib_path):
    """Valida que una librería sea accesible y tenga datos válidos."""
    metadata_db = os.path.join(lib_path, 'metadata.db')
    
    print("\n  [VALIDANDO] {}".format(lib_name))
    
    # Verificar archivo
    if not os.path.isfile(metadata_db):
        print_error("metadata.db no encontrado en: {}".format(lib_path))
        return False
    
    try:
        # Conectar a la BD
        conn = sqlite3.connect(metadata_db)
        cursor = conn.cursor()
        print_success("Conexión a metadata.db exitosa")
        
        # Validar integridad
        cursor.execute('PRAGMA integrity_check')
        result = cursor.fetchone()
        if result and result[0] == 'ok':
            print_success("Integridad de base de datos: OK")
        else:
            print_warning("Posible corrupción en base de datos: {}".format(result))
            return False
        
        # Contar tablas
        cursor.execute("SELECT count(*) FROM sqlite_master WHERE type='table'")
        table_count = cursor.fetchone()[0]
        print_success("Tablas en base de datos: {}".format(table_count))
        
        # Contar autores
        cursor.execute('SELECT COUNT(*) FROM authors')
        author_count = cursor.fetchone()[0]
        print_success("Autores: {}".format(author_count))
        
        # Contar libros
        cursor.execute('SELECT COUNT(*) FROM books')
        book_count = cursor.fetchone()[0]
        print_success("Libros: {}".format(book_count))
        
        # Contar relaciones autor-libro
        cursor.execute('SELECT COUNT(*) FROM books_authors_link')
        link_count = cursor.fetchone()[0]
        print_success("Relaciones autor-libro: {}".format(link_count))
        
        conn.close()
        return True
        
    except Exception as e:
        print_error("Error al validar: {}".format(str(e)))
        return False

def get_library_stats(lib_name, lib_path):
    """Obtiene estadísticas de una librería."""
    metadata_db = os.path.join(lib_path, 'metadata.db')
    
    try:
        conn = sqlite3.connect(metadata_db)
        cursor = conn.cursor()
        
        # Autores único
        cursor.execute('SELECT COUNT(DISTINCT name) FROM authors')
        unique_authors = cursor.fetchone()[0]
        
        # Autores con más libros
        cursor.execute('''
            SELECT a.name, COUNT(DISTINCT bal.book) as book_count
            FROM authors a
            LEFT JOIN books_authors_link bal ON a.id = bal.author
            GROUP BY a.id
            ORDER BY book_count DESC
            LIMIT 5
        ''')
        top_authors = cursor.fetchall()
        
        # Libros por idioma
        cursor.execute('''
            SELECT language, COUNT(*) as count
            FROM books_languages_link
            JOIN languages ON books_languages_link.lang_code = languages.id
            GROUP BY language
            ORDER BY count DESC
        ''')
        languages = cursor.fetchall()
        
        # Títulos duplicados
        cursor.execute('''
            SELECT COUNT(*) FROM (
                SELECT title
                FROM books
                WHERE title IS NOT NULL
                GROUP BY title
                HAVING COUNT(*) > 1
            )
        ''')
        duplicate_titles = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            'unique_authors': unique_authors,
            'top_authors': top_authors,
            'languages': languages,
            'duplicate_titles': duplicate_titles
        }
        
    except Exception as e:
        print_error("Error al obtener estadísticas: {}".format(str(e)))
        return None

def test_analyze(lib_paths):
    """Ejecuta el análisis completo similar al plugin."""
    print_header("ANÁLISIS SIMULADO DEL PLUGIN")
    
    start_time = time.time()
    all_libraries = []
    
    # Fase 1: Encontrar librerías
    print(Color.BOLD + "Fase 1: Búsqueda de librerías" + Color.RESET)
    for lib_path in lib_paths:
        print_info("Buscando en: {}".format(lib_path))
        if not os.path.isdir(lib_path):
            print_error("Ruta no existe: {}".format(lib_path))
            continue
        
        libraries = find_libraries(lib_path)
        if libraries:
            for lib_name, lib_full_path in libraries:
                print_success("Librería encontrada: {}".format(lib_name))
                all_libraries.append((lib_name, lib_full_path))
        else:
            print_warning("No se encontraron librerías en: {}".format(lib_path))
    
    if not all_libraries:
        print_error("No se encontraron librerías en ninguna ruta")
        return False
    
    # Fase 2: Validar librerías
    print("\n" + Color.BOLD + "Fase 2: Validación de librerías" + Color.RESET)
    valid_libraries = []
    for lib_name, lib_path in all_libraries:
        if validate_library(lib_name, lib_path):
            valid_libraries.append((lib_name, lib_path))
    
    # Fase 3: Recopilar estadísticas
    print("\n" + Color.BOLD + "Fase 3: Estadísticas de librerías" + Color.RESET)
    author_stats = defaultdict(lambda: defaultdict(int))
    total_authors = set()
    
    for lib_name, lib_path in valid_libraries:
        print_info("Analizando: {}".format(lib_name))
        
        try:
            conn = sqlite3.connect(os.path.join(lib_path, 'metadata.db'))
            cursor = conn.cursor()
            
            # Obtener autores
            cursor.execute('SELECT name FROM authors')
            authors = [row[0] for row in cursor.fetchall()]
            
            # Contar libros por autor
            for author in authors:
                cursor.execute('''
                    SELECT COUNT(DISTINCT books.id)
                    FROM books
                    JOIN books_authors_link ON books.id = books_authors_link.book
                    JOIN authors ON books_authors_link.author = authors.id
                    WHERE authors.name = ?
                ''', (author,))
                count = cursor.fetchone()[0]
                author_stats[author][lib_name] = count
                total_authors.add(author)
            
            conn.close()
            print_success("{}: {} autores, {} libros".format(
                lib_name, len(authors), 
                sum(author_stats[a][lib_name] for a in authors)
            ))
        except Exception as e:
            print_error("Error al analizar {}: {}".format(lib_name, str(e)))
    
    # Calcular totales
    for author in author_stats:
        author_stats[author]['total'] = sum(
            author_stats[author][lib] 
            for lib in author_stats[author] 
            if lib != 'total'
        )
    
    # Fase 4: Resumen
    print_header("RESUMEN DEL ANÁLISIS")
    print("Librerías procesadas: {}".format(len(valid_libraries)))
    print("Autores únicos: {}".format(len(total_authors)))
    
    # Autores con más libros
    print("\n" + Color.BOLD + "Top 10 autores:" + Color.RESET)
    sorted_authors = sorted(
        author_stats.items(), 
        key=lambda x: x[1].get('total', 0), 
        reverse=True
    )[:10]
    
    for i, (author, libs) in enumerate(sorted_authors, 1):
        total = libs.get('total', 0)
        lib_list = [l for l in libs if l != 'total']
        print("  {}. {} - {} libros en {} librería(s)".format(
            i, author, total, len(lib_list)
        ))
    
    # Detalles por librería
    print("\n" + Color.BOLD + "Detalle por librería:" + Color.RESET)
    for lib_name, lib_path in valid_libraries:
        stats = get_library_stats(lib_name, lib_path)
        if stats:
            print("\n  [{}]".format(lib_name))
            print("    Autores únicos: {}".format(stats['unique_authors']))
            print("    Títulos duplicados: {}".format(stats['duplicate_titles']))
            
            if stats['languages']:
                print("    Idiomas:")
                for lang, count in stats['languages'][:3]:
                    print("      - {}: {} libros".format(lang, count))
            
            if stats['top_authors']:
                print("    Top 3 autores:")
                for author, count in stats['top_authors'][:3]:
                    print("      - {}: {} libros".format(author, count))
    
    elapsed = time.time() - start_time
    print("\n" + Color.BOLD + "Tiempo total: {:.1f} segundos".format(elapsed) + Color.RESET)
    
    return True

def main():
    """Función principal."""
    print_header("TEST ANALYZER - All Libraries Stats Plugin")
    
    if len(sys.argv) < 2:
        print(Color.RED + "ERROR: Especifica las rutas de tus librerías" + Color.RESET)
        print("\nUso:")
        print("  python test_analyzer.py <ruta_padre_1> [ruta_padre_2] ...")
        print("\nEjemplos:")
        print('  python test_analyzer.py "C:\\ Calibre Library"')
        print('  python test_analyzer.py "C:\\ Calibre Library" "D:\\Mis Librerías"')
        return 1
    
    lib_paths = sys.argv[1:]
    
    # Verificar que todos los argumentos sean rutas válidas
    invalid_paths = [p for p in lib_paths if not os.path.isdir(p)]
    if invalid_paths:
        print_error("Las siguientes rutas no existen:")
        for path in invalid_paths:
            print("  - {}".format(path))
        return 1
    
    if test_analyze(lib_paths):
        print("\n" + Color.GREEN + "✓ Test completado exitosamente" + Color.RESET + "\n")
        return 0
    else:
        print("\n" + Color.RED + "✗ Test falló" + Color.RESET + "\n")
        return 1

if __name__ == '__main__':
    sys.exit(main())
