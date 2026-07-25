# Ebook Comparator — Plugin para Calibre

Compara el **contenido** de tus ebooks (no solo título/autor) para encontrar
duplicados y ediciones repetidas, y te deja borrar la copia sobrante sin salir
de Calibre. Soporta **EPUB** y **AZW3**.

## Qué resuelve

Es habitual acabar con el mismo libro varias veces: una copia comprada, otra
descargada, una reconvertida... con títulos ligeramente distintos que Calibre
no detecta como duplicados. Este plugin lee el texto real de los capítulos y
calcula un **porcentaje de similitud** entre libros, así que encuentra
duplicados aunque el título o el nombre de fichero no coincidan exactamente.

## Modos de uso (menú del plugin)

| Acción | Qué hace |
|---|---|
| **Comparar manualmente** | Compara dos libros que elijas tú (selecciona exactamente 2 y lánzalo). Muestra el % global y una tabla capítulo a capítulo. |
| **Comparar seleccionados automáticamente** | Entre los libros que selecciones, agrupa candidatos por título/autor parecidos (mismo idioma) y compara el contenido de cada pareja. |
| **Comparar toda la biblioteca** | Igual que el anterior pero sobre todos los libros de la librería. |
| **Ultrarrápido — solo 100%** (seleccionados o biblioteca completa) | Busca únicamente duplicados **exactos** capítulo a capítulo (hash MD5). Mucho más rápido; ideal para limpiar duplicados obvios en librerías grandes. |
| **Reabrir última revisión** | Vuelve a abrir el diálogo de resultados de la última pasada, por si lo cerraste sin terminar de revisar. |

Los resultados se calculan en segundo plano (no bloquean Calibre) y van
apareciendo en el diálogo de revisión a medida que están listos.

## Cómo se agrupan los candidatos (modos automáticos)

Antes de leer ningún fichero, el plugin empareja libros candidatos a ser el
mismo por: mismo idioma exacto, título parecido (aunque no idéntico: ignora
subtítulos y marcas como "(Edición ilustrada)") y autor parecido (tolera
"Apellido, Nombre" vs "Nombre Apellido" y nombres incompletos). Solo entonces
compara el contenido real; los falsos positivos de esta fase se descartan al
ver que el texto no coincide.

## Revisar y borrar duplicados

En el diálogo de resultados, cada pareja muestra el % de similitud global (en
color: verde ≥75%, naranja ≥40%, rojo <40%), el tamaño de cada fichero y una
tabla con la correspondencia capítulo a capítulo. Puedes borrar directamente
el libro sobrante (con confirmación) y pasar a la siguiente pareja sin volver
a lanzar el análisis.

## Instalación

1. En Calibre: **Preferencias → Plugins → Cargar plugin desde fichero**.
2. Selecciona `EbookComparator.zip` y reinicia Calibre.

## Limitaciones conocidas

- Solo compara ficheros **EPUB** y **AZW3** (PDF, MOBI y otros formatos se
  ignoran).
- Convertir AZW3 requiere que `ebook-convert` esté accesible (viene con
  Calibre).
- El modo ultrarrápido solo encuentra duplicados **exactos**; para libros con
  cambios parciales (p. ej. solo el prólogo distinto) usa el modo automático
  normal.
- El emparejamiento previo por título/autor es aproximado: un error tipográfico
  en la primera palabra del título, o un idioma mal etiquetado en Calibre,
  puede hacer que dos copias del mismo libro no lleguen a compararse.

## Ficheros

| Fichero | Función |
|---|---|
| `__init__.py` | Registro del plugin |
| `action.py` | Menú y coordinación de los trabajos en segundo plano |
| `jobs.py` | Búsqueda de pares candidatos y comparación por lotes |
| `ui.py` | Diálogos de comparación manual y de revisión de pares |
| `extractor.py` | Extrae los capítulos de EPUB/AZW3 |
| `comparator.py` | Algoritmo de similitud (SimHash + TF-IDF + SequenceMatcher, y modo ultrarrápido por MD5) |
| `COMPORTAMIENTO_PLUGIN.md` | Documentación técnica detallada del comportamiento interno |
