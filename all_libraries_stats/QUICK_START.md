# Quick Start - All Libraries Stats Plugin

Instala y ejecuta el plugin en 5 minutos.

## 1. Instalación Rápida (2 minutos)

### Paso 1: Crear 3 Campos en Calibre

1. **Abre Calibre** → menú **Preferences** (Ctrl+P)
2. **Ve a**: Preferences → Add your own columns
3. **Crea el campo 1** (copiar nombres exactos):
   - Lookup name: `#author_libraries`
   - Description: "Librerías de Autor"
   - Format for dates: Text (es single line)
   - Click "Add custom column"

4. **Crea el campo 2**:
   - Lookup name: `#author_total_books`
   - Description: "Total Libros Autor"
   - Format: Numbers (es single)
   - Click "Add custom column"

5. **Crea el campo 3** (nuevo en v1.2.0):
   - Lookup name: `#duplicate_titles`
   - Description: "Títulos Duplicados"
   - Format: Text (es single line)
   - Click "Add custom column"

6. **Reinicia Calibre**

### Paso 2: Instalar Plugin

1. **Descarga el plugin**: All Libraries Stats (archivo .ZIP o carpeta)
2. **En Calibre**: menú Preferences → Plugins → Load plugin from file
3. **Selecciona** el archivo del plugin
4. **Calibre se reinicia** automáticamente

**Listo!** El plugin está instalado.

## 2. Configuración Rápida (2 minutos)

### Paso 1: Abrir Configuración

1. **En Calibre**: Tools → Preferences (Ctrl+P)
2. **Va a**: Plugins → Interface Plugins → All Libraries Stats
3. Click en **Customize plugin**

### Paso 2: Añadir Rutas

En la caja "Parent Library Paths" escribe:

```
C:\Users\TuUsuario\Calibre Libraries
```

O si tienes múltiples ubicaciones:

```
C:\Users\TuUsuario\Calibre Libraries
D:\Mis Libros
E:\Calibre
```

### Paso 3: Confirmar Campos (opcional)

Los valores por defecto están bien:
- Field for author libraries: `#author_libraries` ✓
- Field for total books: `#author_total_books` ✓
- Field for duplicate titles: `#duplicate_titles` ✓

Si creaste con otros nombres, cámbialos aquí.

### Paso 4: Guardar

Click en **OK** → **Apply**

**Listo!**

## 3. Ejecutar Análisis (1 minuto)

### Primera Ejecución

1. **Abre la librería principal** donde quieres ver los datos
2. **Menú**: Tools → All Libraries Stats → Analyze Authors in All Libraries

   OR

   **Botón en toolbar**: Si está ahí el botón de "Analyze Authors"

3. **Espera** a ver la barra de progreso (nuevo en v1.2.1)
   - Muestra proceso en tiempo real
   - Puedes cancelar en cualquier momento
   - No se congela UI de Calibre

4. **Listo!** Los campos se llenarán automáticamente

### Tiempo Esperado (v1.2.1 con Batching)

| Librerías | Libros | Tiempo |
|-----------|--------|--------|
| 1 | 500 | 1-2 seg |
| 2 | 2000 | 3-4 seg |
| 5 | 10000 | 8-12 seg |
| 10 | 50000 | 20-30 seg |
| 20 | 100000+ | 40-60 seg |

**Nota**: v1.2.1 procesa en batches (300 autores/lote, 100 libros/lote)
para mejor rendimiento y responsividad

## 4. Verificar que Funciona

### Busca un Autor Conocido

1. **Casilla de búsqueda** (arriba de la lista de libros)
2. **Escribe**: `#author_libraries:=` (sin comillas)
3. **Debe mostrar** libros que tengan valor en ese campo

### Verifica los Datos

1. **Panel derecho**: Click en un libro
2. **Scroll down**: Busca los 3 campos nuevos:
   - `#author_libraries`: Mostrará "Principal, Clásicos, Ficción" o similar
   - `#author_total_books`: Mostrará un número (ej: 8)
   - `#duplicate_titles`: Mostrará dónde aparece ese título+autor

## Ejemplo Real

Imagina que tienes:

```
Librería "Principal": El Quijote de Cervantes
Librería "Clásicos":  El Quijote de Cervantes
Librería "Ficción":   El Quijote de García
```

Después de Analyze:

| Campo | Principal | Clásicos | Ficción |
|-------|-----------|----------|---------|
| **Libro**: El Quijote (Cervantes) |  |  |  |
| author_libraries | Principal, Clásicos | - | - |
| author_total_books | 7 | - | - |
| duplicate_titles | Principal, Clásicos | Principal, Clásicos | - |
| **Libro**: El Quijote (García) |  |  |  |
| author_libraries | - | - | Ficción |
| author_total_books | - | - | 3 |
| duplicate_titles | Ficción | - | Ficción |

**Nota**: Los campos de "author_libraries" y "author_total_books" **se repiten** para todos los libros del mismo autor (es información del autor).

## 5. ¿Hay Error o Problema?

### Opción 1: Ver logs detallados (RECOMENDADO)

Ejecuta Calibre en modo debug con:

```bash
calibre-debug -g
```

Esto:
- Abre Calibre **con consola de logs**
- Muestra todos los mensajes del plugin
- Permite ver **exactamente dónde falla**
- Es la forma recomendada para investigar

Una vez abierto:
1. Ejecuta el análisis como siempre
2. **Mira la consola** que se abrió
3. Verás logs como:

   ```
   [ALL_LIBRARIES_STATS] INFO: [INICIO] find_libraries - Buscando en: C:\Calibre Library
   [ALL_LIBRARIES_STATS] INFO:   ✓ Librería encontrada: Library1 en C:\Calibre Library\Library1
   [ALL_LIBRARIES_STATS] INFO: [ÉXITO] find_libraries - 1 librerías encontradas
   ```

### Opción 2: Test script para debugging

Si sospechas un problema en las librerías, usa:

```bash
python test_analyzer.py "C:\tu ruta de librerías"
```

Este script:
- Verifica que todas las librerías sean accesibles
- Valida la integridad de metadata.db
- Cuenta autores y libros
- **Identifica dónde está el problema**

### Opción 3: Guía completa de debugging

Si nada funciona, lee: **[DEBUGGING_GUIDE.md](DEBUGGING_GUIDE.md)**

Aquí encontrarás:
- Solución específica para cada error
- Comandos útiles
- Análisis manual de bases de datos
- Cómo reportar errores adecuadamente

El campo "duplicate_titles" **varía** según el libro (es información del título+autor específico).

## 5. Usa el Plugin

### Ver TODO los Autores

1. **Add Column** → `#author_libraries`
2. **Ahora ves** en qué librerías está cada autor

### Ver Duplicados por Autor

1. **Add Column** → `#author_total_books`
2. **Filtra** por "Smith" (apellido frecuente)
3. **Ves** cuántos libros tiene Smith en total

### Detectar Libros Duplicados

**NUEVO en v1.2.0**: Busca por título + autor

1. **Add Column** → `#duplicate_titles`
2. **Busca en esa columna**:
   - Valores con 2+ librerías = duplicados reales
   - "Principal, Clásicos" = El libro está en ambas librerías
3. **Ejemplo de acciones**:
   - Si aparece 2+ librerías: Considera consolidar
   - Si aparece 1 sola: Es único en esa librería

## Troubleshooting Rápido

### "No aparecen datos"

**Solución 1**: Verificar que la ruta sea correcta
- La ruta debe estar a nivel PADRE de las librerías
- Ejemplo: `C:\Users\User\` (no `C:\Users\User\Calibre\Principal`)

**Solución 2**: Confirmar campos personalizados
- Ir a Preferences → Custom columns
- Verificar que existan los 3 campos
- Usar los nombres exactos: `#author_libraries`, `#author_total_books`, `#duplicate_titles`

**Solución 3**: Reiniciar Calibre
- Cierra y abre Calibre de nuevo
- Ejecuta Analyze otra vez

### "Error al leer base de datos"

- Cierra Calibre
- Asegúrate que NO hay base de datos abierta en otra aplicación
- Abre Calibre de nuevo
- Intenta Analyze otra vez

### "Tarda mucho"

- Normal si tienes 10+ librerías con muchos libros
- Puede tomar 10-30 segundos
- Ejecuta una sola vez y luego consulta los datos

## Próximos Pasos

### Para Aprender Más

- Lee [README.md](README.md) para descripción completa
- Lee [DUPLICATES_GUIDE.md](DUPLICATES_GUIDE.md) para casos de duplicados
- Lee [INSTALLATION.md](INSTALLATION.md) para guía paso-a-paso

### Para Usar Avanzado

- Busca por campo: `#author_libraries:=Principal` (libros en "Principal")
- Busca por número: `#author_total_books:>20` (autores con 20+ libros)
- Busca duplicados: `#duplicate_titles:/.+,.+/` (aparece 2+ librerías)

### Para Reportar Problemas

1. **Error específico**: Nota el mensaje exacto
2. **Configuración**: Qué rutas usas, cuántas librerías
3. **Datos**: Cuántos autores/libros aproximadamente
4. **Reporta en**: GitHub issues o comentarios

## Atajos útiles

| Acción | Atajo |
|--------|-------|
| Abrir Preferences | Ctrl+P |
| Buscar en columna | Click en campo + filtro |
| Reordenar columnas | Drag & drop |
| Ver metadatos | Right-click libro → Edit metadata |
| Ejecutar Analyze | Tools → All Libraries Stats |

---

**¿Preguntas?** Ver [README.md](README.md) o [INSTALLATION.md](INSTALLATION.md)

**Versión**: 1.2.0  
**Requisitos**: Calibre 2.0+, 3 campos personalizados

