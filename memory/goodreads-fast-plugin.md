---
name: goodreads-fast-plugin
description: Plugin propio GoodreadsFast (fuente de metadatos calibre) que busca por autocomplete y raspa estanterías para tags
metadata:
  node_type: memory
  type: project
  originSessionId: ddbc4997-64b9-46bc-863c-d4f8b9f6bb2e
---

Plugin de fuente de metadatos "Goodreads Fast" (import name `goodreads_fast`, clase `GoodreadsFast(Source)`), creado en jul-2026 porque el plugin Goodreads de kiwidude falla al buscar sin ISBN: su `create_query` usa la API retirada `search/search.xml?key=...`.

Diseño clave (verificado en vivo con Chrome/web_fetch):
- Búsqueda por el endpoint vivo `book/auto_complete?format=json&q=` con texto libre (título+primer autor; reintento solo título; ISBN si existe). Acepta títulos en español y devuelve la edición en ese idioma → respeta el idioma del libro.
- Detalles vía `/book/show/{id}.xml` (truco `.xml` esquiva el AWS WAF) parseando `__NEXT_DATA__`/apolloState. Reutiliza el worker de kiwidude adaptado sin config.
- Tags: raspa `/book/shelves/{id}` (estructura legacy `shelfStat`/`actionLinkLite`/`smallText` SIGUE VIVA en navegador real; web_fetch la ve vacía porque quita scripts) con conteos, mapea shelf→tag y doble umbral (idea de "Goodreads More Tags"); une con `bookGenres` y aplica TAG_BLOCKLIST (audiobook, book club, to-read...).
- Robustez de búsqueda de títulos (v1.6.0): `_deparen_inline` conserva paréntesis pegados a palabra sin dígitos ("(Un)Lucky"→"UnLucky") y elimina los de serie (con #/dígitos); `_clean_query_title` quita apóstrofos pegando; `_title_cores` genera variantes cabeza/cola/completo partiendo por ":" y " - " (para títulos con serie delante como "Fate of Wizardoms - Wizardoms: Rise of a Wizard Queen"); autor con `get_author_tokens` (descarta iniciales tipo "L. G."). Scoring usa TODOS los tokens del título (strip_subtitle=False) para que subtítulos distintivos cuenten (dos libros con misma base y distinto subtítulo se distinguen; además workId distinto evita agruparlos); bonus de match exacto sobre la cabeza; `MIN_MATCH_SCORE=4.0` descarta coincidencias malas (cajas/omnibus) para pasar a la siguiente variante.
- Scoring `_rank_candidates`: exige autor, premia match exacto de título, penaliza -6 por desajuste de número/ordinal (arregla que "Part Two" eligiera "Part One"). Los números se sacan del título CRUDO con regex, no de `get_title_tokens` (que borra el texto entre paréntesis, p.ej. "(Part Two)").
- Estanterías con timeout corto `SHELF_TIMEOUT=8` porque una petición colgada llegó a tardar 23 s; si fallan, cae a `bookGenres`.
- Selección por edición (v1.3.0): ediciones duplicadas del mismo libro comparten stats de ratings a nivel work (mismo rc/avg), así que el desempate por valoraciones no las distingue. `_edition_group` agrupa ediciones, descarga hasta 3 e `identify` emite la de sinopsis (`comments`) más larga primero (desempate portada); emite todas para elegir en modo individual. NO decidir por nº valoraciones (rompería casos donde la edición con mejor contenido tiene menos/iguales votos).
- Expansión ISBN (v1.4.0): antes, si el libro tenía ISBN, se resolvía la edición EXACTA por ISBN y se saltaba la selección por sinopsis (caso Red Tide: Kindle 9781466831223→id 29368572 con sinopsis de 99 car., en vez de la paperback 31866364 con 1472). Ahora el ISBN fija el libro pero además se busca por título/autor y se agrupan las ediciones hermanas por `workId` (que el autocomplete devuelve) exigiendo mismo título normalizado+números (para no cruzar idioma ni bundles). `_same_book` decide; `_search_ids` junta pool ISBN+título. Efecto colateral: el ISBN aplicado puede cambiar al de la edición ganadora.

Ojo: en el log de calibre el Rating sale a la MITAD (p.ej. 2.1 en vez de 4.23) porque `Metadata.__unicode__representation__` hace `rating/2` al imprimir (escala interna 0-10). El valor guardado es correcto; NO doblar.

**Migrado al repo git el 2026-07-15:** fuentes en `goodreads_fast/` (raíz del repo, antes solo existía como ZIP), añadido a la tabla de `CLAUDE.md`. Master fiable: `dist/GoodreadsFast.zip` (v1.6.0), reconstruido con `build_plugins.py` y verificado ÍNTEGRO. Relacionado: [[cloud-sync-write-corruption]], [[calibre-plugin-zip-no-pycache]].
