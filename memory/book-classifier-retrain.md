---
name: book-classifier-retrain
description: BookClassifier modelo local reentrenado a 9 clases (separa No-Ficción y Paranormal), sin fuga; cómo y con qué datos.
metadata:
  node_type: memory
  type: project
  originSessionId: 50b0c83b-6571-4a60-8d07-1bab24f786a7
---

**Estado actual (reentrenado 2026-07-14):** `book_classifier/model_weights.json` tiene **9 clases**: `['Ciencia Ficción','Fantasía','Ficción general','Misterio·Thriller·Terror','No-Ficción','Paranormal','Romance contemporáneo','Romance histórico','Romantasy']`. Respecto al reentreno anterior (2026-07-11, 7 clases sin No-Ficción y con Paranormal fusionado en Romantasy, ver historial), este añade **No-Ficción** como clase propia y **separa Paranormal de Romantasy**. Fichero de ~5,3MB, 41.993 n-gramas en idf.

**Datos:** `_datos_ejemplo/*.csv` (10 exports, ~6.274 filas leídas). Tras descartar sin `#libreria` (137), vacías/`(revisar)` (4) y fusionar duplicados (136, conflictos descartados 47): **5.950 ejemplos únicos**. Distribución: Paranormal 1556, Fantasía 1046, Romance contemp. 725, Ciencia Ficción 623, Romance histórico 576, Romantasy 540, Misterio·Thriller·Terror 465, Ficción general 381, No-Ficción 38 (clase muy pequeña, ver limitación abajo).

**FUGA (se sigue quitando igual que siempre):** del campo `tags` se excluyen SOLO las que codifican directamente la librería (`Genero`/`Biblioteca`/`Libreria` en formato `Grupo · Valor`, o prefijos crudos `_Biblioteca.`, `English.`, `Spanish.`, `Temas.`, `Themes.`, `FICTION/`). Del resto de tags canónicas que SÍ son señal (`Subgenero ·`, `Ambientacion ·`, `Tono ·`...) solo se queda el valor, no el nombre del grupo. Mismo criterio que `book_classifier/llm_jobs.py::_is_leak_tag` — si cambias uno, cambia el otro. Entrada = título + comments + tags-limpias (sin autor, sin `#subjects` para no desajustar con la inferencia del plugin).

**Precisión real verificada 2026-07-15 (holdout 20%, sin fuga, re-ejecutando `scripts/train_book_classifier.py` sobre los datos actuales): accuracy 0.789, macro-F1 0.725.** Por clase: Ciencia Ficción f1 0.80, Fantasía 0.74, Ficción general 0.67, Misterio·Thriller·Terror 0.76, **No-Ficción f1 0.22 (recall 0.12 — solo 8 ejemplos en el holdout, clase demasiado pequeña, predice mal)**, Paranormal 0.81, Romance contemporáneo 0.83, Romance histórico 0.89, Romantasy 0.80. Vocabulario del holdout: 16.364 n-gramas (min_df=10); el modelo final (con TODOS los ejemplos, el que se exporta) usa 20.165 features.

**Pipeline (reproduce inferencia exacta del plugin):** `normalize` idéntico a `ml_classifier.py`, `TfidfVectorizer(preprocessor=normalize, tokenizer=str.split, token_pattern=None, lowercase=False, ngram_range=(1,2), min_df=10, sublinear_tf=True, norm='l2')` (holdout usa además `max_df=0.4` para limpiar artículos/verbos ultra-comunes, no afecta a `ml_classifier.py`) + `LogisticRegression(C=3, class_weight='balanced', multinomial, max_iter=3000)`. Export: classes(=clf.classes_), idf{ngram}, coef{ngram:[por clase, alineado a classes]}, intercept, sublinear_tf, norm, ngram. El script vive ahora EN el repo: `scripts/train_book_classifier.py` (antes vivía en sandbox `/tmp/train`, fuera del repo). Uso: `python3 scripts/train_book_classifier.py [--datos RUTA] [--out RUTA] [--min-df N] [--max-df F]`; nunca sobreescribe `model_weights.json` de producción automáticamente (escribe a `model_weights_new.json`). Tests: `tests/test_train_book_classifier.py` (normalize, is_leak_tag, build_examples + entrenamiento sintético). Documentación completa en `scripts/README.md`.

**Limitación conocida:** No-Ficción con solo 38 ejemplos (8 en holdout) predice mal — hace falta más `#libreria` resuelta por el rescate LLM antes de fiarse de esa clase. El script avisa con "AVISO: CERO ejemplos" o "POCOS EJEMPLOS" si una librería queda corta; revisar esa salida antes de decidir si copiar `model_weights_new.json` sobre producción.

Empaquetado según [[calibre-plugin-zip-no-pycache]] y [[cloud-sync-write-corruption]]; JSON copiado con cp/bash (no Write) y ZIP verificado ÍNTEGRO con `verificar_plugin.py`/`build_plugins.py`.
