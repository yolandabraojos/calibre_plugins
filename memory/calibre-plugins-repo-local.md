---
name: calibre-plugins-repo-local
description: El proyecto de plugins de Calibre vive en C:\_Proyectos\calibre_plugins (repo git local, 5 plugins); OneDrive queda de respaldo.
metadata:
  node_type: memory
  type: project
---

Desde 2026-06-21 el proyecto de plugins de Calibre vive en el repo git LOCAL
`C:\_Proyectos\calibre_plugins` (rama main, remoto origin). Se movio desde la carpeta
OneDrive `Documentos\Claude\Projects\Calibre - Clasificacion` para evitar la corrupcion
de sincronizacion. La copia de OneDrive se dejo INTACTA como respaldo (contiene ademas
los datos de entrenamiento: `biblioteca/`, xlsx de pesos del modelo, csv, tests).

**5 plugins** (cada carpeta con marcador `plugin-import-name-*.txt`):
- book_classifier v3.0.0 (IA local con `model_weights.json` + `ml_classifier.py`/`ml_jobs.py`;
  sustituyo a la version pre-ML con `classifier.py`/`clasificacion_libros.json`).
- ebook_comparator v2.6.2 — ver [[ebook-comparator-improvements]].
- fix_metadata v1.3.3 — ver [[fix-metadata-consolidation-plan]].
- extract_metadata v1.3.2 (pendiente de fusion en fix_metadata segun el plan).
- all_libraries_stats v1.0.5 (solo estaba en el repo, no en OneDrive; se conserva).

La migracion fusiono lo nuevo de OneDrive sobre el repo (que tenia versiones antiguas),
anadio fix_metadata y conservo all_libraries_stats + el historial git.

Instrucciones del proyecto en `CLAUDE.md`. Generacion de ZIPs: [[build-plugins-generator]].
Recordar: en esta carpeta NUNCA usar Write/Edit — ver [[cloud-sync-write-corruption]].
