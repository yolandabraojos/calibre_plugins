---
name: ebook-comparator-improvements
description: ebook_comparator plugin v2.6.2 — master EbookComparator.zip; fast-path binario, cache, simhash, normalizacion, prefiltro.
metadata:
  node_type: memory
  type: project
---

El plugin `ebook_comparator` esta en **v2.6.2** (en el repo local tras la migracion
de 2026-06-21; OneDrive tenia 2.6.0/2.6.2 en iteracion). Su ZIP maestro es
`dist/EbookComparator.zip`; instalar siempre desde un ZIP que el
verificador marque INTEGRO — ver [[cloud-sync-write-corruption]].

Mejoras para acelerar/afinar la deteccion de libros iguales:
- **Fast-path binario** (`jobs._binary_identical`): compara tamano y luego SHA-1;
  identicos -> 100% sin extraer el EPUB.
- **Cache de extraccion** por (path, mtime, size) en `extractor.py` + extraccion
  de A/B en paralelo (`_extract_pair_parallel`).
- **SimHash** con Counter+blake2b y `hamming` con `int.bit_count()`.
- **book_fingerprint** (huella independiente del orden) para agrupar copias jacket-only.
- **Normalizacion de titulo/autor** en `scan_pairs_sync` (quita articulos, ordena
  tokens de autor) -> mas recall.
- **Prefiltro de longitud** en `compare_books` (ratio < 0.15 -> disjunto sin matriz).

Nota: el paralelismo real por procesos NO es viable en plugins Calibre (los workers
no pueden importar `calibre_plugins.*`); por eso se usa paralelismo de E/S con hilos.
