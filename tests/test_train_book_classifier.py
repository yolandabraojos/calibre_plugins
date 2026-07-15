# -*- coding: utf-8 -*-
"""
Tests para scripts/train_book_classifier.py.

Tres niveles:
  1. Funciones puras (normalize, is_leak_tag, build_examples): rapidas, sin
     dependencias, corren siempre.
  2. Accuracy minima del pipeline sobre un dataset SINTETICO de control (3
     generos con vocabulario claramente distinto): si esto falla, algo se ha
     roto de verdad en normalize/min_df/vectorizador/clasificador -- no
     depende de _datos_ejemplo (que cambia de tamano cada vez que se exporta
     mas biblioteca), asi que es estable y reproducible.
  3. Round-trip completo: entrena -> exporta a JSON -> lo carga
     book_classifier/ml_classifier.py::MLClassifier (el motor real que corre
     dentro de Calibre) -> clasifica -> comprueba que acierta. Comprueba a la
     vez que el JSON exportado es valido (ver el bug de np.str_ ya corregido)
     y que el esquema encaja con lo que espera el plugin.

Los niveles 2 y 3 necesitan scikit-learn; se SALTAN (no fallan) si no esta
instalado, igual que haria un entorno sin `pip install scikit-learn`.

Uso:
    python3 -m unittest discover -s tests -v
"""
from __future__ import unicode_literals
import itertools
import json
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS_DIR = os.path.join(_HERE, '..', 'scripts')
_PLUGIN_DIR = os.path.join(_HERE, '..', 'book_classifier')
sys.path.insert(0, _SCRIPTS_DIR)
sys.path.insert(0, _PLUGIN_DIR)

import train_book_classifier as tbc   # noqa: E402
import ml_classifier as mlc           # noqa: E402

try:
    import sklearn  # noqa: F401
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False


class TestNormalize(unittest.TestCase):

    def test_lowercases_and_strips_accents(self):
        self.assertEqual(tbc.normalize('Ficción Científica'), 'ficcion cientifica')

    def test_strips_html(self):
        self.assertEqual(tbc.normalize('<p>Hola <b>mundo</b></p>'), 'hola mundo')

    def test_collapses_whitespace(self):
        self.assertEqual(tbc.normalize('hola   \n\n  mundo'), 'hola mundo')

    def test_removes_punctuation_but_keeps_slash_and_dash(self):
        self.assertEqual(tbc.normalize('sci-fi/fantasy!!'), 'sci-fi/fantasy')

    def test_empty_input(self):
        self.assertEqual(tbc.normalize(None), '')
        self.assertEqual(tbc.normalize(''), '')

    def test_decodes_html_entities_instead_of_leaving_garbage(self):
        # Regresion concreta: &#8212; &#39; &amp; &quot; sin decodificar
        # sobrevivian como tokens sin sentido ('8212', '39', 'amp', 'quot').
        self.assertEqual(tbc.normalize('AI &amp; Robots'), 'ai robots')
        self.assertEqual(tbc.normalize('Ships&#8212;and stars'), 'ships and stars')
        self.assertEqual(tbc.normalize("World&#39;s End"), 'worlds end')
        self.assertEqual(tbc.normalize('&quot;Hello&quot;'), 'hello')

    def test_apostrophes_are_removed_not_split(self):
        # Regresion concreta: "world's" -> "world s" partia la palabra en dos
        # tokens (uno de ellos, "s" suelto, puro ruido). Ahora se une.
        self.assertEqual(tbc.normalize("world's"), 'worlds')
        self.assertEqual(tbc.normalize("don't"), 'dont')
        self.assertEqual(tbc.normalize("he’d"), 'hed')  # apostrofe tipografico


class TestNormalizeSyncWithPlugin(unittest.TestCase):
    """normalize() vive DUPLICADO en scripts/train_book_classifier.py y en
    book_classifier/ml_classifier.py (entrenamiento e inferencia tienen que
    tokenizar IGUAL o el vocabulario entrenado no coincide con lo que se
    busca al clasificar). Este test es la red de seguridad de esa duplicacion:
    si alguien edita uno y no el otro, esto falla."""

    _SAMPLES = [
        None, '', 'Ficción Científica', '<p>Hola <b>mundo</b></p>',
        "world's end", "don't stop", 'AI &amp; Robots', 'Ships&#8212;and stars',
        '&quot;Hello&quot;', 'sci-fi/fantasy!!', 'hola   \n\n  mundo',
        'he’d already gone', 'Book 3: The Return (2020)',
    ]

    def test_normalize_identical_in_both_copies(self):
        for sample in self._SAMPLES:
            self.assertEqual(
                tbc.normalize(sample), mlc.normalize(sample),
                "normalize() diverge para {!r} entre train_book_classifier.py "
                "y ml_classifier.py".format(sample))


class TestIsLeakTag(unittest.TestCase):
    """El grupo 'Genero'/'Biblioteca'/'Libreria' es fuga (repite la propia
    etiqueta); el resto de grupos canonicos de fix_metadata (Subgenero,
    Ambientacion, Tono, Dinamica, Arquetipo, Paranormal...) NO lo son -- ver
    book_classifier/llm_jobs.py::_is_leak_tag, mismo criterio."""

    def test_genero_group_is_leak(self):
        self.assertTrue(tbc.is_leak_tag('Genero · Fantasía'))
        self.assertTrue(tbc.is_leak_tag('Genero · Ciencia ficcion'))

    def test_biblioteca_libreria_group_is_leak(self):
        self.assertTrue(tbc.is_leak_tag('Biblioteca · Romance'))
        self.assertTrue(tbc.is_leak_tag('Libreria · Fantasía'))

    def test_legacy_raw_prefixes_are_leak(self):
        self.assertTrue(tbc.is_leak_tag('_Biblioteca.Fantasia.Alta fantasia'))
        self.assertTrue(tbc.is_leak_tag('Themes.AI/Sentient Machine'))
        self.assertTrue(tbc.is_leak_tag('English.Science Fiction'))
        self.assertTrue(tbc.is_leak_tag('Spanish.Romance'))
        self.assertTrue(tbc.is_leak_tag('Temas.Amor'))
        self.assertTrue(tbc.is_leak_tag('FICTION/Romance/Contemporary'))

    def test_non_genero_canonical_groups_are_not_leak(self):
        self.assertFalse(tbc.is_leak_tag('Subgenero · Distopia/Apocaliptico'))
        self.assertFalse(tbc.is_leak_tag('Ambientacion · Espacial/Space opera'))
        self.assertFalse(tbc.is_leak_tag('Tono · Angst/Drama emocional'))
        self.assertFalse(tbc.is_leak_tag('Dinamica · Why choose / Haren inverso'))
        self.assertFalse(tbc.is_leak_tag('Arquetipo · Mafia'))
        self.assertFalse(tbc.is_leak_tag('Paranormal · Vampiros'))

    def test_plain_tag_without_group_is_not_leak(self):
        self.assertFalse(tbc.is_leak_tag('Slow burn'))
        self.assertFalse(tbc.is_leak_tag(''))
        self.assertFalse(tbc.is_leak_tag(None))


class TestReadCsvDicts(unittest.TestCase):
    """Proteccion contra la corrupcion de sincronizacion en la nube: un CSV
    truncado a medias deja bytes nulos pegados al final (ver memoria
    cloud-sync-write-corruption.md). No debe tirar el entrenamiento entero."""

    def _write_tmp_csv(self, raw_bytes):
        import tempfile
        fd, path = tempfile.mkstemp(suffix='.csv')
        with os.fdopen(fd, 'wb') as f:
            f.write(raw_bytes)
        self.addCleanup(os.remove, path)
        return path

    def test_clean_csv_has_no_null_count(self):
        path = self._write_tmp_csv(
            'title,#libreria\r\nBook A,Fantasía\r\n'.encode('utf-8-sig'))
        fieldnames, rows, null_count = tbc._read_csv_dicts(path)
        self.assertEqual(null_count, 0)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['title'], 'Book A')

    def test_trailing_null_bytes_are_stripped_not_fatal(self):
        raw = 'title,#libreria\r\nBook A,Fantasía\r\n'.encode('utf-8-sig')
        raw += b'\x00' * 40
        path = self._write_tmp_csv(raw)
        fieldnames, rows, null_count = tbc._read_csv_dicts(path)
        self.assertEqual(null_count, 40)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['#libreria'], 'Fantasía')


class TestBuildExamples(unittest.TestCase):

    def test_filters_empty_and_revisar(self):
        rows = [
            {'title': 'A', 'authors': '', 'comments': '', 'tags': '', '#libreria': ''},
            {'title': 'B', 'authors': '', 'comments': '', 'tags': '', '#libreria': '(revisar)'},
        ]
        examples, diag = tbc.build_examples(rows)
        self.assertEqual(len(examples), 0)
        self.assertEqual(diag['sin_libreria'], 1)
        self.assertEqual(diag['revisar'], 1)

    def test_duplicate_same_library_merged_keeps_longest_synopsis(self):
        rows = [
            {'title': 'Dup Book', 'authors': 'A. Autor', 'comments': 'corta',
             'tags': '', '#libreria': 'Romance contemporáneo'},
            {'title': 'Dup Book', 'authors': 'A. Autor',
             'comments': 'sinopsis mucho mas larga y detallada',
             'tags': '', '#libreria': 'Romance contemporáneo'},
        ]
        examples, diag = tbc.build_examples(rows)
        self.assertEqual(len(examples), 1)
        self.assertEqual(diag['duplicados_descartados'], 1)
        self.assertIn('mucho mas larga', examples[0][0])

    def test_conflicting_library_discarded(self):
        rows = [
            {'title': 'Conflict Book', 'authors': 'B. Autor', 'comments': 'x',
             'tags': '', '#libreria': 'Fantasía'},
            {'title': 'Conflict Book', 'authors': 'B. Autor', 'comments': 'y',
             'tags': '', '#libreria': 'Ciencia Ficción'},
        ]
        examples, diag = tbc.build_examples(rows)
        self.assertEqual(len(examples), 0)
        self.assertEqual(diag['conflictos_descartados'], 2)

    def test_leak_tag_excluded_but_legit_tag_kept_in_text(self):
        rows = [{
            'title': 'Test Book',
            'authors': 'Autor Uno',
            'comments': 'Una historia con magia y dragones en un reino lejano.',
            'tags': 'Genero · Fantasía, Subgenero · Fantasia epica, Tono · Oscuro',
            '#libreria': 'Fantasía',
        }]
        examples, diag = tbc.build_examples(rows)
        self.assertEqual(len(examples), 1)
        text, label = examples[0]
        self.assertEqual(label, 'Fantasía')
        self.assertNotIn('Genero', text)
        self.assertIn('Fantasia epica', text)
        self.assertIn('Oscuro', text)
        # El NOMBRE del grupo no debe colarse como palabra suelta (regresion
        # concreta: 'tono'/'subgenero' aparecian en 40-47% de los libros sin
        # aportar señal, solo por unir 'Grupo' y 'Valor' en el mismo texto).
        self.assertNotIn('Subgenero', text)
        self.assertNotIn('Tono', text)


class TestTagValue(unittest.TestCase):

    def test_extracts_value_from_canonical_tag(self):
        self.assertEqual(tbc.tag_value('Tono · Oscuro'), 'Oscuro')
        self.assertEqual(tbc.tag_value('Subgenero · Fantasia epica'), 'Fantasia epica')
        self.assertEqual(tbc.tag_value('Dinamica · Why choose / Haren inverso'),
                          'Why choose / Haren inverso')

    def test_returns_tag_as_is_when_not_canonical(self):
        self.assertEqual(tbc.tag_value('Slow burn'), 'Slow burn')
        self.assertEqual(tbc.tag_value(''), '')
        self.assertEqual(tbc.tag_value(None), '')


# --- Dataset sintetico de control para los tests de accuracy -----------------
# Vocabulario deliberadamente separable: si el pipeline no logra distinguir
# esto, hay una regresion real (normalize, min_df, vectorizador o
# clasificador rotos), no un problema de datos reales ambiguos.
_CF_WORDS = ["nave espacial", "laser", "robot", "inteligencia artificial",
             "planeta lejano", "futuro tecnologico", "astronauta", "galaxia",
             "androide", "estacion espacial"]
_FANTASY_WORDS = ["magia antigua", "hechicero poderoso", "dragon feroz",
                  "espada magica", "elfo del bosque", "reino encantado",
                  "profecia oculta", "criatura magica", "varita ancestral",
                  "pocion misteriosa"]
_ROMANCE_WORDS = ["amor a primera vista", "boda sonada", "cita romantica",
                  "corazon roto", "pareja enamorada", "beso bajo la lluvia",
                  "relacion secreta", "ciudad moderna", "oficina de la empresa",
                  "carta de amor"]


def _make_docs(words, label, title_prefix):
    docs = []
    for i, (a, b) in enumerate(itertools.combinations(words, 2)):
        title = "{} {}".format(title_prefix, i)
        text = "{}: una historia sobre {} y {}.".format(title, a, b)
        docs.append((text, label))
    return docs


def _synthetic_dataset():
    docs = []
    docs += _make_docs(_CF_WORDS, "Ciencia Ficción", "Novela CF")
    docs += _make_docs(_FANTASY_WORDS, "Fantasía", "Novela Fantastica")
    docs += _make_docs(_ROMANCE_WORDS, "Romance contemporáneo", "Novela Romantica")
    texts = [t for t, _ in docs]
    labels = [l for _, l in docs]
    return texts, labels


@unittest.skipUnless(HAS_SKLEARN, "requiere scikit-learn (pip install scikit-learn --break-system-packages)")
class TestTrainingAccuracy(unittest.TestCase):
    """Comprueba el GRADO DE ACIERTO minimo del entrenamiento, no solo que el
    script no truene. Si esto falla tras un cambio, revisa normalize(),
    is_leak_tag(), min_df o los hiperparametros del clasificador."""

    def test_holdout_accuracy_above_threshold(self):
        texts, labels = _synthetic_dataset()
        result = tbc.train_holdout(texts, labels, min_df=2, test_size=0.3, seed=42)
        self.assertGreaterEqual(
            result['accuracy'], 0.85,
            "Accuracy por debajo de lo esperado en un dataset de vocabulario "
            "claramente separable; posible regresion en el pipeline.\n" + result['report'])
        self.assertGreaterEqual(result['macro_f1'], 0.8)


@unittest.skipUnless(HAS_SKLEARN, "requiere scikit-learn (pip install scikit-learn --break-system-packages)")
class TestModelRoundTrip(unittest.TestCase):
    """Entrena, exporta a JSON y comprueba que el motor REAL del plugin
    (ml_classifier.MLClassifier) carga ese JSON y clasifica bien."""

    def test_exported_model_loads_and_predicts_in_plugin(self):
        texts, labels = _synthetic_dataset()
        model = tbc.train_final(texts, labels, min_df=2)

        # El JSON debe sobrevivir a un ciclo dump/load sin perder tipos
        # (regresion concreta: clf.classes_ son np.str_, no str nativo).
        reloaded = json.loads(json.dumps(model, ensure_ascii=False))
        self.assertIsInstance(reloaded['classes'][0], str)

        clf = mlc.MLClassifier(model=reloaded, mood={})

        cases = [
            ("Una novela sobre una nave espacial y un robot en una estacion espacial.",
             "Ciencia Ficción"),
            ("Una novela sobre un hechicero poderoso y un dragon feroz.",
             "Fantasía"),
            ("Una novela sobre una boda sonada y un beso bajo la lluvia.",
             "Romance contemporáneo"),
        ]
        for text, expected in cases:
            result = clf.classify(text)
            self.assertEqual(
                result['library'], expected,
                "Prediccion incorrecta para {!r}: se esperaba {!r}, salio {!r} "
                "(confianza {:.2f})".format(text, expected, result['library'], result['confidence']))


if __name__ == '__main__':
    unittest.main()
