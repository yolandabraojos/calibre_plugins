# Book Classifier — Plugin para Calibre

Clasifica automáticamente los libros de tu biblioteca asignándoles categorías/etiquetas basándose en sus metadatos. Las reglas de clasificación se definen en un archivo JSON que tú controlas: si el texto del libro contiene ciertas palabras clave, el plugin le asigna una categoría determinada.

La clasificación se ejecuta como un **job en segundo plano**: Calibre sigue siendo usable mientras se procesan miles de libros, con barra de progreso y botón de cancelación.

---

## Campos que lee para clasificar

El plugin extrae y concatena el texto de los siguientes campos de cada libro antes de aplicar las reglas:

| Campo | Nombre en Calibre | Notas |
|---|---|---|
| **Título** | `title` | Siempre se incluye |
| **Comentarios / Sinopsis** | `comments` | Se eliminan las etiquetas HTML antes de analizar el texto |
| **Etiquetas existentes** | `tags` | Cada etiqueta se añade como texto separado |
| **Serie** | `series` | Nombre de la serie, sin el número |
| **Campos personalizados adicionales** | Configurable en ajustes | Cualquier `#campo` de texto definido por el usuario |

> **Cómo funciona la búsqueda:** todo el texto anterior se une en una cadena única. Las palabras clave del JSON se buscan en esa cadena. Por defecto la búsqueda ignora mayúsculas, minúsculas y acentos (`regencia` encuentra `Regencia`, `REGENCIA` y `Regència`).

---

## Campo que actualiza con la clasificación

El plugin escribe **únicamente en un campo**, que tú eliges en la configuración:

### Opción A — Etiquetas estándar (`tags`)

Es la opción por defecto. Las categorías encontradas se añaden como nuevas etiquetas al libro, junto a las que ya tuviera. Si activas **«Reemplazar existentes»**, se borran primero las etiquetas anteriores.

```
Antes:  tags = ["epub", "favorito"]
Después: tags = ["epub", "favorito", "Romance Regencia", "Romance Histórico"]
```

### Opción B — Campo personalizado de tipo lista (`#genero`, `#clasificacion`, …)

Si el campo admite múltiples valores, el comportamiento es idéntico al de las etiquetas: se añaden los nuevos valores sin borrar los existentes (salvo que actives «Reemplazar»).

```
Antes:  #genero = ["Pendiente de leer"]
Después: #genero = ["Pendiente de leer", "Fantasía Épica"]
```

### Opción C — Campo personalizado de texto simple (`#genero_texto`, …)

Las categorías se unen con coma y se escriben en el campo. Si ya había contenido y no se activa «Reemplazar», se fusionan los valores únicos en orden alfabético.

```
Antes:  #genero_texto = "Thriller"
Después: #genero_texto = "Romance Regencia, Thriller"
```

> **El plugin no toca ningún otro campo.** Título, autor, portada, fecha, editorial, idioma, calificación, ruta del archivo… permanecen intactos.

---

## Modos de escritura

| Modo | Comportamiento |
|---|---|
| **Añadir** *(defecto)* | Las categorías nuevas se suman a las existentes. No se borra nada. |
| **Reemplazar** | Se borra el contenido anterior del campo destino antes de escribir. |
| **Simulación (dry run)** | No se escribe nada. Al terminar muestra qué cambios se habrían aplicado. |

---

## Formato del JSON de reglas

```json
{
  "categories": [
    {
      "name": "Romance Regencia",
      "require_all": false,
      "keywords": ["regencia", "regency", "ton", "romance"],
      "exclude_keywords": ["vampiro", "magia"],
      "priority": 10
    }
  ],
  "options": {
    "case_sensitive": false,
    "whole_word": true,
    "allow_multiple": true,
    "min_keywords_match": 1
  }
}
```

### Propiedades de cada categoría

| Propiedad | Tipo | Descripción |
|---|---|---|
| `name` | string | Texto exacto que se escribirá en el campo destino |
| `keywords` | lista | Palabras a buscar en el texto del libro |
| `require_all` | bool | `false` = basta con encontrar una · `true` = deben aparecer todas |
| `exclude_keywords` | lista | Si aparece cualquiera de estas, el libro **no** se clasifica en esta categoría |
| `priority` | número | Si `allow_multiple` es `false`, gana la categoría con número más alto |

### Opciones globales

| Opción | Defecto | Descripción |
|---|---|---|
| `case_sensitive` | `false` | `false` = ignora mayúsculas y acentos |
| `whole_word` | `true` | `true` = solo palabras completas (`ron` no activa `romance`) |
| `allow_multiple` | `true` | `true` = un libro puede recibir varias categorías |
| `min_keywords_match` | `1` | Mínimo de keywords que deben coincidir cuando `require_all` es `false` |

---

## Instalación

1. Descarga `BookClassifier.zip`.
2. En Calibre: **Preferencias → Plugins → Cargar plugin desde fichero**.
3. Selecciona el ZIP y reinicia Calibre.
4. El plugin aparece en la barra de herramientas con el icono del libro verde.

---

## Uso

| Acción | Cómo acceder |
|---|---|
| Clasificar libros seleccionados | Clic en el icono · menú contextual |
| Clasificar toda la biblioteca | Menú del plugin → *Clasificar TODOS los libros* |
| Editar reglas JSON | Menú del plugin → *Ver / Editar reglas…* |
| Importar / exportar reglas | Botones dentro del diálogo de reglas |
| Ver progreso o cancelar | Panel **Trabajos** en la parte inferior de Calibre |

---

## Ejemplo completo

**Regla definida:**
```json
{
  "name": "Romance Regencia",
  "require_all": false,
  "keywords": ["regencia", "regency", "ton", "temporada social", "duque", "baile"],
  "exclude_keywords": ["vampiro", "magia"],
  "priority": 10
}
```

**Libro de ejemplo:**

| Campo | Valor |
|---|---|
| Título | *La duquesa rebelde* |
| Comentarios | *Una joven entra en el ton londinense durante la temporada social...* |
| Tags | `epub`, `pendiente` |

**Texto analizado internamente:**
```
La duquesa rebelde Una joven entra en el ton londinense durante la
temporada social... epub pendiente
```

**Palabras encontradas:** `duquesa`, `ton`, `temporada social` → ✅ coincide (≥ 1 keyword, ninguna exclusión)

**Resultado** (campo destino: `tags`, modo añadir):
```
tags = ["epub", "pendiente", "Romance Regencia"]
```

---

## Archivos del plugin

| Archivo | Función |
|---|---|
| `__init__.py` | Registro del plugin en Calibre |
| `action.py` | Menú, diálogos y lanzamiento del job |
| `jobs.py` | Worker en background: lectura, clasificación y escritura en lote |
| `classifier.py` | Motor de clasificación puro (sin dependencias de GUI) |
| `config.py` | Interfaz de configuración con editor JSON |
| `images/icon.png` | Icono 128 × 128 px |
