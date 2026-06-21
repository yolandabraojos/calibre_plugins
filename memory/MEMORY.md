# Memory index — Calibre Plugins

- [Repo local de plugins](calibre-plugins-repo-local.md) — el proyecto vive en C:\_Proyectos\calibre_plugins (git, 5 plugins); OneDrive queda de respaldo.
- [Corrupcion de escritura (cloud + montaje)](cloud-sync-write-corruption.md) — Write/Edit corrompen codigo aqui; usar bash + verificar, instalar desde ZIP.
- [Generador build_plugins.py](build-plugins-generator.md) — genera y verifica los ZIP maestros; excluye __pycache__/.pyc; build.cmd/verify.cmd.
- [ZIP de plugin: sin __pycache__](calibre-plugin-zip-no-pycache.md) — incluir __pycache__/.pyc rompe la carga del plugin en silencio.
- [Book Classifier retrain](book-classifier-retrain.md) — modelo IA a 8 clases sin fuga; datos L*.csv, sin autor, accuracy ~0.928 con #subjects.
- [Ebook Comparator](ebook-comparator-improvements.md) — v2.6.2; master EbookComparator.zip; fast-path binario, cache, simhash, prefiltro.
- [Plan Fix Metadata](fix-metadata-consolidation-plan.md) — fusionar extract_metadata en fix_metadata; #world por diccionario serie->universo; plan por fases.
