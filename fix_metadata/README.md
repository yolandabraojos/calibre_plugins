# Fix Metadata — Plugin para Calibre

Limpia y normaliza metadatos de tu biblioteca en varios frentes: título,
serie, idioma, subtítulo y universo narrativo (juntos en una sola acción,
"Fix all"), autor, identificadores, calidad de la sinopsis y etiquetas. Cada
acción se puede lanzar sobre los libros seleccionados o sobre toda la
librería. Las que necesitan criterio humano (Fix all, Compare with file
metadata) muestran, **antes de guardar nada**, un diálogo de revisión (el
mismo "comparar y aceptar" que usa Calibre) para que apruebes o descartes
cada cambio libro a libro; las mecánicas y deterministas (Fix author, Fix
identifiers, Fix tags) se escriben directamente.

## Qué hace (menú del plugin)

| Acción | Qué corrige |
|---|---|
| **Extraer metadatos del fichero** | Lee el EPUB/AZW3 y rellena `#generator`, `#book_producer`, `#title_opf` y `#subjects` con lo que trae el propio fichero. |
| **Fix all (series, idioma, subtítulo, universo)** | Detecta "Título — Serie #N" / "Título (Serie, #N)" / "Título: Subtítulo" y el idioma embebido en el título, y resuelve `#world` a partir de la serie (propia, recién detectada, o la del `#title_opf`). Todo (título, serie, idioma, `#subtitle`, `#world`) se revisa junto en un único diálogo; `#world` nunca sobrescribe un valor existente. |
| **Fix author** | Invierte "Apellido, Nombre" → "Nombre Apellido" y corrige iniciales sin puntos o sin espacios (p. ej. "JK Rowling" → "J. K. Rowling"). |
| **Fix identifiers** | Normaliza identificadores: fusiona `asin`/`mobi-asin` en `amazon`, unifica códigos de Amazon regionales (`amazon_ca`, `amazon_es`, `amazon_uk`), elimina UUIDs sueltos y corrige entradas mal formadas. |
| **Check comments** | No corrige la sinopsis (no se puede reescribir sola), pero **marca** las que están vacías, son demasiado cortas/largas, tienen texto repetido, son basura/boilerplate (incluye secciones pegadas como "Sobre el autor" o "Reseñas") o están duplicadas entre varios libros, para revisarlas a mano. |
| **Compare with file metadata (OPF)** | Lee título, autor, serie (+índice) e idioma embebidos en el fichero del libro (el OPF interno del EPUB) y los compara con lo que hay en Calibre. Usa el método de comparación de *Smart Metadata* (similitud difusa de título/autor + conflicto de idioma) para decidir qué difiere, y abre el CompareMany para validar. Al aceptar, el valor del fichero **sobrescribe** el de Calibre. |
| **Fix tags** | Traduce etiquetas sucias y bilingües (`Themes.*`, `English.Romance.*`, `_Genre.*`…) al vocabulario controlado en español `Grupo · Valor`, usando `tags_map.json`. Las etiquetas ya canónicas o desconocidas se dejan tal cual (no se pierde información). |

Cada submenú tiene sus dos variantes: **Selected books** (solo lo que tengas
marcado) y **Entire library** (toda la librería).

## Campos personalizados que usa

Créalos en **Preferencias → Añadir tus propias columnas** antes de usar la
acción correspondiente (el plugin avisa si falta alguno):

| Columna | Tipo | Usado por |
|---|---|---|
| `#generator` | Texto | Extraer metadatos |
| `#book_producer` | Texto | Extraer metadatos |
| `#title_opf` | Texto | Extraer metadatos |
| `#subjects` | Texto | Extraer metadatos / Fix tags |
| `#subtitle` | Texto (no "Long text/comments") | Fix all |
| `#world` | Texto | Fix all |

## Flujo de trabajo

1. Selecciona libros (o ninguno, para "Entire library") y elige la acción en
   el menú del plugin.
2. El plugin analiza los libros en segundo plano.
3. Se abre un diálogo de revisión mostrando el valor actual y el propuesto
   para cada libro afectado; puedes editar, revertir, aceptar todo o
   rechazar libro a libro.
4. Solo se guardan los cambios que aceptes.

## Instalación

1. En Calibre: **Preferencias → Plugins → Cargar plugin desde fichero**.
2. Selecciona `FixMetadata.zip` y reinicia Calibre.

## Ficheros

| Fichero | Función |
|---|---|
| `__init__.py` | Registro del plugin |
| `action.py` | Menú, orquestación y diálogos de cada acción |
| `jobs.py` | Extracción de metadatos en segundo plano |
| `extractor.py` | Lectura de metadatos desde EPUB/AZW3 |
| `fix_title.py` / `fix_title_series.py` | Detección de serie/índice/idioma en el título |
| `fix_author.py` | Normalización de nombres de autor |
| `fix_identifiers.py` | Normalización de identificadores |
| `fix_world.py` + `world_map.json` | Universo narrativo a partir de la serie |
| `fix_comments.py` | Detección de sinopsis de baja calidad |
| `fix_tags.py` + `tags_map.json` | Canonicalización de etiquetas |
| `compare_review.py` | Diálogo de revisión (envoltorio del CompareMany nativo de Calibre) |
| `opf_compare.py` | Lee los metadatos embebidos en el fichero y detecta diferencias con Calibre |
| `matching.py` | Método de comparación (similitud título/autor, conflicto de idioma) reutilizado de *Smart Metadata* |
