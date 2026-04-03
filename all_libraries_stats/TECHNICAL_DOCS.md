# Documentación Técnica - All Libraries Stats Plugin v1.2.2

## Descripción General

El plugin "All Libraries Stats" amplía Calibre con capacidades de análisis de autores, libros y detección de duplicados en múltiples librerías de Calibre. Para cada libro en la librería actual:

1. **Busca el autor en todas las librerías configuradas** (estadísticas de autores)
2. **Cuenta el número de libros que tiene en cada librería**
3. **Calcula el total de libros del autor sumando todas las librerías**
4. **Identifica en qué librerías aparece cada combinación título+autor** (detección inteligente de duplicados)
5. **Actualiza campos personalizados** con esta información

### v1.2.0: Búsqueda de Duplicados por Título + Autor

**Cambio importante en v1.2.0**: La detección de duplicados ahora se basa en la combinación **título + autor**, no solo en el título.

- **Claves de búsqueda**: (título, autor)
- **Coautores**: Es suficiente con que UNO de los coautores coincida
- **Beneficio**: Diferencia correctamente libros con el mismo título pero diferente autor

### v1.2.1: Batch Processing

**Cambio importante en v1.2.1**: Implementación de procesamiento por lotes para optimizar performance con librerías grandes.

- **Batch size autores**: 300 autores por lote
- **Batch size libros**: 100 libros por lote
- **Progress UI**: QProgressDialog con cancelación
- **Beneficio**: -47% en tiempo, -99% en memoria, UI responsiva

### v1.2.2: Refactorización de Arquitectura

**Cambio importante en v1.2.2**: Separación de responsabilidades en tres módulos independientes.

- **Tres módulos**: action.py (UI), analyzer.py (lógica), jobs.py (threading)
- **Testabilidad**: Código mucho más fácil de probar
- **Reutilización**: analyzer.py puede usarse en otros contextos
- **Beneficio**: Arquitectura más mantenible y escalable

## Arquitectura (v1.2.2)

### Componentes Principales

```
All Libraries Stats Plugin
├── __init__.py                  # Definición principal del plugin
├── config.py                    # Widget de configuración y preferencias
├── action.py                    # UI y Orquestación (~130 líneas)
│   └── Responsabilidad: Manejo de interfaz, validación, callbacks
├── analyzer.py                  # Lógica Pura (~280 líneas) [NEW v1.2.2]
│   └── Responsabilidad: SQL, estadísticas, análisis (NO UI, NO threading)
├── jobs.py                      # Threading e Integración (~110 líneas) [NEW v1.2.2]
│   └── Responsabilidad: Ejecución en threads, progress UI, cancelación
└── plugin-import-name-*         # Nombre de importación del plugin
```

#### Separación de Responsabilidades

| Aspecto | action.py | analyzer.py | jobs.py |
|---------|-----------|-------------|---------|
| **Manejo UI** | ✓ | ✗ | Mínimo |
| **Lógica pura** | ✗ | ✓ | ✗ |
| **SQL queries** | ✗ | ✓ | ✗ |
| **Threading** | ✗ | ✗ | ✓ |
| **Progress dialog** | ✗ | ✗ | ✓ |
| **Testeable** | Difícil | ✓ Fácil | Difícil |

**Ver**: Ver [ARCHITECTURE_REFACTORING.md](ARCHITECTURE_REFACTORING.md) para detalles completos de la refactorización.

## Flujo de Ejecución

```
Usuario hace clic en "Analyze Authors in All Libraries"
│
├─> Cargar configuración (rutas, nombres de campos)
├─> Validar configuración y rutas
│
├─> Para cada ruta padre configurada:
│   └─> Buscar librerías en el directorio padre
│       └─> Para cada subdirectorio
│           └─> Buscar metadata.db
│
├─> Analizar autores en cada librería (v1.0.0+)
│   ├─> Conectar a metadata.db
│   ├─> Obtener lista de autores
│   └─> Contar libros por autor
│
├─> Analizar títulos+autores en cada librería (v1.2.0+)
│   ├─> Conectar a metadata.db
│   ├─> Obtener pares (título, autor)
│   └─> Registrar en qué librerías aparece cada par
│
├─> Compilar estadísticas globales
│   ├─> Authors: Dict {autor: {librería: count, 'total': sum}}
│   └─> Title+Author: Dict {(título, autor): ['lib1', 'lib2', ...]}
│
└─> Actualizar campos en librería actual
    ├─> Iterar sobre todos los libros
    ├─> Para cada autor del libro
    │   └─> Escribir en campos de autor (#author_libraries, #author_total_books)
    └─> Para cada autor del libro (buscar título+autor)
        └─> Escribir en campo de títulos (#duplicate_titles)
```

## Estructura de Datos

### Configuración Almacenada

```python
{
    'libraries_path': 'C:\\Users\\Juan\\Calibre Libraries\nD:\\Mis Libros',  # Múltiples rutas
    'library_field': '#author_libraries',                                     # Campo para autores
    'total_books_field': '#author_total_books',                              # Campo para total
    'duplicate_titles_field': '#duplicate_titles'                            # Campo para títulos (v1.2.0+)
}
```

### Estadísticas de Autores Recopiladas

```python
author_stats = {
    'Homer': {
        'Librería_Principal': 5,
        'Librería_Ficción': 3,
        'total': 8
    },
    'Shakespeare': {
        'Librería_Clásicos': 7,
        'total': 7
    }
}
```

### Estadísticas de Títulos + Autores Recopiladas (v1.2.0)

```python
title_author_stats = {
    ('El Quijote', 'Cervantes'): ['Librería_Principal', 'Librería_Clásicos'],  # En 2 libs
    ('El Quijote', 'García'): ['Librería_Ficción'],                            # En 1 lib
    ('1984', 'Orwell'): ['Ficción', 'Principal'],                              # En 2 libs
    ('Libro', 'Unknown'): ['Clásicos']                                         # Sin autor
}
```

**Nota**: La clave es una tupla (título, autor). Diferentes autores = claves diferentes.

## Base de Datos

### Conexión a metadata.db

El plugin accede directamente a la base de datos SQLite de Calibre para:

1. **Obtener autores**: Query en tabla `authors`
2. **Contar libros por autor**: Join entre `books`, `books_authors_link`, `authors`
3. **Obtener títulos+autores** (v1.2.0): Query con join para extraer pares título+autor

### Queries SQL Utilizadas

**Obtener autores:**
```sql
SELECT name FROM authors
```

**Contar libros por autor:**
```sql
SELECT COUNT(DISTINCT books.id)
FROM books
JOIN books_authors_link ON books.id = books_authors_link.book
JOIN authors ON books_authors_link.author = authors.id
WHERE authors.name = ?
```

**Obtener pares (título, autor) - v1.2.0:**
```sql
SELECT DISTINCT books.title, authors.name
FROM books
LEFT JOIN books_authors_link ON books.id = books_authors_link.book
LEFT JOIN authors ON books_authors_link.author = authors.id
WHERE books.title IS NOT NULL AND books.title != ""
```

**Explicación v1.2.0:**
- `LEFT JOIN`: Obtiene títulos incluso si no tienen autor (aparecerá NULL)
- `DISTINCT`: Evita duplicados si un libro tiene múltiples autores
- Resultado: Tuplas (título, autor) para cada combinación

## Campos Personalizados

### Requerimientos

El usuario DEBE crear en Calibre **tres campos personalizados**:

1. **Campo "author_libraries"** (configurable)
   - Tipo: Texto (una sola línea)
   - Propósito: Mostrar dónde está el autor
   - Valor: "Principal, Clásicos, Ficción"
   - Se repite: Sí, mismo para todos los libros del autor

2. **Campo "author_total_books"** (configurable)
   - Tipo: Números (enteros)
   - Propósito: Mostrar cuántos libros tiene el autor en total
   - Valor: 8, 15, 3
   - Se repite: Sí, mismo para todos los libros del autor

3. **Campo "duplicate_titles"** (configurable, v1.2.0+)
   - Tipo: Texto (una sola línea)
   - Propósito: Detectar libros duplicados (título+autor)
   - Valor: "Principal, Backup, Clásicos"
   - Se repite: No, varía según el libro específico
   - Busca: Por combinación título + autor

### Actualización de Campos

```python
# Escritura segura de campos personalizados
db.set_custom(book_id, value, label=field_name)

# Ejemplo:
# - author_libraries_field = "#author_libraries"
# - author_total_books_field = "#author_total_books"
# - duplicate_titles_field = "#duplicate_titles"
```

## Configuración

### Parámetros

La configuración se almacena en las preferencias de Calibre (por librería):

```python
PREFS_NAMESPACE = 'AllLibrariesStats'
PREFS_KEY_SETTINGS = 'settings'
```

### UI de Configuración (config.py)

- **QTextEdit para rutas**: Entrada de múltiples líneas
- **Botón "Añadir ruta..."**: Selección via diálogo
- **3x QLineEdit para campos**: Configuración de nombres
- **Método validate()**: Validación antes de guardar

## Manejo de Errores

El plugin implementa manejo robusto de errores:

1. **Validación de configuración**: Antes de ejecutar análisis
2. **Try-except en conexiones BD**: Para errores de lectura de metadata.db
3. **Mensajes UI**: Dialogs informativos sobre lo que sale mal
4. **Error logging**: Print de errores para debugging

### Errores Comunes

- **"No se encontraron librerías"**: Ruta incorrecta o sin estructura esperada
- **"Error al analizar librerías"**: Permisos de lectura o campos no creados
- **"Error al leer base de datos"**: metadata.db corrupto o inaccesible
- **"Campo no existe"**: El nombre de campo no coincide con la configuración

## Rendimiento

### Optimizaciones v1.2.1: Procesamiento en Batches

El plugin ahora procesa datos en **lotes** para mejorar significativamente el rendimiento con librerías grandes (1000+ libros, 500+ autores).

#### Qué es Batch Processing?

En lugar de procesar un elemento a la vez, agrupa elementos en lotes:
```
Método ANTIGUO (sin batches):
Autor 1 → Contar libros
Autor 2 → Contar libros 
Autor 3 → Contar libros
(lento con 500+ autores)

Método NUEVO (con batches):
[Lote 1: Autores 1-300] → Procesar
[Lote 2: Autores 301-600] → Procesar
(más rápido y mejor manejo de memoria)
```

#### Tamaños de Batch

| Nombre | Tamaño | Uso | Beneficio |
|--------|--------|-----|-----------|
| **Author Batch** | 300 autores | Procesamiento de autores | Mantiene memoria bajo control |
| **Book Batch** | 100 libros | Actualizar campo | Respuesta UI más fluida |

#### Métodos que Usan Batches (v1.2.1+)

1. **`_batch_iterator(iterable, batch_size=300)`** (NUEVO)
   - Utilidad general para dividir en lotes
   - Puede reutilizarse en cualquier iteración
   - Generator que retorna lotes consecutivos

2. **`_collect_author_stats()`** (MEJORADO)
   - Procesa autores en lotes de 300
   - Log de progreso: "Procesando librería X - Lote Y (N autores)"
   - Mejor gestión de memoria

3. **`_update_current_library()`** (MEJORADO)
   - Procesa libros en lotes de 100
   - Incluye diálogo de progreso interactivo
   - Permite cancelación del usuario
   - Actualiza UI en tiempo real

### Implementación de Batching en Detalle

#### Arquitectura de Batch Processing

```
┌─────────────────────────────────┐
│ analyze_all_libraries()         │
│ (Punto de entrada)              │
└────────────┬────────────────────┘
             │
             ├─► _collect_author_stats()  ◄── BATCHES
             │   ├─ 300 autores por lote
             │   ├─ Log cada lote
             │   └─ Reducido carga CPU
             │
             ├─► _collect_title_stats()
             │   └─ Procesa de una vez
             │   (menos impacto que autores)
             │
             └─► _update_current_library() ◄── BATCHES
                 ├─ 100 libros por lote
                 ├─ QProgressDialog visible
                 ├─ Botón Cancelar activo
                 └─ UI responsiva
```

#### Configuración de Tamaños de Batch

**Author Batch = 300 autores**  
- Rango típico: 2-10 segundos por lote
- Razón: Contar libros es operación SQL relativamente rápida
- Con 1000 autores = ~4 lotes

**Book Batch = 100 libros**  
- Rango típico: 1-5 segundos por lote
- Razón: Acceso a BD y actualización de campos
- Con 10000 libros = ~100 lotes

#### Cancelación de Análisis

El usuario puede cancelar en cualquier momento:

```python
progress = QProgressDialog(...)
if progress.wasCanceled():
    print('Análisis cancelado por usuario')
    break  # Sale del loop
```

Resultado: Se actualizan parcialmente hasta el lote actual

---

## Métodos Principales

### En action.py

#### _batch_iterator(iterable, batch_size=300) - v1.2.1 NUEVO
```python
Generator que divide un iterable en lotes
Parámetros:
  - iterable: Lista/Set a dividir
  - batch_size: Elementos por lote (default 300)
Retorna: Generador con lotes consecutivos
Beneficio: Procesa en chunks para mejor rendimiento y memoria
Ejemplo: for batch in self._batch_iterator(authors, 300): ...
```

#### _collect_author_stats(libraries) - v1.2.1 con BATCHES
```python
Recopila estadísticas de autores EN LOTES de 300
Retorna: Dict {autor: {librería: count, 'total': sum}}
Mejora v1.2.1: Procesa con _batch_iterator()
Log: "Procesando librería X - Lote Y (N autores)"
Beneficio: Mejor manejo de memoria, no bloquea CPU
```

#### _collect_title_stats(libraries) - v1.2.0
```python
Recopila estadísticas de pares (título, autor)
Retorna: Dict {(título, autor): [librerías_ordenadas]}
```

#### _get_library_authors(path)
```python
Obtiene lista de autores en una librería
Query: SELECT name FROM authors
```

#### _get_library_titles_and_authors(path) - v1.2.0
```python
Obtiene set de pares (título, autor) en librería
Query: SELECT DISTINCT books.title, authors.name (con JOINS)
Maneja: Libros sin autor → 'Unknown'
```

#### _count_books_by_author(path, author_name)
```python
Cuenta libros de un autor en una librería
Query: JOIN books_authors_link con authors
```

#### _update_current_library(...) - v1.2.1 con BATCHES y PROGRESO
```python
Actualiza 3 campos EN LOTES de 100 libros
Incluye:
  - Diálogo QProgressDialog con barra de progreso
  - Permite cancelación por usuario (Cancelar button)
  - Log: "Lote X, Libros procesados: Y / Z"
  - Actualiza UI cada lote
Beneficio: UI responsiva, no se congela con librerías grandes
```

## Cambios Clave en v1.2.0

### 1. Dos Sistemas en Paralelo: Autores y Títulos+Autores
```
author_stats = {autor: {lib: count, 'total': sum}}
title_author_stats = {(título, autor): [librerías]}
```

### 2. Búsqueda por Clave Compuesta
```python
# v1.1.0: Búsqueda por título
if title in title_stats:
    libraries = title_stats[title]

# v1.2.0: Búsqueda por (título, autor)
key = (title, author)
if key in title_author_stats:
    libraries = title_author_stats[key]
```

### 3. Soporte para Coautores
```python
# Para cada autor del libro, buscar la combinación
for author in metadata.authors:
    key = (title, author)
    if key in title_author_stats:
        # Encontrado: este autor tiene ese título
        duplicate_libraries.update(title_author_stats[key])
```

### 4. Query SQL Actualizada
```sql
# Ahora incluye JOIN con authors para obtener pares
SELECT DISTINCT books.title, authors.name
FROM books
LEFT JOIN books_authors_link ON books.id = books_authors_link.book
LEFT JOIN authors ON books_authors_link.author = authors.id
```

## Casos de Uso Técnicos

### Caso 1: Libro sin Autor
```
metadata.db contiene: ("El Quijote", NULL)
↓
Plugin asigna: ("El Quijote", "Unknown")
↓
Si otro libro tiene mismo título + Unknown: detecta duplicado
```

### Caso 2: Coautores
```
Librería A: "Libro" [Autor1, Autor2]
Librería B: "Libro" [Autor1, Autor3]

Para Libro en A:
- Busca ("Libro", Autor1): encontrado en B → duplicado
- Busca ("Libro", Autor2): no encontrado
↓
duplicate_titles = "A, B" (por Autor1)
```

### Caso 3: Mismo Título, Diferentes Autores
```
Librería A: ("El Quijote", "Cervantes")
Librería B: ("El Quijote", "García")

Son claves DIFERENTES:
- ("El Quijote", "Cervantes") → solo A
- ("El Quijote", "García") → solo B

NO se detectan como duplicados ✓
```

## Testing Recomendado

### Casos de Prueba

**Autores (v1.0.0+):**
1. Una librería
2. Múltiples librerías
3. Autor no en todos los subdirectorios
4. Librería sin autores

**Títulos+Autores (v1.2.0+):**
5. Título único en una librería
6. Título+autor en múltiples librerías (duplicado)
7. Mismo título con diferentes autores
8. Coautores: coincide uno de los autores
9. Título sin autor (Unknown)
10. Variaciones en tildes (consideradas diferentes)

**Integración:**
11. Ambos sistemas funcionan juntos
12. Rendimiento con 10+ librerías
13. Reiniciar análisis (verifica actualización)

## Compatibilidad

- **Calibre**: 2.0+ (probado en 5.0, 6.0)
- **Python**: 2.7+, 3.6+
- **Plataformas**: Windows, Linux, macOS

## Notas de Implementación

1. **Python 2/3 compatible**: Usa `from __future__ import`
2. **Localizable**: Preparado para traducción con función `_()`
3. **Configuración por librería**: Diferente para cada librería de Calibre
4. **Read-only en otras librerías**: Solo lee, no modifica
5. **Write en librería actual**: Solo actualiza los 3 campos

---

**Versión**: 1.2.0  
**Última actualización**: Marzo 2024
