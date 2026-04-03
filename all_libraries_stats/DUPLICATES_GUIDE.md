# Guía de Títulos Duplicados - All Libraries Stats v1.2.0

## Búsqueda por Título + Autor

A partir de v1.2.0, el plugin detecta duplicados usando la combinación **título + autor**, no solo el título.

### ¿Qué significa esto?

- **Clave de búsqueda**: Título + Autor (juntos)
- **Coautores**: Es suficiente con que UNO de los coautores coincida
- **Resultado**: Libros con el mismo título pero diferente autor NO se consideran duplicados

## Ejemplos

### Ejemplo 1: DUPLICADO - Mismo título, mismo autor

```
Librería Principal:  "El Quijote" de Cervantes
Librería Clásicos:   "El Quijote" de Cervantes

→ duplicate_titles: "Principal, Clásicos"
→ ES UN DUPLICADO ✓
```

### Ejemplo 2: NO DUPLICADO - Mismo título, autor diferente

```
Librería Principal:  "El Quijote" de Cervantes
Librería Clásicos:   "El Quijote" de García

→ Principal: duplicate_titles = "Principal"
→ Clásicos: duplicate_titles = "Clásicos"
→ NO SON DUPLICADOS (autores diferentes)
```

### Ejemplo 3: DUPLICADO - Coautores (uno coincide)

```
Librería Principal:  "El Quijote" de Cervantes, García
Librería Clásicos:   "El Quijote" de Cervantes

→ duplicate_titles: "Principal, Clásicos"
→ ES UN DUPLICADO (Cervantes está en ambos)
```

### Ejemplo 4: DUPLICADO - Múltiples coautores en diferentes librerías

```
Librería Principal:  "Libro" de Autor A, Autor B
Librería Ficción:    "Libro" de Autor B, Autor C
Librería Clásicos:   "Libro" de Autor A

→ Coincide Autor A: Principal, Clásicos
→ Coincide Autor B: Principal, Ficción
→ ES UN DUPLICADO (comparten autores)
```

## Tabla Completa de Escenarios

| Título | Autores L1 | Autores L2 | ¿Duplicado? | Razón |
|--------|---|---|---|---|
| El Quijote | Cervantes | Cervantes | ✓ SÍ | Mismo título y autor |
| El Quijote | Cervantes | García | ✗ NO | Autores diferentes |
| El Quijote | Cervantes, García | Cervantes | ✓ SÍ | García coincide |
| Libro A | Autor1 | Autor1, Autor2 | ✓ SÍ | Autor1 coincide |
| Harry Potter 1 | Rowling | Rowling | ✓ SÍ | Mismo autor |
| Harry Potter 1 | Rowling (ES) | Rowling (EN) | ✓ SÍ | Mismo título+autor |

## Ventajas de la Búsqueda por Título + Autor

### 1. No Confunde Libros Diferentes

✐ **Antes (solo título)**:
```
"El Quijote" de Cervantes → duplicado
"El Quijote" de García    → duplicado
↓ Problema: Se confunden ambos
```

✓ **Ahora (título + autor)**:
```
"El Quijote" de Cervantes → duplicado identificado correctamente
"El Quijote" de García    → NO es duplicado (autor diferente)
↓ Correcto: Distingue ambos
```

### 2. Maneja Ediciones Diferentes

```
"El Quijote" Edición 2024 (Cervantes) → Principal
"El Quijote" Edición 1960 (Cervantes) → Clásicos

→ Ambas son el MISMO libro (título + autor)
→ Es un DUPLICADO legítimo
→ Puedes elegir la mejor edición
```

### 3. Soporta Coautores Naturalmente

```
"Colaboración" (Autor1, Autor2) en Principal
"Colaboración" (Autor1, Autor3) en Ficción

→ Autor1 está en ambas
→ DETECTA CORRECTAMENTE la duplicación
```

## Consolidar Duplicados por Título + Autor

### Paso 1: Identificar Duplicados

En Calibre, busca en `duplicate_titles`:
- Si el campo muestra múltiples librerías: Hay un duplicado potencial
- Si el campo muestra una librería: No hay duplicado

**Ejemplo:**
```
Libro "El Quijote"
duplicate_titles = "Principal, Clásicos"

→ Existe en 2 librerías: HAY DUPLICADO
```

### Paso 2: Verificar que es el Mismo Libro

Compara ambas versiones:
1. **Título**: Debe ser idéntico
2. **Autor(es)**: Al menos uno debe coincidir
3. **Details Adicionales**:
   - ISBN (si disponible)
   - Fecha de publicación
   - Editorial
   - Número de páginas

### Paso 3: Elegir la Mejor Copia

Para cada duplicado, decide cual mantener:
- ¿Cuál formato prefieres? (EPUB, PDF, MOBI)
- ¿Cuál tiene mejor calidad?
- ¿Cuál tiene metadatos más completos?

### Paso 4: Eliminar la Copia Inferior

**En Calibre:**
1. Abre la librería alternativa
2. Abre el editor del libro
3. Elimina (Delete) el libro
4. **NO elimines** de la librería principal

**O:**
1. Exporta el libro a una carpeta como respaldo
2. Luego elimina en Calibre
3. Reconecta la librería

### Paso 5: Re-ejecutar el Análisis

Después de eliminar duplicados:
1. Haz clic en "Analyze Authors in All Libraries"
2. El campo `duplicate_titles` should show solo una librería
3. Confirma que el duplicado fue eliminado

## Casos Especiales

### ¿Qué pasa con "Unknown" author?

Si un libro no tiene autor:
```
Librería Principal: "Libro" (sin autor)
Librería Ficción:   "Libro" (sin autor)

→ Se considera DUPLICADO
→ Ambos se agrupan como (título, "Unknown")
```

### ¿Qué pasa con títulos duplicados?

Si hay un libro con el MISMO título en la MISMA librería (afortunadamente raro):
```
Librería Principal: "El Quijote" (Cervantes) - ID 1
Librería Principal: "El Quijote" (Cervantes) - ID 2

→ duplicate_titles en ambos = "Principal"
→ Están en la MISMA librería
→ Verifica manualmente - probablemente error de importación
```

### ¿Qué pasa con variaciones de tildes?

```
"Quijote" (sin tilde)
"Quijóte" (con tilde)

→ Se consideran DIFERENTES (búsqueda exacta)
→ NO se detectará como duplicado
→ Solución: Normaliza manualmente
```

## Integración con Otros Campos

Los 3 campos trabajan juntos:

```
author_libraries = "Principal, Clásicos"
  ↓ Muestra dónde está EL AUTOR

author_total_books = 5
  ↓ Muestra cuántos libros tiene EL AUTOR en suma

duplicate_titles = "Principal, Clásicos"
  ↓ Muestra dónde está ESE LIBRO ESPECÍFICO (título+autor)
```

**Ejemplo con múltiples autores:**

| Libro | Autores | author_libraries | author_total_books | duplicate_titles |
|---|---|---|---|---|
| Colaboración | A, B | Principal, Ficción | 2 | Principal, Ficción |
| Solo A | A | Principal, Ficción | 2 | Principal |
| Solo B | B | Ficción | 1 | Ficción |

**Análisis:**
- Autor A: 2 libros en total (aparece en 2 librerías)
- Autor B: 1 libro en total (aparece en 1 librería)
- Los 2 libros de A comparten librerías, pero el "Solo A" aparece en diferentes librerías

## Exportar y Analizar Duplicados

### Exportar a CSV

En Calibre, selecciona libros y exporta datos:
1. Selecciona libros con `duplicate_titles` con múltiples librerías
2. Exporta a CSV
3. Abre en Excel/LibreOffice
4. Analiza patrones

### Filtrar en Calibre

Busca duplicados usando:
```
#duplicate_titles > 10 caracteres   (improbable que tenga 10+ caracteres si solo una librería)
```

O crea una búsqueda guardada:
```
duplicate_titles:* principal* AND duplicate_titles:* clásicos*
```

## Flujo de Consolidación Recomendado

```
1. Ejecutar análisis
          ↓
2. Filter: duplicate_titles con múltiples librerías
          ↓
3. Para cada duplicado:
   a. Verificar que es el MISMO libro (título+autor)
   b. Elegir la mejor versión
   c. Eliminar en librería alternativa
          ↓
4. Re-ejecutar análisis
          ↓
5. Verificar: Cada título+autor aparece en 1 librería
          ↓
6. Librería consolidada y limpia ✓
```

## Resumen

- ✅ Búsqueda por **título + autor** (combinación)
- ✅ Coautores: Basta con que UNO coincida
- ✅ Diferencia libros con mismo título pero autor diferente
- ✅ Detecta correctamente ediciones duplicadas
- ✅ Facilita consolidación de librerías

**¡Usa esta información para mantener tus librerías de Calibre limpias y organizadas!** 📚
