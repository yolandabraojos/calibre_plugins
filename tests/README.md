# Tests

Suite de tests unitarios (`unittest` de la librería estándar) para dos
partes del repo:

- **`test_fix_metadata.py`** — módulos **puros** del plugin `fix_metadata`,
  los que solo dependen de `re`/`json` y por tanto se ejecutan sin Calibre
  instalado: `fix_author`, `fix_identifiers`, `fix_title` (incluye detección
  de series), `fix_world` y `fix_comments` (incluye detección de secciones
  extra tipo *About the Author*). Sin dependencias externas.
- **`test_train_book_classifier.py`** — `scripts/train_book_classifier.py`:
  `normalize()`, el filtro de fuga de tags (`is_leak_tag`) y `build_examples`
  (dedup, conflictos, filtrado de `(revisar)`) se comprueban sin
  dependencias; además hay dos tests que necesitan **scikit-learn** (se
  saltan solos si no está instalado) y que son los que responden a "¿el
  entrenamiento realmente acierta?":
  - `TestTrainingAccuracy` entrena sobre un dataset **sintético** de 3
    géneros con vocabulario claramente separable y exige accuracy ≥ 0.85 /
    macro-F1 ≥ 0.8. Es sintético (no usa `_datos_ejemplo/`) para que sea
    estable: los CSV reales cambian de tamaño cada vez que exportas más
    biblioteca, así que un umbral fijo contra ellos sería inestable por
    diseño, no por un fallo real.
  - `TestModelRoundTrip` entrena, exporta a JSON y comprueba que
    `book_classifier/ml_classifier.py::MLClassifier` (el motor real que
    corre dentro de Calibre) carga ese JSON y clasifica bien — detecta tanto
    roturas del esquema exportado como regresiones de accuracy.

Sirve de red de seguridad antes de cada reempaquetado del ZIP o cada cambio
en el pipeline de reentrenamiento: corre la suite antes de `build_plugins.py`
o antes de promover un `model_weights_new.json` a producción.

## Ejecutar toda la suite

Desde la raíz del repo:

```bash
python3 -m unittest discover -s tests -v
```

## Ejecutar una clase o un caso concreto

```bash
python3 -m unittest tests.test_fix_metadata.TestFixAuthor -v
python3 -m unittest tests.test_fix_metadata.TestFixAuthor.test_reverse_last_first -v
```

## Añadir tests nuevos

- Los módulos bajo test se importan directamente desde `fix_metadata/`
  (`tests/test_fix_metadata.py` añade esa carpeta a `sys.path`), así que no
  hace falta instalar el plugin en Calibre para probarlo.
- Si el módulo nuevo depende de Calibre (`from calibre...`), no encaja en
  esta suite tal cual: hay que envolver esa dependencia o mockearla primero.
- Convención de nombres: una clase `TestNombreDeLaFuncion` por función/caso de
  uso, con métodos `test_<qué_comprueba>` cortos y descriptivos (ver
  `tests/test_fix_metadata.py` para el estilo).
