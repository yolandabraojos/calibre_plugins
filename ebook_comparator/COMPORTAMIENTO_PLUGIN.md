# Ebook Comparator — Documentación de comportamiento del plugin

**Versión:** 2.3.1  
**Plataformas:** Windows · macOS · Linux  
**Calibre mínimo:** 5.0.0

---

## Índice

1. [Arquitectura general](#1-arquitectura-general)
2. [Modos de uso](#2-modos-de-uso)
   - 2.1 [Comparación manual](#21-comparación-manual)
   - 2.2 [Comparación automática — seleccionados](#22-comparación-automática--seleccionados)
   - 2.3 [Comparación automática — biblioteca completa](#23-comparación-automática--biblioteca-completa)
3. [Flujo de jobs en modo automático](#3-flujo-de-jobs-en-modo-automático)
4. [Diálogos](#4-diálogos)
   - 4.1 [ComparisonDialog (manual)](#41-comparisondialog-manual)
   - 4.2 [PairReviewDialog (automático)](#42-pairreviewdialog-automático)
5. [Extracción y comparación de texto](#5-extracción-y-comparación-de-texto)
6. [Bugs corregidos](#6-bugs-corregidos)
7. [Limitaciones conocidas](#7-limitaciones-conocidas)

---

## 1. Arquitectura general

```
action.py            ← InterfaceAction de Calibre (menú, coordinación de jobs)
  ↓ lanza
jobs.py
  scan_pairs_sync()  ← Hilo principal; sólo lee metadatos (rápido)
  _compare_pairs_chunk() ← ThreadedJob worker; lee EPUBs (lento, en background)
  ComparisonWorker   ← QThread para comparación manual
  ↓ resultados
ui.py
  ComparisonDialog       ← Diálogo de comparación manual (2 libros)
  PairReviewDialog       ← Diálogo de revisión de pares automáticos
  ↓ llama a
extractor.py         ← Extrae capítulos de EPUB/AZW3
comparator.py        ← Algoritmo SimHash + TF-IDF + SequenceMatcher
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
2. `scan_pairs_sync()` agrupa los libros por `(título, autor)` en el hilo principal (sólo metadatos, sin leer ficheros).  
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

## 3. Flujo de jobs en modo automático

```
_launch()
  │
  ├─ scan_pairs_sync()            [hilo principal]
  │    └─ devuelve [(pair1, pair2, ...)]
  │
  ├─ divide en chunks de 20 pares
  │
  ├─ session = _AutoSession(...)
  │    ├─ chunk_holders = [[], [], ...]   # un slot por chunk
  │    └─ pending = N
  │
  └─ para cada chunk:
       ThreadedJob(_compare_pairs_chunk, holder, chunk)  [hilo background]
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

### 4.2 PairReviewDialog (automático)

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

#### Detección de extensiones HTML (case-insensitive)

Las extensiones `.html`, `.xhtml` y `.htm` se reconocen en cualquier capitalización (`.HTML`, `.XHTML`, etc.). Esto es especialmente relevante en EPUBs generados por conversión AZW3 bajo Windows, donde algunos archivos pueden aparecer con extensiones en mayúsculas.

#### Archivos ignorados

Los archivos se clasifican en tres categorías de ignorados, que no participan en la comparativa:

| Razón | Criterio |
|---|---|
| `sistema` | El nombre contiene alguno de los patrones de sistema: `titlepage.xhtml`, `calibre_raster_cover`, `metadata.opf`, `nav.xhtml`, `toc.ncx` |
| `jacket` | El nombre de archivo empieza por `jacket` (cualquier extensión, cualquier capitalización) **o** el contenido HTML incluye `<meta name="calibre-content" content="jacket"/>` |
| `vacío` | El texto extraído tras parsear el HTML es una cadena vacía (página completamente en blanco o formada únicamente por imágenes sin texto alternativo) |

> **Nota sobre la detección de jacket por contenido:** en conversiones AZW3, Calibre puede partir el jacket en varios archivos o renombrarlo. La inspección del meta-tag garantiza que estos archivos quedan excluidos aunque su nombre no sea `jacket.*`. La detección se hace de forma eficiente: primero se busca el literal `calibre-content` en los primeros 4 KB del fichero antes de parsear el árbol HTML completo.

> **Nota sobre archivos pequeños:** a diferencia de versiones anteriores, **no se aplica ningún filtro de longitud mínima**. Fragmentos cortos (dedicatorias, citas, páginas de copyright, epígrafes) se incluyen en la comparativa. Solo se descarta un archivo cuando su texto extraído es completamente vacío.

#### Orden de procesamiento

1. Spine del OPF (orden canónico del libro).
2. Archivos HTML presentes en el ZIP pero ausentes del spine (notas, apéndices, huérfanos), añadidos al final en orden alfabético.

#### Normalización de texto

Minúsculas → eliminación de acentos/diacríticos (NFD) → eliminación de puntuación → colapso de espacios.

---

### comparator.py — método *combined*

El comparador aplica una cadena de tres técnicas en orden de coste computacional:

1. **Hash MD5** — detección de identidad exacta (score = 100 %).
2. **SimHash** (huella de 64 bits + distancia de Hamming):
   - Distancia ≤ 3 bits (similitud ≥ 95 %): score directo sin TF-IDF.
   - Distancia > 26 bits (similitud < 60 %): descartado sin TF-IDF.
   - Zona intermedia: pasa a la siguiente etapa.
3. **TF-IDF coseno + SequenceMatcher** (solo para la zona intermedia):
   - Ponderación: 70 % TF-IDF + 30 % SequenceMatcher (primeros 2000 caracteres).

En todos los casos se aplica una **penalización por diferencia de longitud** (media armónica + raíz cuadrada) para evitar que un fragmento corto contenido en un texto largo reciba score artificialmente alto.

**Umbral de capítulo único:** similitud < 35 % → el capítulo se considera único (sin pareja).

**Similitud global:** media aritmética de (mejor score de cada capítulo de A) y (mejor score de cada capítulo de B) sobre el universo total de capítulos de ambos libros.

---

## 6. Bugs corregidos

### Bug 1 — Pérdida de resultados entre jobs (crítico)

**Fichero:** `action.py` — método `_show_results` (versión original).

**Problema:** cada vez que un job terminaba, el slot cerraba el diálogo existente con `close()` y creaba uno nuevo con `exec_()`. Esto provocaba:
- Los pares ya revisados por el usuario desaparecían.
- El diálogo nuevo solo mostraba los resultados acumulados hasta ese momento, pero el usuario perdía su posición de navegación.
- `exec_()` es bloqueante: el hilo GUI quedaba bloqueado dentro del diálogo, impidiendo que los callbacks de los jobs posteriores pudiesen ejecutarse.

**Corrección:**
- El slot `_on_results_ready()` mantiene una referencia al diálogo (`self._review_dialog`).
- Primera llamada: crea el diálogo y lo muestra con `show()` (no bloqueante).
- Llamadas posteriores: llama a `add_results()` sobre el diálogo existente.
- `add_results()` usa un `set` de claves `(book_a_id, book_b_id)` para añadir solo los pares nuevos, sin resetear el estado de navegación.

### Bug 2 — Señal conectada a método renombrado

**Fichero:** `action.py` — `genesis()`.

**Problema:** `self.results_ready.connect(self._show_results)` pero el método se renombró a `_on_results_ready`.

**Corrección:** conectar a `self._on_results_ready`.

### Bug 3 — `PairReviewDialog` no tenía método público para añadir resultados

**Fichero:** `ui.py`.

**Problema:** el diálogo no exponía ninguna API para recibir nuevos pares desde fuera.

**Corrección:** añadido método `add_results(all_results_so_far)` e interno `_pair_key()`. Separada la lógica de refresco de etiquetas de navegación en `_refresh_nav()` para poder actualizar el contador sin recargar el contenido del par actual.

### Bug 4 — `ComparisonDialog._delete_book` cerraba con `self.close()` sin confirmación visual

**Fichero:** `ui.py` — clase `ComparisonDialog`.

**Problema:** la versión original llamaba `error_dialog(..., 'Libro borrado', ...)` y luego `self.close()`. El diálogo de error puede quedar detrás de la ventana principal; además `close()` no espera a que el usuario lo descarte.

**Corrección:** se muestra primero el diálogo de confirmación de borrado y después se llama `self.accept()` para cerrar limpiamente el `QDialog`.

### Bug 5 — `_on_chunk_done` no decrementaba `pending` antes de emitir

**Fichero:** `action.py` (versión original).

**Problema:** el decremento de `session.pending` y la emisión de `results_ready` ocurrían en el mismo bloque, pero la lógica de «¿quedan jobs?» en `_show_results` no era fiable porque se leía `pending` sin el lock.

**Corrección:** el decremento se hace bajo el lock; la emisión ocurre fuera del lock.

### Bug 6 — Jacket no detectado en conversiones AZW3

**Fichero:** `extractor.py`.

**Problema:** al convertir AZW3 a EPUB, Calibre puede renombrar o fragmentar el archivo jacket. La detección anterior solo comprobaba si el nombre de archivo empezaba por `jacket`, por lo que estos archivos pasaban a la comparativa como capítulos normales, inflando artificialmente la similitud.

**Corrección:** añadida función `_is_jacket_by_content()` que inspecciona el contenido HTML en busca de `<meta name="calibre-content" content="jacket"/>`. La búsqueda se hace en dos fases: primero sobre los primeros 4 KB en bytes (sin parsear) y solo si hay coincidencia se parsea el árbol HTML completo.

### Bug 7 — Archivos con extensión `.HTML` en mayúsculas no procesados

**Fichero:** `extractor.py`.

**Problema:** las comprobaciones `endswith(('.html', '.xhtml', '.htm'))` son case-sensitive. En EPUBs generados por algunas versiones de Calibre o por conversión desde AZW3 en Windows, los archivos pueden tener extensión `.HTML` o `.XHTML`, y por tanto quedaban excluidos silenciosamente.

**Corrección:** introducida la función auxiliar `_is_html_file(name)` que normaliza el nombre a minúsculas antes de comprobar la extensión. Aplicada de forma consistente en todos los puntos donde antes se usaba `endswith` directamente. La resolución de rutas en `_get_spine_order` también incluye ahora un índice case-insensitive para el fallback de búsqueda en el ZIP.

### Bug 8 — Fragmentos cortos excluidos de la comparativa

**Fichero:** `extractor.py`.

**Problema:** el filtro `if len(text) > 50` descartaba silenciosamente dedicatorias, citas, páginas de copyright y otros fragmentos breves pero relevantes para la comparativa.

**Corrección:** eliminado el umbral mínimo de longitud. Ahora solo se ignora un archivo cuando su texto extraído es completamente vacío (cadena de longitud cero tras normalización), lo que corresponde únicamente a páginas en blanco o archivos formados exclusivamente por imágenes sin texto alternativo.

---

## 7. Limitaciones conocidas

- Solo se comparan libros que comparten **título y autor exactos** (en minúsculas). Diferencias tipográficas mínimas crean grupos separados.
- Formatos soportados: **EPUB** y **AZW3**. PDF, MOBI y otros no se procesan.
- La conversión AZW3 → EPUB requiere que `ebook-convert` esté accesible en el PATH o junto al ejecutable de Python.
- Bibliotecas muy grandes (> 1000 libros con muchos duplicados) pueden generar muchos jobs simultáneos. Calibre los encola internamente pero puede haber espera.
- El diálogo `PairReviewDialog` permanece en primer plano; el usuario puede seguir usando Calibre mientras los jobs terminan en background.
