# Guía de Debugging - All Libraries Stats Plugin

## Ejecución en Modo Depuración con calibre-debug

### Paso 1: Ejecutar Calibre en Modo Depuración

Para ejecutar Calibre con el plugin en modo debug y ver todos los mensajes de log y errores:

```bash
calibre-debug -g
```

Este comando:
- Inicia Calibre con depuración gráfica habilitada
- Muestra la consola de salida donde verás todos los logs
- Permite ver excepciones completas en tiempo real
- Es la forma recomendada para investigar errores del plugin

### Paso 2: Activar el Plugin

1. Abre Calibre (ahora en modo debug)
2. Ve a **Tools → Preferences → Plugins → Interface Plugins**
3. Busca **"All Libraries Stats"**
4. Haz clic en **"Customize plugin"** para configurar las rutas de tus librerías
5. Cierra la configuración y vuelve a la librería principal

### Paso 3: Ejecutar el Análisis

1. Busca el botón **"Analyze Authors in All Libraries"** (debería estar en la barra de herramientas o en un menú)
2. Haz clic para iniciar el análisis
3. Observa la consola de debug que abriste en el Paso 1

Los logs mostrarán:
```
Procesando librería "Library 1" - Lote 1 (300 autores)
Procesando librería "Library 2" - Lote 1 (250 autores)
...
Actualizando campos de libros...
```

## Investigación de Errores

### Error: "ValueError: Incorrect number of arguments for function contains"

Este error generalmente indica un problema en una búsqueda o filtro de Calibre.

#### Posibles causas:

1. **Fórmula incorrecta en búsqueda avanzada**
   - Verifica si estás usando búsquedas avanzadas con `contains()`
   - Sintaxis correcta: `contains(field, valor)`
   - Sintaxis incorrecta: `contains(field)` o `contains()`

2. **Campo personalizado mal definido**
   - Verifica en Preferences → Add your own columns
   - Los campos deben estar correctamente creados con nombres como `#author_libraries`
   - El formato debe ser "Text" o "Numbers" según corresponda

3. **Problema en la evaluación de columnas**
   - Algunos plugins o búsquedas pueden intentar evaluar columnas incorrectamente
   - Ve a Preferences → Colors → Column color rules y revisa si hay reglas con `contains()`

#### Investigación paso a paso:

1. **Verifica los campos personalizados:**
   ```
   Preferences → Add your own columns
   Deberías ver:
   - #author_libraries     (Text)
   - #author_total_books   (Numbers)
   - #duplicate_titles     (Text)
   ```

2. **Desactiva temporalmente el plugin:**
   - Preferences → Plugins → Interface Plugins
   - Busca "All Libraries Stats"
   - Haz clic en "Disable"
   - Reinicia Calibre
   - Si el error desaparece, el problema está en el plugin

3. **Revisa las reglas de color:**
   ```
   Preferences → Colors → Column color rules
   Busca cualquier regla que use contains() y verifica que esté correcta
   ```

## Trazabilidad Completa (Logging)

Todas las funciones principales del plugin emiten logs detallados:

```
[INICIO] analyze_libraries_threaded
  ├─ Fase 1: Búsqueda de librerías en rutas padre
  │  ├─ Ruta: C:\Calibre\Library1
  │  ├─ Ruta: D:\Calibre\Library2
  │  └─ Librerías encontradas: 2
  ├─ Fase 2: Recopilación de estadísticas de autores
  │  ├─ Librería "Library1" - Lote 1 (300 autores)
  │  ├─ Librería "Library1" - Lote 2 (150 autores)
  │  └─ Librería "Library2" - Lote 1 (280 autores)
  ├─ Fase 3: Información de títulos duplicados
  │  ├─ Analizando pares título+autor
  │  └─ Títulos únicos encontrados: 5432
  ├─ Fase 4: Actualización de metadatos en librería actual
  │  ├─ Lote 1: Actualizando libros 1-100
  │  ├─ Lote 2: Actualizando libros 101-200
  │  └─ Total actualizado: 5432 libros
  └─ [RESUMEN FINAL]
     ├─ Librerías procesadas: 2
     ├─ Autores únicos: 5432
     ├─ Libros actualizados: 5432
     └─ Tiempo: 45.2 segundos
```

## Script de Debug: test_analyzer.py

Para investigar problemas sin ejecutar el plugin completo:

```bash
python test_analyzer.py
```

Este script:
- Prueba la búsqueda de librerías
- Valida la conexión a cada metadata.db
- Prueba la extracción de autores
- Genera un reporte completo de estadísticas
- Identifica librerías con problemas

Ejemplo de salida:
```
[TEST] Buscando librerías en: C:\Calibre\Library1
  ✓ Librería encontrada: Library1 (path: C:\Calibre\Library1\Library1)
  
[TEST] Validando metadata.db
  ✓ Conexión exitosa
  ✓ Tablas encontradas: 10
  ✓ Identificadores válidos
  
[TEST] Extrayendo autores
  ✓ Autores únicos: 450
  ✓ Libros totales: 2500
  
[RESUMEN]
  Librerías encontradas: 1
  Autores totales: 450
  Libros totales: 2500
```

## Análisis Manual de Librerías

Si sospechas que el problema está en cómo se leen los datos:

1. **Abre la librería en SQLite Browser:**
   - Descarga SQLite Browser: https://sqlitebrowser.org/
   - Abre: `C:\tu_ruta\metadata.db`
   - Explora las tablas: `books`, `authors`, `books_authors_link`
   - Verifica que los datos sean consistentes

2. **Ejecuta queries SQL directas:**
   ```sql
   -- Ver autores únicos
   SELECT COUNT(DISTINCT name) FROM authors;
   
   -- Ver libros por autor
   SELECT a.name, COUNT(b.id) as book_count
   FROM authors a
   LEFT JOIN books_authors_link bal ON a.id = bal.author
   LEFT JOIN books b ON bal.book = b.id
   GROUP BY a.name
   ORDER BY book_count DESC;
   
   -- Ver títulos duplicados
   SELECT title, COUNT(*) as duplicates
   FROM books
   WHERE title IS NOT NULL
   GROUP BY title HAVING COUNT(*) > 1;
   ```

## Registrar Errores

Si encuentras un error, recopila esta información:

1. **Salida completa de la consola** (copia todo desde `calibre-debug -g`)
2. **Configuración del plugin:**
   - Rutas de librerías
   - Nombres de campos personalizados
   - Número de librerías encontradas
3. **Información del sistema:**
   - Versión de Calibre: `calibre --version`
   - Versión de Python: `python --version`
   - Sistema operativo

## Comandos Útiles para Debugging

### Ver versión de Calibre
```bash
calibre --version
```

### Listar librerías disponibles
```bash
calibredb list_libraries
```

### Exportar metadatos de una librería
```bash
calibredb list -l "C:\tu_ruta" > export.txt
```

### Validar integridad de base de datos
```bash
calibre-debug -e "import sqlite3; sqlite3.connect('metadata.db').execute('PRAGMA integrity_check')"
```

## Recursos Adicionales

- **Documentación de Calibre**: https://manual.calibre-ebook.com/
- **Documentación de Plugins**: https://calibre-ebook.com/metafilter
- **Forum de Calibre**: https://www.mobileread.com/forums/
