# Fix Metadata — Documentación de comportamiento del plugin

**Versión:** 1.7.8
**Plataformas:** Windows · macOS · Linux
**Calibre mínimo:** 2.0.0

---

## Índice

1. [Arquitectura general](#1-arquitectura-general)
2. [Patrón general: directo vs revisión (CompareMany) vs solo marcar](#2-patrón-general-directo-vs-revisión-comparemany-vs-solo-marcar)
3. [Extraer metadatos del fichero](#3-extraer-metadatos-del-fichero)
4. [Fix all (series, idioma, subtítulo, universo)](#4-fix-all-series-idioma-subtítulo-universo)
5. [Fix author](#5-fix-author)
6. [Fix identifiers](#6-fix-identifiers)
7. [Check comments](#7-check-comments)
8. [Fix tags](#8-fix-tags)
9. [Compare with file metadata (OPF vs calibre)](#9-compare-with-file-metadata-opf-vs-calibre)
10. [Campos personalizados usados](#10-campos-personalizados-usados)
11. [Limitaciones conocidas y decisiones deliberadas](#11-limitaciones-conocidas-y-decisiones-deliberadas)

---

## 1. Arquitectura general

```
action.py                ← InterfaceAction: menú (7 submenús) y sus acciones
  ├─ extractor.py         ← Lee metadatos embebidos en EPUB/AZW3 (generator, producer, title_opf, subjects)
  ├─ jobs.py               ← ThreadedJob por lotes de 100 para la extracción
  ├─ fix_title.py           ← Detección de serie/índice/idioma/subtítulo/serie_gen embebidos en el título (patrones A-AA)
  ├─ fix_title_series.py    ← Patrones adicionales de serie (usados por fix_title / legacy)
  ├─ fix_author.py           ← Normalización de nombres de autor
  ├─ fix_identifiers.py      ← Normalización de identificadores (amazon/isbn/UUID)
  ├─ fix_world.py + world_map.json  ← Universo narrativo a partir de la serie (mecánico, sin diálogo propio)
  ├─ fix_comments.py         ← Heurísticas de calidad de sinopsis (sin modificarla nunca)
  ├─ fix_tags.py + tags_map.json    ← Canonicalización de tags a "Grupo · Valor"
  ├─ matching.py             ← Similitud título/autor + conflicto de idioma (compartido)
  ├─ opf_compare.py          ← Compara metadatos del fichero (OPF) vs calibre, usa matching.py
  └─ compare_review.py       ← Envoltorio reusable del diálogo nativo CompareMany de calibre
```

Todos los módulos de lógica pura (`fix_*.py`, `matching.py`) son independientes
de Calibre y unit-testables por separado; solo `action.py`, `jobs.py` y
`compare_review.py` tocan la GUI/BD de Calibre.

**v1.7.0**: se eliminaron las clases `SeriesReviewDialog`, `SubtitleReviewDialog`
y `WorldReviewDialog` de `action.py` (quedaron huérfanas al fusionar Fix
series + Fix subtitle + Fix universe en `fix_all_action`). `TagsReviewDialog`
sigue viva y en uso (Fix tags no se tocó).

---

## 2. Patrón general: directo vs revisión (CompareMany) vs solo marcar

Las acciones del menú siguen uno de tres patrones, y **no es intercambiable
sin querer** — al modificar una acción hay que respetar cuál usa:

| Patrón | Acciones | Comportamiento |
|---|---|---|
| **Revisión (CompareMany)** | Fix all (título/serie/idioma/subtítulo/**#world**), Compare with file metadata | Construye un `Metadata` propuesto por libro y lo pasa a `review_changes()` (envoltorio de `compare_review.py`); el usuario acepta/edita/rechaza libro a libro antes de guardar nada. Los rechazados se marcan `revisar_metadata`. |
| **Escritura directa** | Extraer metadatos, Fix author, Fix identifiers, Fix tags | Calcula el cambio y lo escribe sin pasar por CompareMany ni por ningún diálogo. Fix tags SÍ marca (`marks:revisar_tags`) los libros con tags sin mapear, pero el cambio ya se guardó. |
| **Solo marcar (nunca escribe)** | Check comments | Una sinopsis mala no se puede "arreglar sola"; el plugin únicamente marca el libro (`marks:revisar_comentario` + un tag por tipo de problema) para revisión manual. |

`compare_review.py::review_changes()` ajusta además la altura del diálogo
CompareMany a un valor proporcional al número de campos (`fields`) que se le
pasan (`260 + 110 * len(fields)`, y solo si eso es MENOR que lo que calibre
calculó/restauró) — calibre por defecto abre este diálogo casi a pantalla
completa (650-1000px de alto) sin importar si solo hay 2-3 campos de una
línea, dejando huecos enormes.

`#subtitle` (y en teoría `#world`, aunque no es su caso de uso habitual)
requieren revisar el **tipo de columna** (`db.field_metadata['#xxx']['datatype']`): si `#subtitle` se creó
como "Long text, like comments" en vez de "Text", CompareMany la muestra con
el editor WYSIWYG completo (el mismo que usa `comments`) en vez de una caja
de texto de una línea — `fix_all_action` avisa con un `warning_dialog` (no
bloqueante) cuando detecta esto.

---

## 3. Extraer metadatos del fichero

Lee del propio EPUB/AZW3 (vía `extractor.py`, ver también el README de
`extract_metadata`, plugin hermano del que se derivó esta acción) el
generador, el productor del libro, el título tal cual está en el OPF y los
subjects, y los escribe en columnas personalizadas.

- Requiere que existan `#generator`, `#book_producer`, `#title_opf` y
  `#subjects` (`_check_custom_fields`); si falta alguna, aborta con un
  diálogo de error antes de procesar nada.
- Corre como `ThreadedJob` en lotes de 100 libros (`jobs.py`,
  `start_extract_threaded`).
- Escritura directa, sin CompareMany: cada campo se rellena solo si el
  fichero aportó un valor no vacío (`if generator: …`) — nunca borra un
  valor existente aunque el fichero no traiga nada para ese campo.
- Si existe `#subtitle` y el fichero aporta uno, también se rellena aquí.

---

## 4. Fix all (series, idioma, subtítulo, universo)

**v1.7.4 — títulos con autor como SUFIJO y dos patrones nuevos de serie:**
Muchos títulos de biblioteca vienen en formato `"NN Título - Autor"` o
`"Serie - NN Título - Autor"` (el autor pegado al final, no al principio).
Como casi todos los patrones A-T de `find_series_in_title()` anclan al
FINAL de la cadena (`...\s*$`), ese sufijo `" - Autor"` los rompía a todos
sin excepción. Ahora, antes de detectar, se llama a
`strip_known_author_suffix(title, author=mi.authors[0], author_sort=...)`
(función nueva, extraída de la lógica que `make_clean_title()` ya usaba
internamente) para quitar ese sufijo — anclado al autor real del libro, así
que solo actúa cuando el texto final coincide EXACTAMENTE con el autor (o su
variante "Apellido, Nombre" ⇄ "Nombre Apellido"), nunca por adivinanza. La
detección corre sobre esta copia sin autor; `make_clean_title()` se sigue
llamando con el título ORIGINAL (ella misma sabe quitar el sufijo de autor
en su propio pipeline).

Dos patrones nuevos al final de la cascada (los más débiles, evaluados
después de los A-T):

- **Patrón X** — `"Serie - N Título"` (guion ANTES del índice, sin anclar a
  autor; validado con `_is_valid_series()` como los demás). Cubre casos como
  `"Jackman & Evans - 09 Solace House"` o `"Nancy Drew Files - 010 Buried
  Secrets"` que ningún patrón anterior cazaba (H exige DOS guiones, J exige
  el guion DESPUÉS del número).
- **Patrón Y** — índice suelto sin serie, pero **solo en su forma `"N -
  Título"` (guion obligatorio)**. Probado contra `_datos_ejemplo/sample.csv`
  (8000 filas): con guion obligatorio dio 1 acierto y 0 falsos positivos;
  permitiendo también la forma sin guion (`"N Título"`, solo espacio) dio 18
  detecciones y las 18 eran falsos positivos — títulos reales que empiezan
  por un número ("10 Ways to Accidentally Fall in Love", "27 Dates", "7
  Noches de Pecado", "100 puertas", incluso "1462 South Broadway", una
  dirección postal). Por eso la forma sin guion se descartó deliberadamente:
  títulos como `"03 The Raging Storm"` o `"7 Days"` (ambos ejemplos reales
  aportados al definir esto) **no se detectan** — falso negativo aceptado a
  cambio de no inundar la revisión de propuestas erróneas.

**v1.7.0**: `fix_all_action` sustituye a las antiguas acciones independientes
"Fix series", "Fix subtitle" y "Fix universe". Antes eran tres pasadas
separadas (dos CompareMany distintos + un diálogo propio para `#world`);
ahora es una sola pasada que revisa título/serie/idioma/subtítulo juntos en
un único CompareMany, y rellena `#world` de forma automática/mecánica al
margen de esa revisión.

**Detección (por libro, sobre el título original):**

0. `find_generic_series_in_title()` → **Serie_Gen** (v1.7.6): un paréntesis
   final que nombra un universo/imprint/sub-serie SIN número — p.ej.
   `"(Elginvale High)"`, `"(American Haunts)"`, o con dos puntos dentro del
   propio paréntesis `"(Royal Bastards MC: Ankeny IA)"`. Se ejecuta ANTES
   que el resto (paso 1) y, si encuentra algo, lo quita de la copia de
   trabajo del título (`strip_generic_series_paren()`) para que los patrones
   de idioma/serie/subtítulo no lo vean. Cualquier paréntesis con un dígito
   dentro se descarta aquí (es una serie numerada normal, la resuelve el
   paso 2); también se descartan código de idioma, nota de edición, año y
   marcador de copia `(c.N)`. Va a la columna `#serie_gen` (separada de
   `series`, que siempre lleva índice) — ver §10.
1. `find_language_in_title()` → código de idioma tipo `(spa)` al principio o
   final del título.
2. `find_series_in_title()` → serie + índice (+ posible subtítulo de patrón
   `G` o `N`), evaluando ~25 patrones nombrados por letra (A, B, C… Z, AA,
   más `NIS`, v1.7.7) en orden de especificidad, del más restrictivo (`A`:
   requiere `#` explícito) al más débil (`E`: solo requiere que el título
   empiece por el nombre del autor seguido de ` - `). El orden importa: un
   patrón débil evaluado antes que uno fuerte podría capturar mal un caso
   que el patrón fuerte habría resuelto correctamente. Guardas
   transversales: `_is_valid_series()` rechaza nombres genéricos/
   numéricos/contenedores/blurbs de marketing; `_looks_like_year()` descarta
   como índice cualquier número ≥1000. Los números de índice aceptan tanto
   dígitos como palabras inglesas ("Book One", "Volume Nine") vía
   `_NUM`/`_to_index()`. `_normalize_series_name()` retira además
   separadores sueltos al final (`-`, `–`, `:`, `;`, `,`) que quedaban
   pegados a la serie capturada. Patrón `NIS` (v1.7.7):
   `"Título, No. N in the ['the ]Series 'NombreSerie'[ series]"` — el nombre
   va entre comillas (rectas o tipográficas), que es el ancla fiable, no la
   posición de la palabra "series"; usa captura perezosa `(.+?)` en vez de
   excluir comillas, para no romperse con nombres que llevan un apóstrofo
   recto propio (p.ej. `"Amy's Adventures in New York"`).
3. `make_clean_title()` limpia el título de TODO lo detectado (idioma,
   prefijo de autor/author_sort, nota de edición, año de publicación entre
   paréntesis, marcador de copia `(c.1)`, Serie_Gen, serie, y el subtítulo de
   patrón `G`/`N` si lo hay). Al final (v1.7.7) recorta cualquier separador
   colgante (` `, `:`, `;`, `-`, `–`) que haya quedado suelto al final tras
   quitar un paréntesis — p.ej. `"Justice Unserved: (Serie Book 1)"` →
   `"Justice Unserved:"` → `"Justice Unserved"`.
4. Subtítulo — desde v1.7.7 SIEMPRE se intenta, salvo que el paso 2 ya haya
   devuelto uno propio (patrón `G`/`N`); antes se saltaba por completo en
   cuanto se detectaba una serie, lo cual perdía el subtítulo en el caso muy
   común de que serie Y subtítulo vengan del MISMO título (p.ej.
   `"Tormented: A Dark High School Bully Romance (Elginvale High Book 1)"`
   tiene serie `"Elginvale High"` Y subtítulo `"A Dark High School Bully
   Romance"`, ambos del mismo texto). Se prueban tres detectores en cascada,
   el primero que encuentre algo gana:
   - `find_subtitle_in_title()` — estilo `"Título: Subtítulo"`. Con dos o
     más `": "` en el título se parte por el ÚLTIMO, no el primero
     (`rpartition`), así `"Istoria Online: Square One: A LitRPG Adventure"`
     da título `"Istoria Online: Square One"` y subtítulo `"A LitRPG
     Adventure"`. Rechaza subtítulos con estructura de serie ` - `, `#`,
     `[`, exige ≥3 caracteres, descarta paréntesis finales, y rechaza
     descriptores de colección puros tipo "The Complete Series"/"Boxed Set".
   - `find_dash_genre_subtitle_in_title()` (v1.7.7) — estilo `"Título - Un
     blurb de género"` (p.ej. `"Wanted By The Billionaire Cowboy - A Second
     Chance Romance"`); solo dispara si el texto tras el ` - ` TIENE forma de
     blurb de género (empieza por "a"/"an" + palabra tipo romance/mystery/
     saga/…, `_GENRE_BLURB_RE`), para no confundirse con un guion cualquiera.
   - `find_paren_genre_subtitle_in_title()` (v1.7.7) — estilo `"Título
     (Blurb de género)"` sin ningún otro separador, p.ej. `"Where there's a
     Will... (A Novel)"`; misma guarda de forma de blurb que el anterior.

   Todos se aplican sobre el título YA limpiado por `make_clean_title` en el
   paso 3, no sobre el título crudo.
4b. Fallback título = Serie + Índice (v1.7.7): si tras quitar serie/
    subtítulo/Serie_Gen no queda nada usable como título — o lo que queda
    es en sí mismo un blurb de género genérico repetido en todo el volumen,
    vía `whole_title_is_genre_blurb()` (p.ej. `"Futanarium 3: An Erotic
    Short Story Bundle"`: la serie es `"Futanarium"` índice 3, y "An Erotic
    Short Story Bundle" es texto de catálogo repetido en toda la serie, no
    el título real de ESTE libro) — el título pasa a ser `"Serie N"` y el
    texto sobrante (si no había ya un subtítulo) se guarda como subtítulo.
    Solo dispara si el paso 2 SÍ encontró serie; sin serie no hay a qué
    hacer fallback.
5. `#world`: usa como serie de búsqueda, en este orden: la serie ya guardada
   en el libro (`mi.series`) → la serie recién detectada en el título en el
   paso 2 (`found_series`) → si ninguna de las dos existe y hay columna
   `#title_opf` con un valor distinto del título actual, se re-ejecuta
   `find_series_in_title()` sobre ESE texto (el título original sin tocar,
   guardado por "Extraer metadatos") como último recurso. Esto permite
   resolver universo aunque el libro nunca haya tenido el campo `series`
   relleno en calibre. Nunca sobrescribe un `#world` ya existente. **Se
   muestra como una columna más en el mismo CompareMany** (editable,
   revertible, rechazable como cualquier otro campo) — a diferencia de
   Identifiers, que sí se quedó fuera porque ahí no hay un valor propuesto
   único por libro que tenga sentido enseñar/revertir, sino un
   find/replace en bloque sobre el diccionario de identificadores.

**v1.7.3 — de "nunca sobrescribir" a "propón todo, decide el humano":**
Hasta v1.7.2, `series_to_write`/`lang_to_write`/`subtitle_to_write` solo se
calculaban si el campo correspondiente estaba vacío (con una excepción para
el índice cuando el nombre de serie ya coincidía, ver commit de v1.7.2).
Desde v1.7.3 esa cautela se quitó para serie/índice/idioma/subtítulo: se
propone SIEMPRE lo que se detecta en el título, exista o no ya un valor
distinto guardado. La razón: como cada libro pasa igualmente por el
CompareMany, el ser humano que revisa es un filtro mejor que una regla
ciega de "nunca tocar" — puede aceptar, editar o revertir cada campo. Esto
significa que la cascada de patrones A-T SÍ puede proponer ahora un nombre
de serie distinto al guardado (los 40/138 falsos positivos identificados en
`_datos_ejemplo/sample.csv`, tipo "X-Men 3: The Last Stand" → "X-Men" en vez
de "X-Men Novelizations", se muestran como propuesta y hay que rechazarlos a
mano en vez de que el código los descarte solo).

`#world` es la ÚNICA excepción que conserva la regla de "nunca
sobrescribir": no se deriva del título de ESTE libro sino de un mapa curado
aparte (`world_map.json`), así que no tiene sentido ofrecer pisar un valor
que alguien ya fijó a mano.

**Solo se manda a revisión un libro si algo REALMENTE difiere** (de vuelta
al comportamiento de antes de v1.7.0, pero ahora calculado comparando el
`Metadata` propuesto contra el actual campo a campo — título, serie+índice,
idiomas, `#subtitle`, `#world` — no solo "¿se detectó algo?"). Si un valor
detectado coincide con el ya guardado, no cuenta como cambio y el libro no
aparece en el diálogo. Si NINGÚN libro de la selección tiene cambios, no se
abre CompareMany: se informa directamente "No changes detected".

Si `#title_opf` existe y está vacío, se guarda ahí el título original antes
de limpiarlo. `#world` se escribe SOLO si el libro fue aceptado en el
diálogo (como cualquier otro campo).

**Alcance de la revisión:** a diferencia de las acciones antiguas (que solo
mostraban libros con algún cambio detectado), Fix all envía **todos** los
libros seleccionados al CompareMany, tengan o no cambios — así se puede
revisar/editar/rechazar toda la selección en un único paso. `#world` se
aplica de todas formas a todo lo escaneado (acepte o rechace el usuario el
resto de campos de ese libro), salvo que se cancele el diálogo entero
(`accepted is None`), en cuyo caso no se escribe nada, ni siquiera `#world`.

Revisión vía CompareMany (campos `title`, `series`, `languages`, `#subtitle`
si existe, `#serie_gen` si existe, y `#world` si existe); los libros
rechazados se marcan `revisar_metadata` (antes: `revisar_serie`).

---

## 5. Fix author

`fix_author.py`, aplicado por cada nombre de autor de cada libro:

1. Invierte `"Apellido, Nombre"` → `"Nombre Apellido"` (solo si hay coma).
2. Expande iniciales sueltas sin puntos: `JK` → `J. K.`, `JRR` → `J. R. R.`
   (regex `_BARE_INITIALS`: 2-3 mayúsculas consecutivas como palabra
   aislada — así no confunde `KING` con iniciales).
3. Añade espacio entre iniciales pegadas: `J.K.` → `J. K.` (bucle hasta
   estabilizar, para que `J.R.R.` se resuelva en una sola pasada).
4. Añade espacio entre una inicial con punto y el apellido pegado:
   `J.Rowling` → `J. Rowling`.
5. Añade el punto que falte a una inicial suelta: `"J K Rowling"` →
   `"J. K. Rowling"`.

Escritura directa (sin CompareMany): compara autor por autor y solo escribe
si `new_authors != old_authors`.

---

## 6. Fix identifiers

`fix_identifiers.py`, reglas aplicadas en este orden sobre el dict de
identificadores de cada libro:

1. `asin`/`mobi-asin` → se copian a `amazon` (si `amazon` no existe ya) y se
   eliminan.
2. Variantes regionales `amazon_ca`/`amazon_es`/`amazon_uk` → igual, se
   funden en `amazon` (aplicado ANTES de las reglas de UUID/key==value para
   no perder el valor).
3. Claves o valores con forma de UUID → eliminados.
4. Entradas `clave == valor` (típico de una importación mal hecha) → se
   renombran a `isbn:valor` (o se descartan como duplicado si `isbn` ya
   existe).
5. `amazon` con un valor que no es un ASIN válido (10 alfanuméricos) → se
   elimina.
6. Variantes mal formadas de ISBN (`isbn-13`, `isbn 10`, `isbn0310861691`,
   `urn:isbn:...`) → normalizadas a la clave `isbn`. Si el propio nombre de
   la clave lleva los dígitos embebidos (`isbn0310861691`), se usan esos
   dígitos como valor en vez de fiarse del valor almacenado.

Lectura y escritura en bloque (una sola consulta/transacción para todos los
`book_ids`, no libro a libro) por rendimiento en bibliotecas grandes.
Escritura directa, sin CompareMany. **Deliberadamente fuera de Fix all**: es
un cambio mecánico/determinista sin ambigüedad real, meterlo en la revisión
interactiva solo añadiría clics de "Next" sin aportar criterio humano.

---

## 7. Check comments

`fix_comments.py`, análisis de la sinopsis (`comments`, almacenado como
HTML) sin modificarla nunca — solo la marca. `strip_html()` la convierte a
texto plano (con manejo de saltos de bloque/`<br>` para conservar la
segmentación en líneas) y `analyze_comment()` detecta:

| Código | Cuándo |
|---|---|
| `vacio` | Sin texto útil tras quitar el HTML |
| `corto` | Por debajo de `MIN_CHARS=200` caracteres o `MIN_WORDS=30` palabras |
| `largo` | Por encima de `MAX_CHARS=5000` caracteres |
| `repetido` | Una frase/párrafo de ≥40 caracteres (`_SEGMENT_MIN`) aparece 2+ veces, o el texto completo está pegado dos veces seguidas |
| `basura` | Frases de relleno (`"sinopsis no disponible"`…), marcas de agua de sitios de descarga, URLs, mojibake (codificación rota), **o** secciones añadidas tipo "Sobre el autor"/"Reseñas"/"Extracto" detectadas como líneas cortas tipo encabezado — el HTML en sí NUNCA cuenta como basura por llevar formato |

Detalle importante: si se detecta una sección añadida (About the
Author/Praise/Reviews/Excerpt) y hay ≥20 caracteres de sinopsis real antes de
esa sección, los umbrales `corto`/`largo` se calculan SOLO sobre el texto
anterior al corte (la sinopsis real), no sobre el comentario completo con la
sección pegada.

`duplicate_fingerprint()` existe en el módulo para detectar sinopsis
idénticas entre libros distintos, **pero `check_comments_action` en
`action.py` NO la usa actualmente** — el docstring de la acción dice
explícitamente que los duplicados cruzados no se marcan porque tener el
mismo libro dos veces en la biblioteca es normal y esperado. Si en el futuro
se quiere activar esa detección, la función ya existe y solo falta cablearla
en la acción.

No escribe nada en el libro: solo `marks` (`revisar_comentario` +
`comentario_<código>` por cada problema encontrado), consultable con
`marks:revisar_comentario` o por tipo (`marks:comentario_corto`, etc.).

---

## 8. Fix tags

`fix_tags.py` + `tags_map.json` (`{"rules": {"Grupo · Valor": "regex"},
"drop": ["hoja_normalizada", ...]}`). Para cada libro:

1. Reúne la unión de `tags` + `#clasificacion` + `#subjects` (si esas
   columnas existen).
2. Clasifica cada tag (`classify_tag`): si ya está en forma canónica
   (contiene ` · `) se conserva tal cual; si su hoja normalizada está en
   `drop`, se descarta; si no, se prueba cada regla EN ORDEN (la primera que
   matchea gana) primero contra la hoja (último segmento tras partir por
   `.`), y si no matchea nada y la tag es un prefijo estructural
   (`_Biblioteca.`/`_Libreria.`) o la hoja sola perdió contexto, se reintenta
   contra la ruta completa. Sin match → se conserva la tag tal cual y se
   marca "sin mapear".
3. El resultado sustituye por completo el campo `tags` del libro (no se
   pierde información: lo desconocido se conserva, solo se pierden los
   duplicados y lo que está en `drop`).
4. Si `#subjects` existe y tenía contenido, se vacía tras la consolidación
   (su contenido ya se fundió en `tags`). `#clasificacion` se lee pero
   **nunca se toca** — es propiedad del Book Classifier.

**Aplicación directa, sin CompareMany** (a pesar de que el tooltip del menú
dice "review before saving" — en el código actual no hay diálogo de
revisión para esta acción; el cambio se escribe de inmediato). Los libros
que se quedan con alguna tag "sin mapear" se marcan `revisar_tags`.

---

## 9. Compare with file metadata (OPF vs calibre)

`opf_compare.py` + `matching.py` (añadidos el 2026-07-18). Lee el
título/autor/serie/idioma **embebidos en el propio fichero** del libro (el
OPF interno de un EPUB, o los metadatos de AZW3/MOBI/AZW/KEPUB —
`PREFERRED_FORMATS`, en ese orden de preferencia) y los compara con lo que
Calibre tiene ahora mismo, reutilizando el mismo método de decisión "seguro
vs dudoso" que usa Smart Metadata:

- **Título**: similitud difusa (`SequenceMatcher`, directa + insensible al
  orden de palabras) sobre el título normalizado completo; además hay un
  atajo comparando solo la cabecera antes de `:` cuando ambos títulos tienen
  longitud comparable (no se fía de un título corto que solo casa con la
  cabecera de otro mucho más largo — evita falsos "coincide" con una edición
  con subtítulo extenso).
- **Autor**: mejor coincidencia por pares entre las listas de autores,
  usando `token_sort_ratio` (ignora el orden de palabras, así "Apellido,
  Nombre" casa con "Nombre Apellido").
- **Serie**: comparación normalizada de nombre; si el nombre coincide pero
  el índice difiere, también cuenta como diferencia.
- **Idioma**: solo se marca conflicto si AMBOS lados declaran idioma y no
  comparten ninguno (`'und'`/indeterminado se ignora); la ausencia de idioma
  en un lado nunca es, por sí sola, un conflicto.
- Umbrales por defecto (iguales a Smart Metadata): título 90%, autor 80%,
  autor obligatorio (`REQUIRE_AUTHOR=True`).
- Libros donde el fichero y Calibre ya coinciden en todo se omiten
  directamente (no aparecen en la revisión). Si el book no tiene ningún
  formato legible, se cuenta aparte (`no_file`) y se informa al final.
- Revisión vía CompareMany (campos `title`, `authors`, `series`,
  `languages`); el fichero sobrescribe a Calibre solo en los libros
  aceptados, campo a campo (los que no difieren no se tocan).

---

## 10. Campos personalizados usados

| Columna | Tipo | Acción que la usa | Comportamiento |
|---|---|---|---|
| `#generator` | Texto | Extraer metadatos | Solo escribe si el fichero aporta valor |
| `#book_producer` | Texto | Extraer metadatos | Solo escribe si el fichero aporta valor |
| `#title_opf` | Texto | Extraer metadatos, Fix all | Guarda el título original antes de limpiarlo, si está vacío; también sirve de última fuente para resolver `#world` |
| `#subjects` | Texto | Extraer metadatos, Fix tags | Fix tags la vacía tras fundirla en `tags` |
| `#subtitle` | **Texto** (no "Long text/comments" — ver §2) | Extraer metadatos, Fix all | Nunca sobrescribe si ya tiene valor; Fix all la rellena vía CompareMany |
| `#serie_gen` | **Texto** (no "Long text/comments" — ver §2) | Fix all (vía CompareMany) | v1.7.6. Universo/imprint/sub-serie SIN número, detectado por `find_generic_series_in_title()` en un paréntesis final; distinto de `series` (que siempre lleva índice). Se propone siempre que se detecta, igual que serie/idioma/subtítulo (sin regla de "nunca sobrescribir") |
| `#world` | Texto | Fix all (vía CompareMany) | Nunca sobrescribe un valor existente; serie de búsqueda: `series` guardada → serie detectada en el título → serie detectada en `#title_opf` |
| `#clasificacion` | — | Fix tags (solo lectura) | Se lee como fuente pero nunca se modifica — es del Book Classifier |

---

## 11. Limitaciones conocidas y decisiones deliberadas

- El patrón de "escritura directa sin revisión" en Fix author / Fix
  identifiers / Fix tags es deliberado: son transformaciones deterministas y
  de bajo riesgo (no hay ambigüedad real que un humano deba arbitrar).
  `#world` SÍ pasa por CompareMany desde v1.7.1 (junto con
  serie/idioma/subtítulo) porque, al no existir ya un menú "Fix universe"
  aparte, el diálogo de Fix all es el único sitio donde se puede ver/
  corregir antes de guardar.
- Desde v1.7.3, Fix all ya NO enseña todos los libros seleccionados sin
  distinción (eso era la decisión original al fusionar las acciones, pero
  en la práctica generaba demasiadas filas sin ningún cambio real que
  revisar) — solo entran al CompareMany los libros donde al menos un campo
  difiere de verdad. El motivo del cambio de rumbo, documentado por si se
  reconsidera en el futuro: mostrarlo todo tenía sentido cuando `#world` se
  escribía aparte y automáticamente, pero al plegar también serie/idioma/
  subtítulo en "propón siempre, decide el humano" (mismo v1.7.3), la lista
  de libros con algo que decidir de verdad creció lo suficiente como para
  que las filas sin cambios fueran solo ruido.
- `fix_comments` nunca reescribe la sinopsis — no hay forma automática de
  "arreglar" un texto de mala calidad sin generar contenido nuevo, así que
  el plugin se limita a señalar.
- El emparejamiento de series por título es heurístico (~20 patrones
  regex); un formato de título no cubierto por ninguno de los patrones A-T
  simplemente no se detecta, no genera un falso positivo.
- `world_map.json` y `tags_map.json` son datos curados a mano; una serie o
  tag nueva no aparece hasta que se añade al mapa correspondiente. `#world`
  SOLO puede resolver universos que ya están en el mapa — no hay (todavía)
  detección de universo directamente desde el texto del título cuando la
  serie tampoco está en el mapa.
- El campo `#clasificacion` es tierra de nadie para `fix_metadata`: se lee
  pero no se escribe, porque pertenece al Book Classifier — si algún día se
  quiere que `fix_metadata` también lo actualice, es un cambio de diseño
  explícito, no un descuido.
- CompareMany es un widget nativo de calibre (`gui2/metadata/diff.py`), no
  del plugin: su tamaño de ventana por defecto y qué editor usa por campo
  (texto de una línea vs WYSIWYG de comentarios) dependen de decisiones de
  calibre que `compare_review.py` solo puede mitigar parcialmente (ver §2).
