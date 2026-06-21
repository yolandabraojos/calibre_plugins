---
name: book-classifier-retrain
description: BookClassifier modelo reentrenado a 8 clases sin fuga; cómo y con qué datos.
metadata: 
  node_type: memory
  type: project
  originSessionId: 50b0c83b-6571-4a60-8d07-1bab24f786a7
---

El modelo de Book Classifier (`model_weights.json`) se reentrenó el 2026-06-13 desde cero (antes tenía 6 clases con fuga de etiquetas: los tags `Idioma.Genero.*` tipo `English.Fantasy.*` metían el género en la entrada).

**Datos:** los `biblioteca/L*.csv` (una librería por fichero). **8 clases:** Ciencia ficción, Fantasía, Ficción general, Terror, Misterio·Thriller, Romance contemporáneo, Romance histórico, Romantasy / Paranormal (antes Fantasía y Sci-Fi iban juntas y Terror dentro de Misterio).

**Limpieza anti-fuga (versión conservadora final):** entrada = título + #subtitle + comments + series + #world + tags depurados. **Sin autor.** Del campo `tags`: se conservan `Themes.*` y `Temas.*` (EN+ES) y se "rescatan" subgéneros de CONTENIDO por palabra contenida (vampires, cozy mystery, urban fantasy, space opera, witches, shapeshifters, gothic, litrpg…); se descartan basura (`Find…`, `Catalog`, `Revisar`, `Traducción`) y la etiqueta-label de género (`Idioma.Genero.*`, códigos de biblioteca, `Biblioteca:/Tema:`). **Términos casi-etiqueta (`paranormal`, `historical`, género puro) se excluyen del RESCATE de tags pero siguen aprendiéndose del subtítulo/sinopsis** si aparecen ahí (ahí no se filtran). Solo se filtra `tags`, no el resto de campos.

**Pipeline (reproduce la inferencia del plugin):** `normalize` idéntico, analizador unigramas+bigramas adyacentes, `TfidfVectorizer(sublinear_tf=True, norm='l2')`, `LogisticRegression(C=4, class_weight='balanced', multinomial)`. Export: classes, idf{ngram}, coef{ngram:[por clase]}, intercept.

**Filtros adicionales aplicados (iteraciones posteriores):** (1) fuera stopwords EN+ES (filtradas en el analizador; bigramas solo entre no-stopwords → compatible con inferencia); (2) fuera nombres propios: un término debe salir en **≥2 sagas distintas** y ≥4 libros (mata annja/adelice/animorphs; conserva contenido); (3) campo `series` excluido de la entrada (era fuente de nombres de saga); (4) añadido `#subjects` a la entrada con limpieza por **lista negra** de género/idioma (toma el último segmento dotted, conserva contenido tipo survival/cyberpunk/post apocalyptic) — `#subjects` aporta +1.5pp. `#subtitle` casi vacío (0-4%), no se usa.

**Datos:** las L* fueron **reexportadas** (cuentas reales por csv, p.ej. Fantasía ~1206, no 4530 — wc -l contaba saltos de línea de comments). Modelo final entrenado sobre L* + **107 correcciones manuales** de las T* (revisión activa; reforzó Romance contemp. +16, Terror +7, Misterio +20). Validación held-out 20% (solo L, con subjects): **accuracy 0.928** (~14.5k n-gramas). El usuario marcó 2 libros como "Erótica" (no es de las 8 clases; pendiente decidir si crear clase). Para inferencia hay que añadir `#subjects` en "Columnas personalizadas" del plugin.

**Limitaciones conocidas:** solo ~4016 de ~13k libros tienen texto útil tras quitar la fuga (el resto son fichas solo-título sin sinopsis); Terror (16 libros) y Romance contemporáneo (43) son demasiado pequeñas y predicen mal (Terror f1≈0). Pendiente: revisar `mood_rules.json` (temas tipo cozy/fantasy cruzados en Misterio). El entrenador no vive en el repo; se generó en sandbox. Empaquetado según [[calibre-plugin-zip-no-pycache]] y [[cloud-sync-write-corruption]].
