# Guía de Instalación - All Libraries Stats Plugin

## Requisitos previos

- **Calibre 2.0 o superior** (recomendado: Calibre 5.0+)
- **Acceso de lectura** a todas las librerías de Calibre en el disco
- **Permiso de escritura** en la librería actual de Calibre
- **Python 2.7 o Python 3.x** (incluido en Calibre)

## Paso 1: Preparar el plugin

### Opción A: Como archivo ZIP (Recomendado)

1. Navega al directorio `calibre_plugins_samples/all_libraries_stats/`
2. Crea un archivo ZIP con todos los archivos:
   - `__init__.py`
   - `action.py`
   - `config.py`
   - `plugin-import-name-all_libraries_stats.txt`
   - Carpetas `translations/` e `images/` (vacías está bien)
3. Nombra el archivo `all_libraries_stats.zip`

### Opción B: Como directorio (Desarrollo)

Si estás desarrollando el plugin:
1. Copia todo el directorio `all_libraries_stats/` a:
   - Windows: `C:\Users\[username]\AppData\Roaming\calibre\plugins\`
   - Linux: `~/.config/calibre/plugins/`
   - macOS: `~/Library/Preferences/calibre/plugins/`

## Paso 2: Crear campos personalizados

**IMPORTANTE**: Debes hacer esto ANTES de instalar el plugin. El plugin necesita **3 campos personalizados**.

### Campos Requeridos - Tabla de Referencia

| # | Nombre Columna | Tipo Calibre | Etiqueta Búsqueda | Descripción |
|---|---|---|---|---|
| 1 | `author_libraries` | **Texto (una sola línea)** | `#author_libraries` | Librerías donde está el autor |
| 2 | `author_total_books` | **Números** (enteros) | `#author_total_books` | Total de libros del autor |
| 3 | `duplicate_titles` | **Texto (una sola línea)** | `#duplicate_titles` | Librerías donde aparece este título+autor |

**Nota**: Puedes cambiar los nombres, pero luego configura los nuevos nombres en el plugin.

### Paso a Paso para Crear Campos

1. Abre **Calibre** (si ya está abierto, reinicia)
2. Abre la **librería** donde quieras usar el plugin
3. Ve a **Preferencias** → **Añadir tus propias columnas**

#### CAMPO 1: Librerías del Autor

1. Haz clic en **"Añadir columna personalizada"**
2. Rellena los campos:
   - **Nombre de la columna**: `author_libraries`
   - **Nombre de búsqueda**: Se genera automáticamente como `#author_libraries`
   - **Tipo de datos**: Selecciona **"Texto"** → **"Texto (una sola línea)"**
   - **Categorías**: Opcional
   - **Descripción**: `Librerías donde se encuentra el autor`
3. Haz clic en **"OK"**

#### CAMPO 2: Total de Libros del Autor

1. Haz clic en **"Añadir columna personalizada"**
2. Rellena los campos:
   - **Nombre de la columna**: `author_total_books`
   - **Nombre de búsqueda**: Se genera automáticamente como `#author_total_books`
   - **Tipo de datos**: Selecciona **"Números"** (sin decimales)
   - **Decimales**: 0
   - **Descripción**: `Total de libros del autor en todas las librerías`
3. Haz clic en **"OK"**

#### CAMPO 3: Librerías del Título ⭐ (NUEVO en v1.2.0)

1. Haz clic en **"Añadir columna personalizada"**
2. Rellena los campos:
   - **Nombre de la columna**: `duplicate_titles`
   - **Nombre de búsqueda**: Se genera automáticamente como `#duplicate_titles`
   - **Tipo de datos**: Selecciona **"Texto"** → **"Texto (una sola línea)"**
   - **Categorías**: Opcional
   - **Descripción**: `Librerías donde aparece este título+autor (detecta duplicados)`
3. Haz clic en **"OK"**

#### Finalizar

Haz clic en **"OK"** para cerrar la ventana de preferencias.

**Verifica:** Deberías ver **3 nuevas columnas** en tu tabla de libros (posiblemente al final):
- `author_libraries`
- `author_total_books`
- `duplicate_titles`

## Paso 3: Instalar el plugin

### Si usas archivo ZIP:

1. Ve a **Preferencias** → **Complementos** → **Cargar complemento desde archivo**
2. Navega y selecciona `all_libraries_stats.zip`
3. Haz clic en **"Abrir"**
4. Verás un mensaje de confirmación
5. Haz clic en **"OK"**
6. **Reinicia Calibre**

### Si instalaste como directorio:

1. **Reinicia Calibre**
2. El plugin debería aparecer automáticamente

## Paso 4: Configurar el plugin

1. Ve a **Preferencias** → **Complementos**
2. En la sección "Interfaz de usuario", busca "All Libraries Stats"
3. Hace clic en el nombre del plugin para seleccionarlo
4. Haz clic en el botón **"Preferencias"** (icono de engranaje a la derecha)

Se abrirá la ventana de configuración del plugin con 4 campos que rellenar.

### Campo 1: "Rutas padre de librerías"
- Especifica la **ruta PADRE** que contiene tus librerías
- Puedes especificar **MÚLTIPLES rutas** (una por línea)
- Estructura esperada:
  ```
  C:\Users\Juan\Calibre Libraries\
  ├── Librería_Principal\
  │   └── metadata.db         ← Librería individual
  ├── Librería_Ficción\
  │   └── metadata.db         ← Librería individual
  └── Clásicos\
      └── metadata.db         ← Librería individual
  ```
- **Ejemplos Windows**: 
  ```
  C:\Users\Juan\Calibre Libraries
  D:\Mis Libros
  E:\Clásicos
  ```
- **Ejemplos Linux**: 
  ```
  /home/juan/calibre_libraries
  /mnt/backup/books
  ```
- **Ejemplos macOS**: 
  ```
  /Users/juan/Calibre Libraries
  /Volumes/External/Books
  ```
- Usa el botón **"Añadir ruta..."** para seleccionar mediante diálogo

### Campo 2: "Campo para librerías del autor"
- **Nombre que creaste**: `author_libraries`
- **Escribir en configuración**: `#author_libraries`
- Debe coincidir EXACTAMENTE (incluye el #)
- Si creaste con otro nombre, escribe: `#nombre_que_creaste`
- Este campo mostrará: "Principal, Ficción, Clásicos"

### Campo 3: "Campo para total de libros"
- **Nombre que creaste**: `author_total_books`
- **Escribir en configuración**: `#author_total_books`
- Coincidir EXACTAMENTE con el nombre que creaste
- Si usaste otro nombre: `#nombre_que_creaste`
- Este campo mostrará un número entero (ejemplo: 15)

### Campo 4: "Campo para títulos duplicados" ⭐ NUEVO
- **Nombre que creaste**: `duplicate_titles`
- **Escribir en configuración**: `#duplicate_titles`
- Nuevo en v1.2.0 - **detecta libros por título + autor**
- Busca por combinación de título + autor (suficiente con que uno de los coautores coincida)
- Debe coincidir EXACTAMENTE
- Este campo mostrará: "Principal, Backup" (si la combinación título+autor aparece en varias librerías)

5. Haz clic en **"OK"** para guardar la configuración

**Nota**: Cada librería de Calibre puede tener configuración diferente. Si usas el plugin en varias librerías, deberás configurar esto en cada una.

## Paso 5: Ejecutar el análisis

1. Abre la **librería** donde configuraste el plugin
2. En la **barra de herramientas**, deberías ver un nuevo botón o menú
3. Busca la acción **"Analyze Authors in All Libraries"**
4. Haz clic en él
5. El plugin comenzará a analizar. Esto puede tomar tiempo si tienes muchas librerías/libros
6. Cuando termine, verás un mensaje de confirmación

**Resultado**: Los 3 campos se llenarán automáticamente:
- `author_libraries`: Librerías donde está el autor
- `author_total_books`: Total de libros del autor
- `duplicate_titles`: Librerías donde aparece la combinación título+autor

## Verificar la instalación

Después de ejecutar el análisis, verifica que todo funcionó:

1. En tu librería de Calibre, busca libros y verifica los valores:
   - **author_libraries**: Deberías ver nombres de librerías separadas por comas (ej: "Principal, Clásicos")
   - **author_total_books**: Deberías ver números enteros (ej: 8, 15)
   - **duplicate_titles**: Deberías ver nombres de librerías donde aparece esa combinación título+autor

2. **Ejemplo de valores esperados:**
   ```
   author_libraries: "Principal, Ficción, Clásicos"
   author_total_books: 8
   duplicate_titles: "Principal, Clásicos"
   ```

3. **Busca por autor** para verificar que los datos son correctos:
   - Todos los libros del mismo autor deberían tener el MISMO valor en `author_libraries` y `author_total_books`
   - El valor en `duplicate_titles` varía según dónde esté ese libro específico (título+autor)

## Solución de problemas

### "Complemento no aparece en la lista"

**Solución:**
1. Asegúrate de que el archivo ZIP está bien formado
2. Verifica que `__init__.py` está en la raíz del ZIP
3. Comprueba que hay un archivo con nombre `plugin-import-name-*`
4. Reinicia Calibre completamente

### "Por favor, configura la ruta de las librerías"

**Solución:**
1. Ve a Preferencias → Complementos → All Libraries Stats → Preferencias
2. Llena el campo "Ruta padre de librerías"
3. Verifica que la ruta existe y es correcta
4. Haz clic en "OK"

### "No se encontraron librerías"

**Solución:**
1. Comprueba que la ruta padre especificada es correcta
2. Verifica que dentro hay subdirectorios con archivos `metadata.db`
3. Estructura correcta:
   ```
   C:\Calibre Libraries\
   ├── Librería1\
   │   └── metadata.db  ← Debe existir
   └── Librería2\
       └── metadata.db  ← Debe existir
   ```

### "Los campos no se rellenan"

**Solución paso a paso:**

1. **Verifica que creaste los 3 campos personalizados**:
   - `author_libraries` (Tipo: Texto - una sola línea)
   - `author_total_books` (Tipo: Números enteros)
   - `duplicate_titles` (Tipo: Texto - una sola línea)

2. **Verifica la configuración del plugin**:
   - Abre: **Preferencias** → **Complementos** → **All Libraries Stats** → **Preferencias**
   - Comprueba que los nombres coinciden EXACTAMENTE:
     - Campo autores: `#author_libraries`
     - Campo total: `#author_total_books`
     - Campo títulos: `#duplicate_titles`
   - **Importante**: Incluye el `#` al inicio
   - **Importante**: Respeta mayúsculas/minúsculas

3. **Ejecuta el análisis nuevamente**:
   - Haz clic en **"Analyze Authors in All Libraries"**
   - Espera a que termine
   - Los campos deberían llenarse

4. **Si aún no funciona**:
   - Abre Calibre → Preferencias → Añadir propias columnas
   - Verifica el **nombre de búsqueda exacto** de cada campo
   - Comparar con la configuración del plugin

### Errores al analizar

**Solución:**
1. Asegúrate de que el usuario tiene **permisos de lectura** en todas las librerías
2. Comprueba que los archivos `metadata.db` no están corrupto (prueba a abrirlos en otra herramienta)
3. Verifica que hay espacio libre en disco
4. Intenta con una sola librería primero como prueba

## Desinstalación

Para desinstalar el plugin:

1. Ve a **Preferencias** → **Complementos**
2. Busca "All Libraries Stats"
3. Haz clic en el botón **"Desinstalar"** (o símbolo -)
4. **Reinicia Calibre**

**Nota**: Los campos personalizados NO se eliminarán automáticamente. Si quieres quitarlos también:
1. Ve a **Preferencias** → **Añadir tus propias columnas**
2. Selecciona cada columna y haz clic en **"Borrar"**:
   - `author_libraries`
   - `author_total_books`
   - `duplicate_titles`
3. Confirma cada borrado
4. Haz clic en **"OK"**

## Actualización

Para actualizar a una versión más nueva:

1. Descarga la nueva versión del plugin
2. Ve a **Preferencias** → **Complementos** → **Desinstalar**
3. Reinicia Calibre
4. Instala la nueva versión como se describe en "Paso 3"

## Soporte técnico

Si encuentras problemas:

1. **Revisa los logs**: Algunos errores se muestran en los logs de Calibre
2. **Ejecuta la validación**: `python validate_plugin.py`
3. **Consulta la documentación**: Revisa README.md, QUICK_START.md, TECHNICAL_DOCS.md
4. **Verifica la sintaxis**: El plugin requiere Python correcto

## Notas finales

- El plugin es **de solo lectura** en otras librerías
- Solo **escribe en los campos** especificados en configuración
- Puede ejecutarse **varias veces** sin problemas
- Compatible con **Calibre 2.0+** (probado en 5.0+, 6.0+)
- Funciona en **Windows, macOS y Linux**

---

## Referencia: Formatos de Datos en los Campos

Después de ejecutar el análisis, los campos se rellenan automáticamente con estos formatos:

### Campo 1: author_libraries
**Tipo**: Texto  
**Formato**: Nombres de librerías separadas por comas  
**Ejemplos**:
```
Principal, Ficción, Clásicos
Librería1, Librería2
Principal
```

**Nota**: Se repite el MISMO valor para todos los libros del mismo autor.

### Campo 2: author_total_books
**Tipo**: Número entero  
**Formato**: Suma total de libros del autor en TODAS las librerías  
**Ejemplos**:
```
15
8
1
25
```

**Nota**: Se repite el MISMO valor para todos los libros del mismo autor.

### Campo 3: duplicate_titles
**Tipo**: Texto  
**Formato**: Nombres de librerías donde aparece ESTE TÍTULO específico  
**Ejemplos**:
```
Principal, Backup
Ficción
Principal, Clásicos, Backup
```

**Nota**: Diferente para cada título (no se repite).

### Ejemplo Completo (Vista de una Librería después del Análisis)

| Título | Autor | author_libraries | author_total_books | duplicate_titles |
|--------|-------|---|---|---|
| El Quijote | Cervantes | Principal, Clásicos | 3 | Principal, Clásicos |
| Novelas Ejemplares | Cervantes | Principal, Clásicos | 3 | Principal |
| La Gitanilla | Cervantes | Principal, Clásicos | 3 | Clásicos |
| 1984 | Orwell | Principal, Ficción | 2 | Principal, Ficción |
| Rebelión en la Granja | Orwell | Principal, Ficción | 2 | Principal |

**Observaciones:**
- Los 3 libros de Cervantes tienen el MISMO valor en `author_libraries` y `author_total_books`
- El valor en `duplicate_titles` VARÍA según el título (detecta dónde está cada libro específico)
- Los 2 libros de Orwell también comparten `author_libraries` y `author_total_books`
