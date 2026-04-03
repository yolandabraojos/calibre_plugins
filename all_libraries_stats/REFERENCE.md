# Reference - Guía de Referencia Rápida

Referencia rápida de comandos, ajustes y accesos directos.

---

## 🎯 Accesos Directos

### Menús de Calibre

| Acción | Atajo |
|--------|-------|
| Preferences | Ctrl+P |
| Books | Ctrl+L |
| Search | Ctrl+F |
| Edit Metadata | Ctrl+M (left side) |

### Plugin

| Acción | Ruta |
|--------|------|
| Ejecutar Análisis | Tools → All Libraries Stats → Analyze Authors in All Libraries |
| Configurar | Preferences → Plugins → All Libraries Stats → Customize plugin |
| Ver Campos | Preferences → Custom columns |

---

## 🔍 Búsquedas en Calibre

### Buscar por Campo

```
Sintaxis: #field_name:=value
```

**Ejemplos:**

```
#author_libraries:=Principal              → Autores en "Principal"
#author_total_books:>20                   → Autores con 20+ libros
#author_total_books:>=10                  → Autores con 10 o más
#duplicate_titles:/.+,.+/                 → Títulos en 2+ librerías
#duplicate_titles:=                       → Títulos vacíos (sin duplicados)
```

### Búsqueda Avanzada

```
#author_libraries:=Principal AND #author_total_books:>5
```
→ Autores en "Principal" con más de 5 libros

---

## 📊 Campos Personalizados

### Especificaciones

| Campo | Tipo | Propósito | Valor Ejemplo |
|-------|------|-----------|---------------|
| `#author_libraries` | Texto (línea) | Dónde está el autor | "Principal, Clásicos" |
| `#author_total_books` | Números | Cuántos libros tiene | 7 |
| `#duplicate_titles` | Texto (línea) | Dónde está el título+autor | "Principal, Ficción" |

### Crear Campos en Calibre

```
Preferences → Add your own columns

Campo 1:
  Lookup name: #author_libraries
  Description: Librerías de Autor
  Type: Text single line
  
Campo 2:
  Lookup name: #author_total_books
  Description: Total Libros Autor
  Type: Numbers
  
Campo 3:
  Lookup name: #duplicate_titles
  Description: Títulos Duplicados
  Type: Text single line
```

---

## ⚙️ Configuración del Plugin

### Archivo de Configuración

Ubicación por SO:
- **Windows**: `%APPDATA%\calibre\plugins\All Libraries Stats\prefs.json`
- **Linux**: `~/.config/calibre/plugins/All Libraries Stats/prefs.json`
- **macOS**: `~/Library/Preferences/calibre/plugins/All Libraries Stats/prefs.json`

### Parámetros

```json
{
  "libraries_path": "C:\\Users\\...\\Calibre Libraries\nD:\\Mis Libros",
  "library_field": "#author_libraries",
  "total_books_field": "#author_total_books",
  "duplicate_titles_field": "#duplicate_titles"
}
```

**Múltiples rutas**: Separar con salto de línea (\n)

---

## 🗄️ Estructura de Base de Datos

### Tabla: authors

```sql
SELECT * FROM authors LIMIT 1;

Campos:
  id          INTEGER
  name        TEXT
  sort        TEXT (ej: "Smith, John")
  link        TEXT
  rating      REAL
```

### Query para Obtener Autores

```sql
SELECT DISTINCT authors.name 
FROM authors
WHERE authors.name IS NOT NULL
ORDER BY authors.name
```

### Query para Contar Libros por Autor

```sql
SELECT COUNT(DISTINCT books.id) 
FROM books
JOIN books_authors_link ON books.id = books_authors_link.book
JOIN authors ON books_authors_link.author = authors.id
WHERE authors.name = 'Shakespeare'
```

### Query para Obtener (Título, Autor) - v1.2.0

```sql
SELECT DISTINCT books.title, authors.name
FROM books
LEFT JOIN books_authors_link ON books.id = books_authors_link.book
LEFT JOIN authors ON books_authors_link.author = authors.id
WHERE books.title IS NOT NULL AND books.title != ""
ORDER BY books.title, authors.name
```

---

## 💾 Archivos del Plugin

### Estructura

```
all_libraries_stats/
├── __init__.py                     ← Definición principal
├── action.py                       ← Lógica principal (~500 lineas)
├── config.py                       ← Interface de configuración
├── plugin-import-name-*.txt        ← Metadatos
├── validate_plugin.py              ← Script de validación
│
├── README.md                       ← Overview
├── START_HERE.md                   ← Entrada principal
├── QUICK_START.md                  ← Instalación rápida
├── INSTALLATION.md                 ← Guía detallada
├── DUPLICATES_GUIDE.md             ← Casos de duplicados
├── TECHNICAL_DOCS.md               ← Documentación técnica
├── MIGRATION.md                    ← Actualizar desde v1.1.0
├── CHANGELOG.md                    ← Historial de cambios
├── INDEX.md                        ← Índice de documentos
├── REFERENCE.md                    ← Este archivo
│
├── images/                         ← Imágenes/screenshots
└── translations/                   ← Archivos de traducción
```

---

## 🐍 Métodos Principales en action.py

### Clase Principal

```python
class AllLibrariesStatsAction(InterfaceActionBase):
    '''Plugin para analizar autores en todas las librerías'''
    
    def genesis(self):
        '''Inicialización'''
        
    def show_dialog(self):
        '''Ejecutar análisis'''
        
    def _analyze_all_libraries(self):
        '''Función principal de análisis'''
```

### Métodos Clave

```python
def _collect_author_stats(self, libraries):
    '''Recopila estadísticas de autores de todas las librerías
    Returns: Dict{autor: {librería: count, 'total': sum}}
    '''

def _collect_title_stats(self, libraries):
    '''Recopila estadísticas de (título, autor) - v1.2.0
    Returns: Dict{(título, autor): [librerías_ordenadas]}
    '''

def _get_library_authors(self, library_path):
    '''Obtiene lista de autores en una librería
    Returns: Set[author_names]
    '''

def _get_library_titles_and_authors(self, library_path):
    '''Obtiene pares (título, autor) en una librería - v1.2.0
    Returns: Set[(título, autor), ...]
    '''

def _count_books_by_author(self, library_path, author_name):
    '''Cuenta libros de un autor en una librería
    Returns: integer
    '''

def _update_current_library(self, author_stats, library_field, 
                           total_books_field, title_stats, 
                           duplicate_titles_field):
    '''Actualiza los 3 campos en la librería actual'''
```

---

## 🐛 Errores Comunes y Soluciones

| Error | Causa | Solución |
|-------|-------|----------|
| "No se encontraron librerías" | Ruta incorrecta | Ver QUICK_START.md Troubleshooting |
| "Campos no existen" | No creados en Calibre | Crear campos (QUICK_START.md paso 1) |
| "Error al leer BD" | metadata.db inaccesible | Cerrar Calibre, reabrir |
| "Plugin no aparece" | Instalación falló | Reinstalar (INSTALLATION.md paso 3) |
| "Datos no se actualizan" | Campos no creados | Crear + Reinicia Calibre |

---

## 🎨 Personalización

### Cambiar Nombres de Campos

1. **Crear campos con otro nombre** en Calibre
2. **Copiar nombre exacto** (ej: `#my_author_libs`)
3. **Preferences → Plugins → Customize → Paste el nombre**
4. **OK → Analyze**

### Cambiar Rutas de Análisis

1. **Preferences → Plugins → Customize plugin**
2. **Actualizar "Parent Library Paths"**
3. **OK → Analyze**

### Usar Solo Una Librería

El plugin funciona incluso con una sola librería:
- Plugin busca en datos que le configures
- Puedes poner una sola ruta
- Sigue funciona igual

---

## 📈 Rendimiento

### Optimizaciones

| Acción | Tiempo Estimado |
|--------|-----------------|
| 1 librería | 1-2 segundos |
| 3 librerías | 3-5 segundos |
| 5 librerías | 5-10 segundos |
| 10 librerías | 10-30 segundos |
| 20 librerías | 30-60 segundos |

**Factores que afectan**:
- Número de libros (más libros = más tiempo)
- Autores únicos (más autores = más tiempo)
- Velocidad del disco (DVD vs SSD)
- CPU disponible

### Consejos de Optimización

1. Ejecuta cuando no uses Calibre
2. Verifica que metadata.db no esté en red lenta
3. Cierra otros programas que usan metadata.db

---

## 🔐 Seguridad

### Lo que el Plugin Hace

✓ Lee archivos metadata.db  
✓ Escribe 3 campos personalizados  
✓ Lee configuración de Calibre  

### Lo que NO Hace

✗ No elimina libros  
✗ No modifica otros campos  
✗ No sube datos a internet  
✗ No requiere internet  
✗ No accede a archivos personales  

### Permisos Requeridos

- Lectura: Directorios de librerías
- Escritura: Campos personalizados en librería actual

---

## 🌍 Localización / Idiomas

### Cadenas Traducibles

El plugin incluye strings listos para traducción:

```python
_('Translation string')
```

### Idiomas Soportados Actualmente

- Español (es): Completo ✓
- Inglés (en): Fallback ✓

### Contribuir Traducción

Archivos en: `translations/`

Estructura:
```
translations/
├── es/
│   └── All Libraries Stats_es.po
├── fr/
│   └── All Libraries Stats_fr.po
└── ...
```

---

## 🧪 Testing

### Casos de Prueba Mínimos

```
Test 1: Un autor en una librería
  ✓ author_libraries se completa
  ✓ author_total_books se completa

Test 2: Multiple autores en múltiples librerías
  ✓ author_libraries muestra todas
  ✓ author_total_books suma correctamente

Test 3: Duplicados título+autor (v1.2.0)
  ✓ duplicate_titles detecta correctamente
  ✓ Diferencia entre diferentes autores

Test 4: Coautores (v1.2.0)
  ✓ Busca por uno de los autores

Test 5: Libro sin autor (v1.2.0)
  ✓ Maneja como "Unknown"
```

---

## 📚 Documentos Por Tema

### Instalación
- QUICK_START.md (5 min)
- INSTALLATION.md (15 min)

### Uso Básico
- START_HERE.md
- README.md

### Duplicados
- DUPLICATES_GUIDE.md

### Técnico
- TECHNICAL_DOCS.md
- REFERENCE.md (este)

### Actualización
- MIGRATION.md
- CHANGELOG.md

### Navegación
- INDEX.md

---

## ⌨️ Comandos Útiles

### Calibre Equivalentes de Línea de Comandos

```bash
# Ejecutar Calibre
calibre

# Con debug info
calibre --debug-device-detection

# Especificar librería
calibre --with-library "C:\path\to\library"
```

### SQLite (acceso directo a BD)

```sql
sqlite3 "C:\path\to\metadata.db"

-- Ver tablas
.tables

-- Exportar autores
.mode csv
.output authors.csv
SELECT * FROM authors;
.quit
```

---

## 🎓 Aprender Más

| Tema | Documento |
|------|-----------|
| Primeros pasos | [START_HERE.md](START_HERE.md) |
| Instalar | [QUICK_START.md](QUICK_START.md) |
| Detalle completo | [INSTALLATION.md](INSTALLATION.md) |
| Duplicados | [DUPLICATES_GUIDE.md](DUPLICATES_GUIDE.md) |
| Técnica | [TECHNICAL_DOCS.md](TECHNICAL_DOCS.md) |
| Actualizar | [MIGRATION.md](MIGRATION.md) |
| Cambios | [CHANGELOG.md](CHANGELOG.md) |
| Índice | [INDEX.md](INDEX.md) |
| Referencia | [REFERENCE.md](REFERENCE.md) (este) |

---

## 🆘 Soporte Rápido

**Problema**: "No aparecen datos"
**Solución 1**: Verifica campos existen → Ver QUICK_START.md
**Solución 2**: Reinicia Calibre → Intenta de nuevo
**Solución 3**: Lee INSTALLATION.md paso 4

**Problema**: "Duplicados no detectados correctamente"
**Solución**: Lee DUPLICATES_GUIDE.md para casos especiales

**Problema**: "Quiero actualizar desde v1.1.0"
**Solución**: Lee MIGRATION.md

**Problema**: "Quiero entender la técnica"
**Solución**: Lee TECHNICAL_DOCS.md

---

## 📋 Checklist de Instalación

```
☐ Calibre 2.0+ instalado
☐ Campo #author_libraries creado
☐ Campo #author_total_books creado
☐ Campo #duplicate_titles creado (v1.2.0)
☐ Plugin instalado
☐ Rutas configuradas
☐ "Analyze" ejecutado
☐ Datos aparecen en campos
```

---

## 📞 Contacto / Reportes

**Reportar bug**:
1. Versión del plugin (START_HERE.md)
2. Versión Calibre (Preferences → About)
3. Mensaje de error exacto
4. Pasos para reproducir

**Sugerir feature**:
Describe qué quieres que haga

---

**Última actualización**: Marzo 2024  
**Versión**: 1.2.0  
**Para preguntas**: Ver [INDEX.md](INDEX.md)
