---
name: ebook-comparator-improvements
description: ebook_comparator plugin v2.7.1 — master zip EbookComparator.zip; binary/jacket dedup design; emparejamiento difuso título/autor + subtítulos.
metadata:
  node_type: memory
  type: project
  originSessionId: e805d1f2-dc7a-4dad-8b60-7cd68847a1f4
---

El plugin `ebook_comparator` está en v2.7.1 (2026-07-12). Su ZIP maestro es `dist/EbookComparator.zip` en la raíz del proyecto; instalar siempre desde un ZIP que `verificar_plugin.py` marque ÍNTEGRO — ver [[cloud-sync-write-corruption]].

Mejoras añadidas para acelerar/afinar la detección de libros iguales:
- **Fast-path binario** (`jobs._binary_identical`): compara tamaño y luego SHA-1 del fichero; idénticos → 100% sin extraer EPUB.
- **Caché de extracción** por (path, mtime, size) en `extractor.py` + extracción de A/B en paralelo (`_extract_pair_parallel`).
- **SimHash** con Counter+blake2b y `hamming` con `int.bit_count()`.
- **book_fingerprint** (huella de libro independiente del orden) para agrupar copias jacket-only.
- **Prefiltro de longitud** en `compare_books` (ratio < 0.15 → resultado disjunto sin matriz).

**v2.7.0 — emparejamiento difuso en `scan_pairs_sync` (jobs.py):** antes agrupaba por clave EXACTA `(título, autor, idioma)` tras normalizar; ahora genera un par candidato si el idioma es exacto, el título normalizado tiene similitud `SequenceMatcher.ratio() >= TITLE_FUZZY_THRESHOLD` (0.85), y algún autor de cada lado tiene similitud `>= AUTHOR_FUZZY_THRESHOLD` (0.5). La similitud de autor usa **coeficiente de solape** (`tokens compartidos / min(len_a, len_b)`), NO Jaccard sobre la unión — así "Tolkien" vs "J.R.R. Tolkien" da 1.0 en vez de 0.33. Para evitar O(n²), dentro de cada idioma los libros se ordenan por título normalizado y cada uno solo se compara con los `NEIGHBORHOOD_WINDOW` (40) siguientes ("sorted neighborhood"); limitación: una errata en la primera palabra del título puede dejar el par sin comparar. Documentado en `ebook_comparator/COMPORTAMIENTO_PLUGIN.md` §6-8.

**v2.7.1 — subtítulos/marcas de edición en `_normalize_title`:** antes de quitar puntuación general, ahora (a) descarta contenido entre paréntesis/corchetes ("(Edición ilustrada)", "[Tomo 1]") y (b) corta el título en el primer `:` descartando lo que sigue (subtítulo). Así "Título: Edición ilustrada" y "Título (Edición ilustrada)" normalizan igual que "Título". Efecto colateral aceptado: libros de una misma saga con prefijo común antes de `:` (p. ej. "Star Wars: Episodio IV" vs "Episodio V") generan un par candidato que se descarta en la comparación de CONTENIDO, no en el agrupamiento. Sigue sin detectar subtítulo pegado SIN separador ("Título Edición Ilustrada" sin `:` ni paréntesis) — no se abordó, sería un blocklist de palabras de edición, más frágil.

Nota: paralelismo real por procesos NO es viable en plugins Calibre (los workers no pueden importar `calibre_plugins.*`); por eso se usó paralelismo de E/S con hilos.
