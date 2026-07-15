# Ebook Comparator — Documentación de comportamiento del plugin

**Versión:** 2.7.1  
**Plataformas:** Windows · macOS · Linux  
**Calibre mínimo:** 6.0.0

---

## Índice

1. [Arquitectura general](#1-arquitectura-general)
2. [Modos de uso](#2-modos-de-uso)
   - 2.1 [Comparación manual](#21-comparación-manual)
   - 2.2 [Comparación automática — seleccionados](#22-comparación-automática--seleccionados)
   - 2.3 [Comparación automática — biblioteca completa](#23-comparación-automática--biblioteca-completa)
   - 2.4 [Modo ultrarrápido — solo 100 %](#24-modo-ultrarrápido--solo-100-)
3. [Flujo de jobs en modo automático](#3-flujo-de-jobs-en-modo-automático)
4. [Diálogos](#4-diálogos)
   - 4.1 [ComparisonDialog (manual)](#41-comparisondialog-manual)
   - 4.2 [PairReviewDialog (automático / ultrarrápido)](#42-pairreviewdialog-automático--ultrarrápido)
5. [Extracción y comparación de texto](#5-extracción-y-comparación-de-texto)
6. [Agrupación de pares](#6-agrupación-de-pares)
7. [Limitaciones conocidas](#7-limitaciones-conocidas)
8. [Historial de versiones](#8-historial-de-versiones)

---

## 1. Arquitectura general

```
action.py            ← InterfaceAction de Calibre (menú, coordinación de jobs)
  ↓ lanza
jobs.py
  scan_pairs_sync()              ← Hilo principal; sólo lee metadatos (rápido)
  _compare_pairs_chunk()         ← ThreadedJob worker; modo normal (background)
  _compare_pairs_chunk_ultrafast()← ThreadedJob worker; modo ultrarrápido (background)
  ComparisonWorker               ← QThread para comparación manual
  ↓ resultados
ui.py
  ComparisonDialog               ← Diálogo de comparación manual (2 libros)
  PairReviewDialog               ← Diálogo de revisión de pares automáticos
  ↓ llama a
extractor.py         ← Extrae capítulos de EPUB/AZW3
comparator.py        ← Algoritmo SimHash + TF-IDF + SequenceMatcher + ultrafast MD5
```

---

## 2. Modos de uso

### 2.1 Comparación manual

**Requisito:** exactamente 2 libros seleccionados en Calibre.

**Flujo:**

1. El usuario selecciona 2 libros y activa *Comparar manualmente*.
2. Se abre `ComparisonDialog` de forma **modal** (`exec_()`).
3. El usuario elige el método de comparación (combined / tfidf) y pulsa *Comparar*.
4. `ComparisonWorker` (QThread) extrae los capítulos y calcula la similitud **en segundo plano**, emitiendo señales de progreso al hilo GUI.
5. Al finalizar se muestra:
   - Porcentaje de similitud global (código de color: verde ≥ 75 %, naranja ≥ 40 %, rojo < 40 %).
   - Tamaño de cada fichero.
   - Número de capítulos únicos en A y en B.
   - Tabla capítulo a capítulo con su porcentaje individual.
6. Los botones *Borrar libro A* y *Borrar libro B* se habilitan tras la comparación.
7. Al borrar un libro se pide confirmación; si el usuario acepta, el libro se elimina de la biblioteca, se refresca la vista de Calibre y el diálogo se cierra (`accept()`).

---

### 2.2 Comparación automática — seleccionados

**Requisito:** al menos 2 libros seleccionados.

**Flujo:**

1. El usuario selecciona N libros y activa *Comparar seleccionados automáticamente*.
2. `scan_pairs_sync()` genera pares candidatos comparando cada libro con sus vecinos por **similitud difusa de título y autor** (idioma exacto) en el hilo principal (sólo metadatos, sin leer ficheros). Ver [§6](#6-agrupación-de-pares).
   - Solo se consideran libros con formato EPUB o AZW3.
   - Se generan pares de libros dentro de cada grupo (combinaciones de 2).
3. Los pares se dividen en **chunks de 20** (`CHUNK_SIZE = 20`).
4. Se lanza un `ThreadedJob` por chunk. Cada job llama a `_compare_pairs_chunk()` que:
   - Lee los EPUBs/AZW3.
   - Extrae capítulos (filtrando ruido: jacket, portada, nav, etc.).
   - Calcula la similitud con el algoritmo *combined* (SimHash + TF-IDF + SequenceMatcher).
   - Escribe sus resultados en el slot `chunk_holders[idx]` de la sesión.
5. **Cuando cada job termina** emite la señal `results_ready` (en el hilo GUI vía cola de señales Qt).
6. El slot `_on_results_ready()` acumula todos los resultados disponibles hasta ese momento y:
   - Si el diálogo aún no existe: crea `PairReviewDialog` y lo muestra con `show()` (no bloqueante).
   - Si el diálogo ya está abierto: llama a `add_results()` para **añadir los nuevos pares sin cerrar ni resetear el diálogo**.

---

### 2.3 Comparación automática — biblioteca completa

Idéntico al modo anterior, pero `scan_pairs_sync()` itera sobre **todos** los IDs de la biblioteca (`db.all_book_ids()`).

El resto del flujo es exactamente el mismo: chunks, jobs, señal, actualización incremental del diálogo.

---

### 2.4 Modo ultrarrápido — solo 100 %

**Requisito:** al menos 2 libros seleccionados (versión *seleccionados*) o ninguno (versión *biblioteca completa*).

**Objetivo:** encontrar únicamente pares de libros **idénticos capítulo a capítulo** (100 % de similitud), con el menor coste computacional posible.

**Flujo:**

1. La agrupación previa es la misma que en los modos automáticos (`scan_pairs_sync()`).
2. Los pares se dividen en chunks de 20 y se lanzan jobs con `_compare_pairs_chunk_ultrafast()`.
3. Para cada par, el worker:
   a. Extrae los capítulos de ambos libros.
   b. Llama a `compare_books_ultrafast()`, que **detiene la comparación en cuanto detecta que el resultado será < 100 %**.
   c. Si la similitud es exactamente 100 %: añade el par a los resultados.
   d. Si la similitud es < 100 %: **descarta el par silenciosamente** (no aparece en el diálogo).
   e. Los errores de extracción también se descartan (no se muestran pares con error).
4. El diálogo `PairReviewDialog` muestra únicamente los pares con similitud 100 %.
5. Si ningún par alcanza el 100 % al terminar todos los jobs, se muestra un aviso informativo.

**Condiciones de early-exit en `compare_books_ultrafast()`:**

| Condición | Acción |
|---|---|
| `total_a == 0` y `total_b == 0` | Descarte (sin contenido que comparar) |
| `total_a ≠ total_b` | Descarte inmediato (número de capítulos diferente) |
| Capítulo de A sin MD5 exacto en B | Descarte inmediato (early-exit) |
| Todos los capítulos de A emparejados | Resultado 100 % (por simetría total_a == total_b, B también está totalmente emparejado) |

---

## 3. Flujo de jobs en modo automático

```
_launch(ultrafast=False|True)
  │
  ├─ scan_pairs_sync()            [hilo principal]
  │    └─ devuelve [(pair1, pair2, ...)]
  │
  ├─ divide en chunks de 20 pares
  │
  ├─ session = _AutoSession(..., ultrafast=...)
  │    ├─ chunk_holders = [[], [], ...]   # un slot por chunk
  │    ├─ pending = N
  │    └─ ultrafast = True/False
  │
  └─ para cada chunk:
       ThreadedJob(
         _compare_pairs_chunk           [normal]
         _compare_pairs_chunk_ultrafast [ultrarrápido]
       )  [hilo background]
            │  cuando termina (fallo o éxito):
            └─ _on_chunk_done()
                  ├─ session.pending -= 1
                  └─ emit results_ready(session)   ──→  GUI thread
                                                          │
                                                    _on_results_ready(session)
                                                          │
                                                    acumula resultados
                                                          │
                                               ┌──────────┴──────────┐
                                        primera vez             ya existe
                                               │                     │
                                     PairReviewDialog.show()   add_results()
                                       (no bloqueante)          (incremental)
```

**Garantía de no pérdida de datos:** `add_results()` usa un `set` de claves `(book_a_id, book_b_id)` para detectar pares ya mostrados y solo añade los nuevos. La lista completa acumulada se pasa siempre al slot, por lo que incluso si una señal se procesa tardíamente no se pierden resultados.

---

## 4. Diálogos

### 4.1 ComparisonDialog (manual)

| Elemento | Descripción |
|---|---|
| Cabecera | Títulos de los dos libros seleccionados |
| Selector de método | *combined* (recomendado) / *tfidf* |
| Barra de progreso | Visible durante la comparación |
| Similitud global | Porcentaje con código de color |
| Tamaños | Formato y tamaño en bytes legibles |
| Estadísticas | Total capítulos, únicos en A, únicos en B, método usado |
| Tabla | Capítulo A → mejor coincidencia en B → similitud (%) |
| Botones borrar | Habilitados tras comparación; borran y cierran el diálogo |

### 4.2 PairReviewDialog (automático / ultrarrápido)

| Elemento | Descripción |
|---|---|
| Navegación | «Par X de N» con botones ← Anterior / Siguiente → |
| Título | Título y autores comunes del par actual |
| Similitud global | Porcentaje con código de color (rojo si hay error) |
| Info libros | Libro A y Libro B con formato y tamaño |
| Capítulos únicos | Listado de capítulos exclusivos de cada libro |
| Tabla | Mapa capítulo a capítulo con similitud individual |
| Botones borrar | Borran el libro elegido y avanzan al siguiente par |
| Botón cerrar | Cierra el diálogo sin borrar nada |

**Actualización incremental:** cuando un job posterior termina y el diálogo ya está abierto, `add_results()` añade los nuevos pares al final de la lista. El contador «Par X de N» se actualiza automáticamente. El usuario puede continuar navegando mientras llegan más resultados.

---

## 5. Extracción y comparación de texto

### extractor.py

#### Formatos soportados

- **EPUB** — lectura directa del ZIP.
- **AZW3** — convertido a EPUB con `ebook-convert` antes de procesar.

#### Detección de archivos de contenido HTML

Los archivos de texto se identifican por dos vías complementarias:

1. **Por extensión** (case-insensitive): `.html`, `.xhtml`, `.htm`.
2. **Por media-type en el manifiesto OPF**: se parsea el fichero `.opf` del EPUB y se incluyen todos los ítems cuyo `media-type` sea `application/xhtml+xml` o `text/html`, independientemente de su extensión.

La segunda vía cubre EPUBs (frecuentes en ciertos convertidores) donde los archivos de texto tienen extensión `.xml` pero están declarados como `application/xhtml+xml` en el manifiesto. Sin esta detección esos archivos se ignoraban completamente.

#### Archivos ignorados

Los archivos se clasifican en tres categorías de ignorados, que no participan en la comparativa:

| Razón | Criterio |
|---|---|
| `sistema` | El nombre contiene alguno de los patrones de sistema: `titlepage.xhtml`, `calibre_raster_cover`, `metadata.opf`, `nav.xhtml`, `toc.ncx` |
| `jacket` | El nombre de archivo empieza por `jacket` (cualquier extensión, cualquier capitalización) **o** el contenido HTML incluye `<meta name="calibre-content" content="jacket"/>` |
| `vacío` | El texto extraído tras parsear el HTML es una cadena vacía (página completamente en blanco o formada únicamente por imágenes sin texto alternativo) |

> **Nota sobre la detección de jacket por contenido:** en conversiones AZW3, Calibre puede partir el jacket en varios archivos o renombrarlo. La inspección del meta-tag garantiza que estos archivos quedan excluidos aunque su nombre no sea `jacket.*`. La detección se hace de forma eficiente: primero se busca el literal `calibre-content` en los primeros 4 KB del fichero antes de parsear el árbol HTML completo.

> **Nota sobre archivos pequeños:** no se aplica ningún filtro de longitud mínima. Fragmentos cortos (dedicatorias, citas, páginas de copyright, epígrafes) se incluyen en la comparativa. Solo se descarta un archivo cuando su texto extraído es completamente vacío.

#### Orden de procesamiento

1. Spine del OPF (orden canónico del libro).
2. Archivos HTML/XHTML presentes en el ZIP pero ausentes del spine (notas, apéndices, huérfanos), añadidos al final en orden alfabético.

#### Normalización de texto

Minúsculas → eliminación de acentos/diacríticos (NFD) → eliminación de puntuación → colapso de espacios.

---

### comparator.py — método *combined* (modos manual y automático normal)

El comparador aplica una cadena de tres técnicas en orden de coste computacional:

1. **Hash MD5** — detección de identidad exacta (score = 100 %).
2. **SimHash** (huella de 64 bits + distancia de Hamming):
   - Distancia ≤ 3 bits (similitud > 96 %): score directo sin TF-IDF (+ penalización de longitud).
   - Similitud < 60 %: descartado sin TF-IDF (score = 0).
   - Zona intermedia: pasa a la siguiente etapa.
3. **TF-IDF coseno + SequenceMatcher** (solo para la zona intermedia):
   - Ponderación: 70 % TF-IDF + 30 % SequenceMatcher (primeros 2000 caracteres).

En todos los casos se aplica una **penalización por diferencia de longitud** (media armónica + raíz cuadrada) para evitar que un fragmento corto contenido en un texto largo reciba score artificialmente alto.

**Umbral de capítulo único:** similitud < 35 % → el capítulo se considera único (sin pareja).

**Similitud global:** media aritmética de (mejor score de cada capítulo de A) y (mejor score de cada capítulo de B) sobre el universo total de capítulos de ambos libros.

---

### comparator.py — método *ultrafast* (modo ultrarrápido)

Algoritmo O(n) exclusivamente basado en MD5:

1. Si `total_a ≠ total_b` → descarte inmediato (sin similitud posible del 100 %).
2. Se calcula el MD5 de cada capítulo de B y se almacena en una lista indexada.
3. Para cada capítulo de A se busca una pareja exacta (mismo MD5) en B que aún no esté emparejada.
4. Si algún capítulo de A no tiene pareja exacta → descarte inmediato (**early-exit**).
5. Si todos los capítulos de A tienen pareja → similitud 100 % garantizada (la simetría total_a == total_b garantiza que todos los B también están emparejados).

No se calcula TF-IDF, SimHash, ni SequenceMatcher. Es adecuado para detectar duplicados exactos en bibliotecas grandes con un coste mínimo.

---

## 6. Agrupación de pares

`scan_pairs_sync()` genera un par candidato entre dos libros cuando se cumplen las tres condiciones siguientes:

1. **Idioma EXACTO.** El idioma es el primer valor del campo `languages` de Calibre para ese libro (cadena vacía si no está definido). Se exige exacto para no mezclar traducciones o ediciones bilingües que comparten título y autor.
2. **Título difuso.** Los títulos se normalizan (`_normalize_title()`) y se comparan con `difflib.SequenceMatcher.ratio()`. La normalización, en este orden: (a) quita contenido entre paréntesis/corchetes — marcas de edición como "(Edición ilustrada)" o "[Tomo 1]"; (b) corta el título en el primer `:` y descarta lo que sigue — subtítulo; (c) minúsculas, sin puntuación, sin artículo inicial, espacios colapsados. Los pasos (a)/(b) van ANTES de quitar la puntuación general porque, una vez convertidos `:` y paréntesis en espacios, ya no hay forma de distinguir "esto es un subtítulo" de "son más palabras del título". El par se acepta si la similitud resultante es `>= TITLE_FUZZY_THRESHOLD` (0.85). Efecto colateral aceptado: títulos de una misma saga con el mismo prefijo antes de `:` (p. ej. "Star Wars: Episodio IV" y "Star Wars: Episodio V") normalizan igual y generan un par candidato — se descarta en la comparación de CONTENIDO, no aquí.
3. **Autor difuso.** Cada autor se reduce a un conjunto de tokens (`_author_token_sets()`), independiente del orden de nombres y de la forma "Apellido, Nombre" vs "Nombre Apellido". Se compara CADA autor de un libro con CADA autor del otro usando el **coeficiente de solape** (tokens compartidos / tokens del nombre más corto, no Jaccard sobre la unión), y se toma el máximo. El par se acepta si ese máximo es `>= AUTHOR_FUZZY_THRESHOLD` (0.5). Usar el nombre más corto como denominador (en vez de la unión) permite que un autor con metadatos incompletos ("Tolkien") case con el nombre completo ("J.R.R. Tolkien"), caso en el que Jaccard clásico daría solo 0.33 y no se detectaría.

**Coste computacional:** comparar cada libro con todos los demás sería O(n²). Para evitarlo, dentro de cada idioma los libros se ordenan por título normalizado y cada uno solo se compara con los `NEIGHBORHOOD_WINDOW` (40) siguientes en ese orden ("sorted neighborhood"), quedando en O(n · 40). Contrapartida: dos libros cuyo título normalizado empiece de forma muy distinta (p. ej. una errata en la primera palabra) pueden no llegar a compararse aunque coincidan en el resto.

Un falso positivo en esta fase solo cuesta una comparación de CONTENIDO de más — `comparator.py` la descarta con un score bajo (ver [§5](#5-extracción-y-comparación-de-texto)). El filtrado fino de verdad ocurre ahí, no en esta agrupación; por eso los umbrales de título y autor se dejan deliberadamente permisivos.

Solo se incluyen en la agrupación libros que tengan al menos un formato EPUB o AZW3. Los libros sin ninguno de estos formatos se omiten.

---

## 7. Limitaciones conocidas

- El emparejamiento por título/autor es difuso (ver [§6](#6-agrupación-de-pares)) pero el **idioma sigue siendo exacto**, y el `NEIGHBORHOOD_WINDOW` puede dejar sin comparar libros cuyo título normalizado empiece de forma muy distinta (p. ej. errata en la primera palabra) o cuyo idioma en Calibre esté mal etiquetado. Subtítulos ("Título: Edición ilustrada") y marcas de edición entre paréntesis/corchetes ("Título (Edición ilustrada)") se descartan antes de comparar (desde v2.7.1), pero un subtítulo pegado SIN separador (p. ej. "El Hobbit Edición Ilustrada" sin `:` ni paréntesis) no se detecta.
- Formatos soportados: **EPUB** y **AZW3**. PDF, MOBI y otros no se procesan.
- La conversión AZW3 → EPUB requiere que `ebook-convert` esté accesible en el PATH o junto al ejecutable de Python.
- Bibliotecas muy grandes (> 1000 libros con muchos duplicados) pueden generar muchos jobs simultáneos. Calibre los encola internamente pero puede haber espera.
- El diálogo `PairReviewDialog` permanece en primer plano; el usuario puede seguir usando Calibre mientras los jobs terminan en background.
- El modo ultrarrápido no detecta duplicados parciales (ej. libros donde solo cambia el prólogo). Para esos casos usar el modo automático normal.

---

## 8. Historial de versiones

| Versión | Cambios principales |
|---|---|
| **2.7.1** | `_normalize_title()` descarta subtítulos (tras `:`) y marcas de edición entre paréntesis/corchetes antes de comparar, para que "Título: Edición ilustrada" / "Título (Edición ilustrada)" normalicen igual que "Título". |
| **2.7.0** | Agrupación de pares (`scan_pairs_sync()`) pasa de clave exacta `(título, autor, idioma)` a emparejamiento **difuso** de título (SequenceMatcher) y autor (coeficiente de solape de tokens), manteniendo el idioma exacto. Blocking por "sorted neighborhood" para mantener el coste O(n · ventana). |
| **2.5.0** | Soporte de archivos `.xml` como contenido XHTML (detección por media-type OPF). Agrupación de pares por `(título, autor, idioma)`. Nuevo modo ultrarrápido que muestra solo pares con 100 % de similitud, con early-exit en la comparación. |
| **2.4.0** | Algoritmo combined (SimHash + TF-IDF + SequenceMatcher). Penalización por diferencia de longitud. Detección de jacket por contenido. Extracción de archivos huérfanos fuera del spine. Detección case-insensitive de extensiones HTML. |
