# Goodreads Fast — Documentación de comportamiento del plugin

**Versión:** 1.8.14 (nota: el `README.md` y la tabla de plugins en `CLAUDE.md`
dicen 1.6.0 — revisar cuál es la correcta antes de publicar; `__init__.py` es
la fuente de verdad real).
**Calibre mínimo:** 2.0.0
**Capacidades:** `identify`, `cover`

---

## Índice

1. [Arquitectura general](#1-arquitectura-general)
2. [Flujo de `identify()`](#2-flujo-de-identify)
3. [Generación de variantes de búsqueda](#3-generación-de-variantes-de-búsqueda)
4. [Ranking de candidatos](#4-ranking-de-candidatos)
5. [Pin por ISBN (con guarda)](#5-pin-por-isbn-con-guarda)
6. [Agrupación de ediciones](#6-agrupación-de-ediciones)
7. [`worker.py` — descarga y parseo de la ficha](#7-workerpy--descarga-y-parseo-de-la-ficha)
8. [Etiquetas enriquecidas (shelves)](#8-etiquetas-enriquecidas-shelves)
9. [Limitaciones conocidas y decisiones deliberadas](#9-limitaciones-conocidas-y-decisiones-deliberadas)

---

## 1. Arquitectura general

```
__init__.py   ← Clase Source de calibre: identify(), download_cover(), y TODO
                el pipeline de búsqueda/ranking (autocompletado, matching, ISBN)
worker.py     ← Un hilo por edición candidata: descarga la ficha del libro
                (JSON __NEXT_DATA__), la parsea a Metadata, y opcionalmente
                trae tags enriquecidas de las "shelves" populares
```

No hay `action.py`/menú propio: es un plugin de tipo *Source* (fuente de
metadatos), se integra en el flujo estándar de Calibre
(`Preferencias → Descarga de metadatos` + el botón de varita / "Descargar
metadatos" sobre los libros seleccionados).

---

## 2. Flujo de `identify()`

1. Si el libro ya tiene un identificador `goodreads` guardado, se usa
   directamente (`ids = [goodreads_id]`), sin buscar nada.
2. Si no, `_search_ids()` (§3-§6) decide qué edición(es) de Goodreads
   corresponden al `(title, authors, identifiers)` de entrada.
3. Se lanza un `Worker` (hilo) por cada id encontrado (hasta 3, ver §6), en
   paralelo, cada uno descargando y parseando su propia página.
4. Los resultados se ordenan por "riqueza" — `(len(comments), has_cover)` — y
   se emiten TODOS a `result_queue` con `source_relevance` creciente (el más
   rico primero), para que el usuario pueda elegir otra edición a mano si
   Calibre está en modo manual de selección.

---

## 3. Generación de variantes de búsqueda

`_search_ids()` no lanza una única consulta al autocompletado: prueba varias
variantes EN ORDEN hasta encontrar un match fuerte, para maximizar el
"recall" sin sacrificar precisión (`_gather()` corta en cuanto una consulta
produce un candidato con `tsim >= 0.95` (o exacto) y `amatch >= 0.5`):

1. **`_title_cores()`**: extrae hasta 3 candidatos de "núcleo de título" —
   cabeza (antes del separador), cola (después), y cualquier segmento
   intermedio — porque un título mal cargado en Calibre puede llevar el
   prefijo de la saga ANTES del título real (`"Fate of Wizardoms -
   Wizardoms: Rise of a Wizard Queen"`), y no siempre es el primer segmento
   el que hay que buscar.

   **Separadores reconocidos (`_SEGMENT_SPLIT_RE`, v1.8.14):** además de `:`
   y ` - ` (guion con espacios), se reconocen las variantes típicas de un
   título sacado de un nombre de fichero, donde `:` y el espacio no son
   válidos: `:`/` - ` con guiones bajos alrededor (`"Blade_:_A ..."`,
   `"Blade_-_A ..."`), una racha de **2 o más** `_` seguidos (`"Blade__A
   ..."`), y `|`. Un `_` **suelto** NO cuenta como separador a propósito:
   casi siempre sustituye a un espacio individual
   (`"Blade_A_Bear_Shifter_Biker_Romance"` es UN título con espacios raros,
   no seis palabras sueltas) y tratarlo como tal fragmentaría el título en
   trozos de una palabra. Se limpia más abajo (se convierte en espacio) igual
   que el resto de puntuación. Mismo regex compartido por
   `_cand_title_variants()`, para que el filtro de reclamo de género (más
   abajo) reconozca la cola también en los títulos de los candidatos si
   alguna vez vinieran así.

   **Excepción (v1.8.13):** un segmento que NO es la cabeza y que es un
   *reclamo de género* — `_is_boilerplate_segment()` — no se usa como núcleo
   independiente. Son los subtítulos comerciales que Amazon/KDP pegan a los
   libros (`"A Reverse Harem Dragon Shifter Romance"`, `"A Bear Shifter Biker
   Romance"`), compartidos por cientos de títulos distintos. Se reconocen por
   la forma, no por una lista de frases: `<artículo> … <sustantivo de género>`
   (romance, novel, thriller, story, saga, memoir…), o sin artículo si además
   llevan dentro alguna etiqueta comercial (`shifter`, `harem`, `mafia`,
   `billionaire`…). El título completo se conserva siempre; y si el título
   ENTERO es un reclamo así, se busca igual, porque no hay otra cosa.
2. **`_author_variants()`**: autor primario primero, luego cada coautor por
   separado — así un libro con varios autores se encuentra aunque Goodreads
   solo tenga catalogado a uno de ellos.
3. **`_query_variants()`** combina ambos: cada núcleo de título + autor
   primario, luego núcleos solos (sin autor), luego núcleo + cada autor
   secundario, y como último recurso el título recortado a 4/3/2 palabras
   (con y sin autor) — para títulos muy largos o con ruido.
4. Si NINGUNA variante encuentra nada, se reintenta una vez con **título y
   autor intercambiados** (`attempts.append((' '.join(authors), [title]))`)
   — cubre bibliotecas donde esos dos campos están invertidos por error.

---

## 4. Ranking de candidatos

`_rank_candidates()` puntúa cada resultado crudo del autocompletado:

- **Similitud de título** (`_title_similarity`): mejor solape de tokens entre
  cualquier núcleo de la consulta y cualquier segmento del título candidato
  (cabeza/cola/completo), con bonus si hay coincidencia EXACTA de algún par.
  Antes de comparar, se glutinan apóstrofes (`"She's"` → `"Shes"`, igual que
  en el lado de la consulta) y se descartan segmentos "estructurales" (solo
  palabras tipo `volume`/`book`/número: `"Volume Two"`) salvo que sea el
  título completo, porque muchos libros no relacionados reusan la misma
  etiqueta de volumen/parte.
- **Similitud de autor** (`_author_similarity`): fracción de tokens del
  autor candidato presentes en el conjunto de tokens de TODOS los autores de
  la consulta — un apellido compartido solo no basta para dar 1.0.
- **Puerta de aceptación** (antes de puntuar): `exact` (coincidencia exacta
  de título) **o** `tsim >= 0.85` **o** (`amatch >= 0.5` y `tsim >= 0.7`).
  Todo lo demás se descarta sin más — la similitud de autor NUNCA rescata
  por sí sola un título que no encaja razonablemente.
- **Fórmula de score** (solo entre los que pasan la puerta):
  `tsim * 10 + (6 si exact) + 4 * amatch`, con:
  - penalización de -6 si consulta y candidato mencionan AMBOS un número de
    volumen/parte y DISCREPAN (p. ej. consulta "Book 2" vs candidato "Book
    One") — pero un número presente solo en un lado NUNCA penaliza (un
    "50" perdido en un subtítulo de Goodreads que la consulta no menciona no
    es un conflicto real);
  - bonus de popularidad `min(2.0, log10(ratingsCount+1))` solo si
    `tsim >= 0.7` (la popularidad refuerza un match ya decente, nunca
    rescata uno débil) — y penalización de -1 si el candidato no tiene
    ninguna valoración.
  - se descartan directamente los candidatos marcados `'NOT A BOOK'` como
    autor, y los que contienen algún `JUNK_MARKERS` activo (bundle, box set,
    guía de lectura, resumen, omnibus...) — salvo que ese marcador ya esté
    presente en el propio título de la consulta (entonces el libro buscado
    ES ese tipo de producto, es legítimo).
- Umbral final: `score >= MIN_MATCH_SCORE` (4.0) para entrar en la lista
  ordenada de candidatos.

---

### 4.1. Por qué el reclamo de género importa tanto aquí

La puerta de aceptación deja pasar **cualquier** coincidencia exacta de título
sin mirar el autor (decisión deliberada: seudónimos y coautorías). Eso, sumado
a un núcleo de búsqueda que fuese un reclamo de género, producía resultados
directamente inventados: para `"Bonded to her Royal Mates: A Reverse Harem
Dragon Shifter Romance"` de Claire Heat — un libro que **no está en
Goodreads** — el núcleo `"A Reverse Harem Dragon Shifter Romance"` casaba
`exact`/`tsim=1.00` contra tres libros de Misty Malloy, los tres empatados a
`18.00` (el bonus de popularidad está topado en 2.0, así que 138, 173 y 309
votos puntúan igual) y el empate lo rompía el orden de inserción. Con el
filtro de la §3 esos tres candidatos ya no llegan a puntuarse y la respuesta
es "no match", que es la correcta.

Hay test de regresión de punta a punta en
`tests/test_goodreads_fast.py::TestRankCandidates`.

---

## 5. Pin por ISBN (con guarda)

Si la consulta trae ISBN, se busca también por ese ISBN. El resultado
**solo** se usa como target fijo si su propio título/autor pasan la MISMA
puerta de aceptación que cualquier otro candidato (`exact or tsim>=0.85 or
(amatch>=0.5 and tsim>=0.7)`) — un ISBN mal asignado en el fichero de origen,
o un ISBN de Goodreads que apunta a un libro distinto, no puede imponerse
sobre la búsqueda por título/autor. Si el ISBN no pasa la puerta, se registra
en el log y se ignora, cayendo en la búsqueda normal.

Si el ISBN sí pasa la puerta, gana sobre cualquier resultado de la búsqueda
por título (`if isbn_cand is not None: target_cand = isbn_cand`), incluso si
la búsqueda por título encontró algo con score más alto.

---

## 6. Agrupación de ediciones

Una vez decidido el "libro objetivo" (`target_cand`), `_edition_group()`
recorre el pool completo de candidatos vistos durante la búsqueda (de TODAS
las variantes de consulta, no solo la que ganó) y añade hasta 3 ids que sean
"la misma obra" (`_same_book()`):

- Mismo `workId` de Goodreads si ambos lo tienen, **y**
- mismo título normalizado (tokens, con subtítulo recortado) **y** mismos
  tokens de número/volumen — así nunca se cuela una edición en otro idioma o
  un bundle distinto aunque comparta `workId`.
- Se excluyen ediciones cuyo título lleva un `JUNK_MARKERS` que el propio
  libro objetivo NO lleva (si el objetivo mismo es un bundle, sus ediciones
  hermanas también pueden serlo).

Esas hasta-3 ediciones se descargan en paralelo (§7) y se devuelven todas —
la elección final de cuál usar (más sinopsis + portada primero) ocurre
después de descargar, no antes.

---

## 7. `worker.py` — descarga y parseo de la ficha

Cada `Worker` es un hilo que descarga `.../book/show/<id>.xml` — la URL con
extensión `.xml` en vez de la página normal, porque la página sin extensión
está detrás de un WAF de AWS, y la `.xml` sirve la MISMA página Next.js con
el JSON `__NEXT_DATA__` que se necesita parsear. Ese truco ya no es fiable al
100 %: el WAF también rechaza la `.xml` de vez en cuando (503 en ~0,3 s), de
ahí la alternancia de URL descrita abajo.

- **Reintentos** (v1.8.11): hasta 4 intentos, con backoff 1 s / 2 s / 4 s (no
  antes del primero), en dos casos:
  1. la respuesta llega sin el book JSON (respuesta parcial), y
  2. Goodreads devuelve un código HTTP transitorio —
     `TRANSIENT_HTTP_CODES = {408, 425, 429, 500, 502, 503, 504}`.

  El caso 2 **no reintentaba antes de la v1.8.11**: `get_details()` devolvía
  `False` en la rama de excepción y `False` corta el bucle, así que un 503 del
  WAF acababa como "No matches found" en el intento #1 pese a que el comentario
  del bucle decía lo contrario. Un `404` y un *timeout* siguen abortando sin
  reintentar, que es lo correcto.
- **Alternancia de URL** (v1.8.11): `_other_url_flavour()` conmuta entre
  `/book/show/<id>.xml` y `/book/show/<id>` antes de cada reintento. El WAF de
  AWS acepta o rechaza cada variante por separado y de forma errática, así que
  cuando una da 503 la otra suele responder.
- **Sinopsis prestada de otra edición** (v1.8.12): Goodreads guarda la sinopsis
  por EDICIÓN, no por obra, y es muy frecuente que la ficha con más votos —la
  que gana el ranking— tenga literalmente `"Coming soon..."`. Cuando la ficha
  descargada no trae una descripción real (`_is_real_description()`: vacía, un
  marcador tipo *Coming soon* / *To be announced*, o menos de 60 caracteres de
  texto plano), se lee la lista de ediciones de la obra
  (`Work.editions.webUrl`, o `/work/editions/<legacyId>`) y se descarga la
  sinopsis de hasta 3 ediciones hermanas hasta encontrar una buena. Se
  descartan las ediciones cuyo *Edition language* no coincide con el idioma ya
  parseado de la nuestra, para no acabar con la sinopsis en alemán de un libro
  en inglés. **Solo se toma prestada la sinopsis**: el resto de metadatos
  (título, serie, ISBN, fecha, portada) sigue viniendo de la ficha elegida, que
  suele ser la que tiene la serie bien puesta. Caso que motivó el cambio:
  *Blade* de Eva Kent, obra `110186032` — la ficha `85746064` (Kindle, 268
  votos) dice "Coming soon..." y la `138295429` (Paperback) trae la sinopsis
  completa.
- **Detección de página de error**: si el `<title>` es una página de
  resultados de búsqueda o un 404, aborta ese candidato sin reintentar como
  si fuera un fallo transitorio.
- **Parseo**: el JSON `__NEXT_DATA__` contiene un `apolloState` con entradas
  con claves tipo `Book:<id>`, `Series:<id>`, `Contributor:<id>`,
  `Work:<id>`; se extraen por prefijo de clave.
- Campos extraídos del `book_json`/`work_json`: título, autores (solo los de
  rol `Author`/`Pseudonym`, salvo `GET_ALL_AUTHORS=True` que está fijado a
  `False`), serie + índice (`userPosition`), ISBN (13 preferido sobre el
  normal), valoración media, sinopsis (saneada con
  `sanitize_comments_html`), portada (verificada con una petición
  `HEAD`-like: descarta imágenes de <1000 bytes, típicamente placeholders),
  editorial, fecha de publicación (prioriza `work_json` sobre `book_json`
  porque `FIRST_PUBLISHED=True` está fijado — usa la fecha de la PRIMERA
  publicación de la obra, no de esta edición concreta), idioma (mapeado por
  nombre a código ISO vía un diccionario manual, con
  `canonicalize_lang` como fallback).
- Todos estos "interruptores" (`GET_ALL_AUTHORS`, `FIRST_PUBLISHED`) eran
  configurables en los plugins originales de los que deriva este (Goodreads
  de Grant Drake, Goodreads More Tags de Michon van Dooren) y aquí están
  fijados en el código — para cambiarlos hay que editar la constante, no hay
  UI.

---

## 8. Etiquetas enriquecidas (shelves)

Además de los géneros oficiales de la ficha (`bookGenres`), se hace una
petición aparte a `.../book/shelves/<id>` para leer las "estanterías"
populares con las que los usuarios de Goodreads clasifican el libro:

1. Se leen todas las shelves con su recuento de votos.
2. Cada nombre de shelf se traduce a 0+ tags en inglés vía `SHELF_MAPPINGS`
   (diccionario fijo, p. ej. `'sci-fi-fantasy'` → `['Science Fiction',
   'Fantasy']`).
3. **Doble umbral** para quedarse solo con las shelves relevantes: primero
   un mínimo absoluto de votos (`SHELF_THRESHOLD_ABSOLUTE=10`), luego un
   umbral relativo (`SHELF_THRESHOLD_PCT=30`% de la media de los puestos 3º
   y 4º del ranking) — evita que una única shelf dominante haga desaparecer
   tags secundarios legítimos, pero también recorta la cola larga de shelves
   marginales.
4. El resultado se une (`merge_tags`) con los géneros oficiales,
   deduplicando sin distinguir mayúsculas y descartando ruido de
   estado/formato (`TAG_BLOCKLIST`: `to-read`, `favorites`, `owned`,
   `audiobook`, `dnf`...) que no aporta información de género/tema.
5. Esta petición tiene su propio timeout más corto
   (`min(timeout, SHELF_TIMEOUT=8)`) porque es un enriquecimiento opcional:
   si falla o tarda, el libro se sigue devolviendo con los géneros oficiales
   nada más.

---

## 9. Limitaciones conocidas y decisiones deliberadas

- Depende por completo de la estructura actual de la página Next.js de
  Goodreads (`__NEXT_DATA__` / `apolloState`) y del endpoint de
  autocompletado; un cambio de Goodreads en cualquiera de los dos rompe el
  plugin hasta que se actualice.
- La puerta de aceptación de título (§4) es deliberadamente estricta: un
  título/autor muy distorsionado en Calibre puede no encontrar nada en vez
  de arriesgar un match incorrecto — es la misma filosofía que
  `ebook_comparator` y `fix_metadata`/`opf_compare.py` (mejor "no sé" que
  "adivino mal").
- `GET_ALL_AUTHORS` y `FIRST_PUBLISHED` son constantes de código, no
  preferencias de usuario — a diferencia de los plugins de los que deriva.
- El número de versión en `__init__.py` (1.8.10) no coincide con lo que
  reflejan `README.md`/`CLAUDE.md` (1.6.0) a fecha de escribir esto — revisar
  antes de asumir cuál es la vigente.
