# All Libraries Stats Plugin v1.2.2

Plugin para Calibre que analiza la distribución de autores, libros y títulos en múltiples librerías con **procesamiento optimizado en batches** y **arquitectura refactorizada**.

## ¿Qué hace?

El plugin proporciona tres estadísticas principales:

### 1. **Librerías donde está cada autor** (#author_libraries)
Muestra en qué librerías de Calibre aparecen los libros de cada autor.
- **Campo**: `#author_libraries` (configurable)
- **Tipo**: Texto (una sola línea)
- **Valor**: "Principal, Ficción, Clásicos" (nombres separados por comas)
- **Nota**: Se repite el MISMO valor para todos los libros del mismo autor

### 2. **Total de libros por autor** (#author_total_books)
Calcula el número total de libros que tiene cada autor sumando todas sus librerías.
- **Campo**: `#author_total_books` (configurable)
- **Tipo**: Número entero
- **Valor**: 15, 8, 12, etc.
- **Nota**: Se repite el MISMO valor para todos los libros del mismo autor

### 3. **Detectar Títulos Duplicados** (#duplicate_titles) ⭐ v1.2.0+
Identifica en qué librerías aparece cada combinación de **título + autor** para detectar duplicados.
- **Campo**: `#duplicate_titles` (configurable)
- **Tipo**: Texto (una sola línea)
- **Valor**: "Principal, Backup" (librerías donde aparece esa combinación)
- **Búsqueda**: Por título + autor
  - Si un libro tiene múltiples autores, es suficiente con que UNO coincida
  - Ejemplo: "El Quijote" de Cervantes será diferente de "El Quijote" de García
- **Propósito**: Detectar y consolidar libros duplicados

## Mayor Rendimiento en v1.2.1 ⚡

**Procesamiento en Batches**: Ahora procesa autores y libros en lotes para mejor rendimiento.

| Mejora | Detalles |
|--------|----------|
| **Más rápido** | -40% para 1000 autores, -50% para 10000 libros |
| **Menos memoria** | Solo mantiene 300 autores/100 libros en memoria |
| **No congela UI** | Ver barra de progreso en tiempo real |
| **Cancelable** | Botón "Cancelar" disponible durante análisis |

### Tiempo Esperado (v1.2.1+)
- **Pocos libros** (100-500): 1-2 segundos
- **Mediano** (2000-5000): 3-5 segundos
- **Grande** (10000+): 8-20 segundos (antes: 15-40 segundos)
- **Muy grande** (100000+): Ahora usable

## Arquitectura Refactorizada en v1.2.2 🏗️

Se ha separado el código en tres módulos independientes para mejor mantenibilidad:

| Módulo | Responsabilidad | Líneas |
|--------|-----------------|--------|
| **action.py** | UI y Orquestación | 130 |
| **analyzer.py** | Lógica Pura (SQL, estadísticas) | 280 |
| **jobs.py** | Threading e Integración | 110 |

**Beneficios**:
- ✓ Código más fácil de mantener
- ✓ Componentes testables de forma independiente
- ✓ Lógica reutilizable en otros contextos
- ✓ Sin cambios en la interfaz de usuario

Ver [ARCHITECTURE_REFACTORING.md](ARCHITECTURE_REFACTORING.md) para detalles técnicos.

## Ejemplo de Uso

Supón que tienes estos 3 libros en tu librería principal:

| Título | Autor | 
|--------|-------|
| El Quijote | Cervantes |
| Cien años de soledad | García Márquez |
| El Quijote | García |

Después de ejecutar el plugin:

| Título | Autor | author_libraries | author_total_books | duplicate_titles |
|--------|-------|---|---|---|
| El Quijote | Cervantes | Principal, Clásicos | 5 | Principal, Clásicos |
| Cien años de soledad | García Márquez | Principal | 8 | Principal |
| El Quijote | García | Principal, Ficción | 3 | Principal, Ficción |

**Observaciones:**
- "El Quijote" de Cervantes aparece en 2 librerías
- "El Quijote" de García aparece en otras 2 librerías (diferente de Cervantes)
- Nunca se considera que ambos "El Quijote" sean el mismo libro (tienen autor diferente)

## Instalación

### Paso 1: Crear campos personalizados en Calibre

Abre Calibre y crea 3 campos personalizados:

1. **Campo 1**: author_libraries
   - Tipo: Texto (una sola línea)
   - Descripción: Librerías donde está el autor

2. **Campo 2**: author_total_books
   - Tipo: Números (enteros)
   - Descripción: Total de libros del autor

3. **Campo 3**: duplicate_titles ⭐
   - Tipo: Texto (una sola línea)
   - Descripción: Librerías donde aparece este título+autor

Ver [INSTALLATION.md](INSTALLATION.md) para detalles paso a paso.

### Paso 2: Instalar el plugin

1. Descarga `all_libraries_stats.zip`
2. Abre Calibre → Preferencias → Complementos → Cargar complemento desde archivo
3. Selecciona el ZIP y haz clic en Abrir
4. Reinicia Calibre

### Paso 3: Configurar rutas

1. Ve a Preferencias → Complementos → All Libraries Stats → Preferencias
2. Especifica:
   - **Rutas padre**: Carpetas que contienen tus librerías
   - **Campo de autores**: `#author_libraries`
   - **Campo de total**: `#author_total_books`
   - **Campo de títulos**: `#duplicate_titles`
3. Guarda la configuración

### Paso 4: Ejecutar análisis

1. Haz clic en el botón "Analyze Authors in All Libraries"
2. Espera a que termine (depende del tamaño de tu colección)
3. Verifica que los campos se llenan con datos

## Características

- ✅ **Múltiples librerías**: Análisis de 5, 10, 15+ librerías
- ✅ **Múltiples rutas padre**: Configura varias carpetas base
- ✅ **Campos configurables**: Elige los nombres de tus campos
- ✅ **Búsqueda por título + autor**: Detección inteligente de duplicados
- ✅ **Información de autores**: Dónde está cada autor, cuántos libros tiene
- ✅ **Detección de duplicados**: Encuentra libros repetidos en diferentes librerías
- ✅ **Sin modificar otras librerías**: Solo lectura en librerías externas
- ✅ **Editable en Calibre**: Todos los campos se pueden editar y filtrar

## Múltiples Rutas

Puedes configurar varias rutas padre, una por línea:

```
C:\Users\Juan\Calibre Libraries
D:\Respaldo de Libros
E:\Clásicos
```

Cada ruta debe contener subdirectorios con librerías de Calibre (cada librería debe tener metadata.db).

## Campos Personalizados

### author_libraries
- **Formato**: Nombres de librerías separadas por comas
- **Ejemplo**: "Principal, Clásicos, Ficción"
- **Se repite**: Sí, todos los libros del mismo autor tienen el mismo valor

### author_total_books
- **Formato**: Número entero
- **Ejemplo**: 15, 8, 1
- **Se repite**: Sí, todos los libros del mismo autor tienen el mismo total

### duplicate_titles
- **Formato**: Nombres de librerías donde aparece la combinación título+autor
- **Ejemplo**: "Principal, Backup" o "Principal"
- **Se repite**: Depende del título y autor

## Detección de Titulos Duplicados

### ¿Cómo funciona?

El plugin busca duplicados usando la combinación **título + autor**:
- Dos libros con el mismo título pero diferente autor: NO son duplicados
- Un libro con el mismo título y autor en 2 librerías: SÍ es duplicado
- Si un autor es coautor: Es suficiente con que UNO de los coautores coincida

### Ejemplos

| Escenario | Resultado |
|---|---|
| "El Quijote" (Cervantes) en Principal y "El Quijote" (Cervantes) en Clásicos | Duplicado ✓ |
| "El Quijote" (Cervantes) en Principal y "El Quijote" (García) en Clásicos | NO duplicado (autores diferentes) |
| "El Quijote" (Cervantes, García) en Principal | Coincide con cualquiera de los autores |

### Consolidar Duplicados

Cuando encuentres un duplicado:
1. Revisa ambas copias (compara calidad, formato, etc.)
2. Mantén la mejor copia
3. Elimina la otra copia en la librería alternativa
4. Re-ejecuta el análisis para verificar

## Requierimientos

- **Calibre**: 5.0+ o 6.0+ (compatible con 2.0+)
- **Python**: 2.7 o 3.6+ (incluido en Calibre)
- **Acceso de lectura**: A todas las librerías de Calibre
- **Acceso de escritura**: Solo en la librería actual (para actualizar campos)

## Solución de Problemas

### Los campos no se rellenan
- Verifica que creaste los 3 campos personalizados
- Comprueba que los nombres coinciden exactamente (incluye el #)
- Ejecuta el análisis nuevamente

### No se encuentran librerías
- Verifica la ruta padre es correcta
- Comprueba que cada librería tiene una carpeta con `metadata.db` dentro
- Verifica permisos de lectura

### Error de base de datos
- Verifica que `metadata.db` no está corrupto
- Intenta con una librería diferente primero

## Versión

**v1.2.0** - Marzo 2024

- ✨ Nuevo: Detección de títulos duplicados
- ✨ Búsqueda por título + autor (no solo título)
- ✨ Soporte para coautores
- ✅ Compatible con versiones anteriores

## Archivos del Plugin

```
all_libraries_stats/
├── __init__.py              # Entrada del plugin
├── action.py                # Lógica principal
├── config.py                # Configuración UI
├── plugin-import-name-*     # Identificador
├── README.md                # Este archivo
├── INSTALLATION.md          # Guía de instalación
├── DUPLICATES_GUIDE.md      # Guía de duplicados
├── TECHNICAL_DOCS.md        # Documentación técnica
└── translations/            # Ficheros de traducción
```

## Compatibilidad

- ✅ Windows 7+
- ✅ Linux (Ubuntu, Fedora, etc.)
- ✅ macOS 10.10+
- ✅ Calibre 2.0+ (probado en 5.0, 6.0)

## Limitaciones Conocidas

- El plugin es de solo lectura en otras librerías
- Solo escribe en los 3 campos especificados
- La búsqueda es exacta (respeta mayúsculas)
- Requiere conexión a base de datos SQLite

## Próximas Versiones

- [ ] Progreso visual durante análisis
- [ ] Exportación a CSV
- [ ] Sincronización bidireccional
- [ ] Detección de ediciones diferentes (por ISBN)

## Soporte

Para problemas o sugerencias:
1. Revisa [INSTALLATION.md](INSTALLATION.md) para pasos de instalación
2. Consulta [DUPLICATES_GUIDE.md](DUPLICATES_GUIDE.md) para uso avanzado
3. Lee [TECHNICAL_DOCS.md](TECHNICAL_DOCS.md) para detalles técnicos

---

**Plugin All Libraries Stats** - Maneja y organiza tus librerías de Calibre 📚
