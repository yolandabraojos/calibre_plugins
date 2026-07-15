# Memory index — Calibre Plugins

- [Repo local de plugins](calibre-plugins-repo-local.md) — el proyecto vive en C:\_Proyectos\calibre_plugins (git, 6 plugins); OneDrive queda de respaldo.
- [Corrupcion de escritura (cloud + montaje)](cloud-sync-write-corruption.md) — Write/Edit corrompen codigo aqui; usar bash + verificar, instalar desde ZIP.
- [Generador build_plugins.py](build-plugins-generator.md) — genera y verifica los ZIP maestros; excluye __pycache__/.pyc; build.cmd/verify.cmd.
- [ZIP de plugin: sin __pycache__](calibre-plugin-zip-no-pycache.md) — incluir __pycache__/.pyc rompe la carga del plugin en silencio.
- [Book Classifier retrain](book-classifier-retrain.md) — modelo IA a 9 clases sin fuga (No-Ficcion + Paranormal separado); accuracy 0.789 macro-F1 0.725 (14-jul).
- [Book Classifier hibrido LLM](book-classifier-hybrid-llm.md) — sesgo de cajon de sastre a Misterio; capa de rescate LLM llm_rescue_engine.py/llm_jobs.py.
- [Book Classifier: jobs por grupo](book-classifier-jobs-per-group.md) — v3.3.0+, un ThreadedJob por serie/universo en vez de un QThread unico bloqueante.
- [ThreadedJob callback en hilo worker](calibre-threadedjob-callback-thread.md) — el callback de ThreadedJob corre en el hilo worker; envolver con Dispatcher().
- [Ebook Comparator](ebook-comparator-improvements.md) — v2.7.1; master EbookComparator.zip; fast-path binario, cache, simhash, emparejamiento difuso.
- [Plan Fix Metadata](fix-metadata-consolidation-plan.md) — fusionar extract_metadata en fix_metadata; #world por diccionario serie->universo; plan por fases.
- [Fix comments: secciones extra](fix-comments-extra-sections.md) — About the Author/Praise/Reviews/Excerpt cuentan como basura; HTML no es basura por defecto.
- [Goodreads Fast plugin](goodreads-fast-plugin.md) — fuente de metadatos propia; busca por autocomplete (sin ISBN, respeta idioma) y raspa estanterias para tags; master GoodreadsFast.zip v1.6.0.
