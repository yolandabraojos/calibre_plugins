# Scripts (línea de comandos, fuera de Calibre)

Herramientas que se ejecutan con Python normal (no el embebido de Calibre),
desde la raíz del repo o desde esta carpeta.

## `train_book_classifier.py` — reentrenar el modelo local (eje 1: librería)

### Requisitos

```bash
pip install scikit-learn --break-system-packages   # o tu venv habitual
```

### Uso básico

```bash
python3 scripts/train_book_classifier.py
```

Por defecto:

- Lee **todos** los `.csv` de `_datos_ejemplo/` (en la raíz del repo), sea
  cual sea su nombre. Los que no tengan columna `#libreria` (exports que aún
  no han pasado por el rescate con IA) se listan pero se ignoran.
- Escribe el modelo en `book_classifier/model_weights_new.json` — **nunca**
  sobreescribe el `model_weights.json` de producción automáticamente.

### Opciones

| Flag | Por defecto | Qué hace |
|---|---|---|
| `--datos RUTA` | `_datos_ejemplo/` | Carpeta con los `.csv` exportados de Calibre |
| `--out RUTA` | `book_classifier/model_weights_new.json` | Fichero de salida |
| `--min-per-class N` | `20` | Umbral solo para el AVISO de "pocos ejemplos" (no excluye nada) |
| `--min-df N` | `10` | `min_df` del `TfidfVectorizer`; bájalo si el dataset es pequeño |
| `--max-df F` | `0.4` | Descarta n-gramas que aparecen en más de ese % de libros (artículos/verbos genéricos en cualquier idioma, sin lista de stopwords a mano) |
| `--test-size F` | `0.2` | Proporción del holdout de evaluación |
| `--seed N` | `42` | Semilla del split train/test |

### Qué hace con los datos

1. Junta todas las filas de los `.csv` que tengan columna `#libreria`.
2. Descarta filas sin `#libreria`, vacías o en `(revisar)`/variantes.
3. Deduplica por (título, autor) normalizado — se queda con la copia de
   sinopsis más larga; si el mismo libro aparece con librerías distintas en
   dos ficheros (conflicto), descarta el grupo entero.
4. Construye el texto de entrada: **título + comentarios + tags limpias**
   (sin autor, sin `#subjects`). "Tags limpias" excluye SOLO las que
   codifican directamente la librería: grupo `Genero`/`Biblioteca`/`Libreria`
   en formato canónico `Grupo · Valor` (el que genera Fix Metadata), o los
   prefijos en crudo pre-Fix Metadata (`_Biblioteca.`, `English.`, `Spanish.`,
   `Temas.`, `Themes.`, `FICTION/`). Del resto de tags canónicas
   (`Subgenero ·`, `Ambientacion ·`, `Tono ·`, `Dinamica ·`, `Arquetipo ·`,
   `Paranormal ·`...), que SÍ se usan como señal, solo se queda el **valor**
   (`tag_value`): el nombre del grupo no es contenido del libro, es la
   etiqueta de la faceta, y dejarlo colaba `tono`/`dinamica`/`subgenero` como
   palabras sueltas en 40-47% de los libros sin aportar nada. Mismo criterio
   de fuga que `book_classifier/llm_jobs.py::_is_leak_tag` — si cambias uno,
   cambia el otro.
5. Entrena `TfidfVectorizer` + `LogisticRegression` con los mismos
   hiperparámetros que usa `book_classifier/ml_classifier.py` para inferir
   (más `max_df` para limpiar artículos/verbos ultra-comunes, que solo afecta
   al vocabulario exportado y no requiere tocar `ml_classifier.py`), evalúa
   contra un holdout del 20% y muestra accuracy, macro-F1 y el informe por
   librería.
6. Reentrena con TODO el dataset (sin holdout) y exporta el modelo final.

**Límite conocido de `max_df`:** es un umbral GLOBAL de frecuencia documental,
no por idioma. En una biblioteca mayoritariamente en inglés, artículos en
español (`de`, `la`, `el`) pueden seguir dentro del vocabulario porque su
frecuencia global (solo dentro del subconjunto en español) no llega al 40%,
aunque dentro de ese subconjunto sean omnipresentes. Si esto te importa, baja
`--max-df` (con cuidado: un umbral muy agresivo puede tirar señal real) o
pasa a una lista de stopwords bilingüe explícita.

### Fidelidad con el plugin (no tocar sin sincronizar)

| Pieza | Debe coincidir con |
|---|---|
| `normalize()` | `book_classifier/ml_classifier.py::normalize` |
| Filtro de fuga de tags | `book_classifier/llm_jobs.py::_is_leak_tag` |
| Lista de librerías esperadas | `book_classifier/llm_rescue_engine.py::LIBRERIAS` y `scripts/llm_rescue.py::LIBRERIAS` |
| Esquema del JSON exportado (`classes`, `idf`, `coef`, `intercept`, `sublinear_tf`, `norm`, `ngram`) | lo que carga `book_classifier/ml_classifier.py::MLClassifier.__init__` |

### Tests

`tests/test_train_book_classifier.py` cubre `normalize`, `is_leak_tag` y `build_examples`, y (si tienes scikit-learn) entrena sobre un dataset sintético para comprobar que el pipeline realmente acierta y que el modelo exportado carga bien en `ml_classifier.MLClassifier`. Correrlo antes de tocar este script:

```bash
python3 -m unittest tests.test_train_book_classifier -v
```

### Leer la salida antes de decidir nada

El script avisa de dos cosas a las que hay que prestar atención:

- **`AVISO: CERO ejemplos de estas librerías`** — esas clases nunca se van a
  poder predecir con este dataset; hace falta más `#libreria` resuelta por el
  rescate con IA antes de reentrenar en serio.
- **`<-- POCOS EJEMPLOS`** en la distribución — clases con menos ejemplos que
  `--min-per-class`; sus métricas en el informe no son de fiar.

### Promover el modelo a producción

El script **no** toca `book_classifier/model_weights.json`. Cuando las
métricas te convenzan:

```bash
cp book_classifier/model_weights_new.json book_classifier/model_weights.json   # bash, NUNCA Write/Edit
python3 verificar_plugin.py
python3 build_plugins.py book_classifier
```

Confirma "ÍNTEGRO" en ambos pasos antes de instalar el ZIP en Calibre.

## Otros scripts de esta carpeta

- **`llm_rescue.py`** — versión de línea de comandos del rescate con IA
  (mismo motor que `book_classifier/llm_rescue_engine.py`, para correrlo
  sobre un CSV sin abrir Calibre).
  `python3 scripts/llm_rescue.py --diag --provider deepseek` prueba la
  conexión; `--dry-run` muestra el prompt sin llamar a la API.
- **`Rescatar_con_IA.bat`** — lanzador de doble clic para `llm_rescue.py` con
  el proveedor GLM/z.ai (pide la clave por teclado, ofrece modo prueba de 30
  libros o biblioteca completa).
