---
name: calibre-plugins-repo-local
description: "El proyecto de plugins de Calibre se movió a C:\\_Proyectos\\calibre_plugins (repo git local, 6 plugins); OneDrive queda de respaldo."
metadata:
  node_type: memory
  type: project
  originSessionId: e4502bae-9144-4166-9da4-0a0d6b745a79
---

El 2026-06-21 el proyecto de plugins de Calibre se movió desde la carpeta OneDrive `Documentos\Claude\Projects\Calibre - Clasificacion` al repo git LOCAL `C:\_Proyectos\calibre_plugins` (rama main, remoto origin), para evitar la corrupción de sincronización. La copia de OneDrive se dejó INTACTA como respaldo (incluye datos de entrenamiento: biblioteca/, xlsx de pesos, csv, tests).

El destino ya era el repo git canónico pero con versiones antiguas; la migración fusionó lo nuevo de OneDrive (book_classifier v3.0.0 con IA local, ebook_comparator v2.6.2), añadió fix_metadata v1.3.3, conservó all_libraries_stats v1.0.5 (solo estaba en el repo) y extract_metadata v1.3.2, manteniendo el historial git.

**6 plugins** (desde 2026-07-15; antes 5), cada carpeta con marcador `plugin-import-name-*.txt`. El proyecto tiene `CLAUDE.md` con las reglas, `memory/` propio, y un generador `build_plugins.py` (+ build.cmd/verify.cmd) que crea y verifica los ZIP maestros `<NombreCamel>.zip` excluyendo __pycache__/.pyc.

**Aviso clave:** este montaje cowork corrompe Write/Edit (truncó build_plugins.py en una edición), no solo OneDrive — escribir SIEMPRE con bash y verificar. Ver [[cloud-sync-write-corruption]]. Modelo: [[book-classifier-retrain]]; comparador: [[ebook-comparator-improvements]]; metadata: [[fix-metadata-consolidation-plan]].

**2026-07-05:** ojo — la copia de OneDrive había DERIVADO por delante del repo git (git se quedó en 21-jun con book_classifier v3.0.0; OneDrive tenía action.py/ml_jobs.py/ml_classifier.py/config.py más nuevos). Se reconcilió: OneDrive era la base buena; se integró el rescate LLM sobre ella y se desplegó a AMBOS a book_classifier **v3.1.0**, borrando el `jobs.py` obsoleto (worker viejo pre-rename a ml_jobs.py). Git quedó con 5 modificados + 1 borrado (jobs.py) + 2 nuevos (llm_jobs.py, llm_rescue_engine.py), pendiente de commit por Yolanda. Nota mount: crear/sobrescribir sí funciona, pero BORRAR da EPERM — usar `allow_cowork_file_delete`. Ver [[book-classifier-hybrid-llm]].

**2026-07-15 (estado actual):** verificado con `git status` — el repo tiene bastante trabajo local sin commitear desde la reconciliación (book_classifier a v3.4.1, ebook_comparator a v2.7.1, fix_metadata a v1.5.9 con fix_comments.py/fix_tags.py/tags_map.json nuevos, más `scripts/` y `tests/` sin trackear). Se detectó y corrigió un plugin que solo existía como ZIP construido (`dist/GoodreadsFast.zip`) sin fuente en el repo — ver [[goodreads-fast-plugin]]; ahora migrado a `goodreads_fast/` y añadido a la tabla de `CLAUDE.md`. Los xlsx/csv de entrenamiento (Pesos_modelo_*, clasificacion_resultado.csv, biblioteca/) siguen deliberadamente solo en OneDrive como respaldo, no se versionan. `CLAUDE.md` tenía la tabla de versiones desactualizada (arrastraba las de la migración de 21-jun) — corregida para reflejar las versiones reales del `__init__.py` de cada plugin.
