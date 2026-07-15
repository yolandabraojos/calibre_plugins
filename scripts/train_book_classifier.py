#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
train_book_classifier.py -- Reentrena el modelo local del Book Classifier (eje 1: libreria)
=============================================================================================

Lee TODOS los .csv de una carpeta de datos (por defecto _datos_ejemplo/ en la raiz
del repo), sea cual sea su nombre, y usa la columna `#libreria` (la que rellena el
rescate con IA, ver book_classifier/llm_jobs.py) como etiqueta de verdad. Reproduce
EXACTAMENTE el pipeline de inferencia de book_classifier/ml_classifier.py (mismo
normalize(), mismo TfidfVectorizer, misma LogisticRegression) para que el
model_weights.json resultante funcione en el plugin sin tocar ml_classifier.py.

FUGA: se excluyen del texto de entrada las tags que codifican directamente la
libreria (grupo 'Genero'/'Biblioteca'/'Libreria' en formato canonico
'Grupo (dot) Valor' de fix_metadata, o los prefijos en crudo pre-fix_metadata:
_Biblioteca., Libreria., English., Spanish., Temas., Themes., FICTION/). El resto
de tags canonicas (Subgenero, Ambientacion, Tono, Dinamica, Arquetipo, Paranormal...)
SI se usan como señal: no repiten la clase, describen contenido del libro. Mismo
criterio que book_classifier/llm_jobs.py::_is_leak_tag -- si cambias uno, cambia
el otro (ver memoria book-classifier-retrain.md). De esas tags SI usadas solo se
queda el VALOR (tag_value): el nombre del grupo ('Tono', 'Dinamica'...) no es
contenido, es la etiqueta de la faceta, y dejarlo colaba 'tono'/'dinamica'/
'subgenero' como palabras sueltas en 40-47% de los libros (puro ruido).

LIMPIEZA DE VOCABULARIO: ademas del filtro de fuga, max_df=0.4 (por defecto)
descarta n-gramas que aparecen en mas del 40% de los libros -- articulos y
verbos genericos en cualquier idioma ('a', 'the', 'and', 'de', 'la'...) sin
necesidad de mantener una lista de stopwords a mano. Solo afecta al
entrenamiento (que entra en el vocabulario exportado); no requiere tocar
ml_classifier.py.

Las funciones de entrenamiento (fit_vectorizer/train_holdout/train_final) estan
separadas de main() a proposito para que tests/test_train_book_classifier.py
pueda llamarlas directamente con datos sinteticos, sin pasar por CSV ni CLI --
ese test es el que comprueba que el PIPELINE realmente aprende (accuracy minima
en un dataset de control) y que el filtro de fuga funciona, no solo que el
script no truene.

Uso:
    pip install scikit-learn --break-system-packages   # o tu venv habitual
    python3 scripts/train_book_classifier.py
    python3 scripts/train_book_classifier.py --datos _datos_ejemplo --out book_classifier/model_weights_new.json
    python3 scripts/train_book_classifier.py --min-per-class 15 --min-df 5

Por defecto NO sobreescribe el model_weights.json en produccion: escribe
model_weights_new.json al lado. Cuando revises las metricas y decidas adoptarlo,
copialo (bash, NUNCA Write/Edit) sobre book_classifier/model_weights.json, corre
verificar_plugin.py y luego build_plugins.py para regenerar el ZIP.
"""
from __future__ import annotations
import argparse
import collections
import csv
import glob
import html
import io
import json
import os
import re
import sys
import unicodedata

# --- Mismo normalize() que book_classifier/ml_classifier.py -----------------
# (si cambias esto, cambia tambien ml_classifier.py o la inferencia dejara de
# coincidir con el entrenamiento)
def normalize(text):
    text = html.unescape(text or '')
    text = re.sub(r'<[^>]+>', ' ', text)
    text = text.replace("'", '').replace('\u2019', '')
    text = unicodedata.normalize('NFKD', text)
    text = ''.join(c for c in text if not unicodedata.combining(c)).lower()
    text = re.sub(r"[^a-z0-9/\- ]", ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


# --- Mismo filtro de fuga que book_classifier/llm_jobs.py::_is_leak_tag -----
# Post fix_metadata TODAS las tags canonicas usan 'Grupo (dot) Valor', asi que
# "contiene el separador" ya NO distingue fuga de señal legitima: solo el
# grupo 'Genero'/'Biblioteca'/'Libreria' equivale a la propia etiqueta que se
# entrena. Ver memoria cloud-sync-write-corruption.md / book-classifier-retrain.md.
_LEAK_RAW_PREFIX_RE = re.compile(
    r'^(_?Biblioteca\.|_?Libreria\.|English\.|Spanish\.|Temas\.|Themes\.|FICTION/)',
    re.IGNORECASE)
_LEAK_GROUPS = ('genero', 'biblioteca', 'libreria')


def _leak_group(tag):
    t = str(tag or '')
    if '·' not in t:
        return ''
    grupo = t.split('·', 1)[0].strip()
    grupo = unicodedata.normalize('NFKD', grupo)
    grupo = ''.join(c for c in grupo if not unicodedata.combining(c))
    return grupo.lower()


def is_leak_tag(tag):
    t = str(tag or '').strip()
    if not t:
        return False
    if _leak_group(t) in _LEAK_GROUPS:
        return True
    return bool(_LEAK_RAW_PREFIX_RE.match(t))


def tag_value(tag):
    """Para una tag canonica 'Grupo · Valor' (Subgenero, Ambientacion, Tono,
    Dinamica, Arquetipo, Paranormal...) devuelve SOLO 'Valor'. El nombre del
    grupo no es contenido del libro, es la etiqueta de la faceta -- dejarlo
    metia como palabra suelta contamina el vocabulario sin aportar señal
    (medido: 'tono'/'dinamica'/'subgenero' aparecian en 40-47% de los libros,
    puro ruido estructural). Las tags sin ese formato se devuelven tal cual."""
    t = str(tag or '').strip()
    if '·' in t:
        return t.split('·', 1)[1].strip()
    return t


# Debe coincidir con LIBRERIAS de book_classifier/llm_rescue_engine.py y de
# scripts/llm_rescue.py (no hay un unico sitio de donde importarlo: los tres
# ficheros llevan su propia copia, sincronizar a mano si cambia).
EXPECTED_LIBRERIAS = [
    "Romance contemporáneo",
    "Romance histórico",
    "Romantasy",
    "Paranormal",
    "Fantasía",
    "Ciencia Ficción",
    "Misterio·Thriller·Terror",
    "Ficción general",
    "No-Ficción",
]

REVISAR_VALUES = {'', '(revisar)', '[revisar]', 'revisar', 'sin datos', '(sin datos)'}


def norm_key(v):
    s = '' if v is None else str(v)
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return ' '.join(s.lower().split())


def _read_csv_dicts(path):
    """Lee un CSV tolerando bytes nulos (corrupcion de sincronizacion en la
    nube: escrituras truncadas a medias dejan la cola del fichero rellena de
    \x00, ver memoria cloud-sync-write-corruption.md). Si aparecen, se
    eliminan y se seguye leyendo lo que haya quedado completo -perder la cola
    truncada es preferible a que csv.DictReader reviente con "line contains
    NUL"-, y se avisa para que el fichero se reexporte desde Calibre.
    Devuelve (fieldnames, rows, null_count)."""
    with open(path, 'rb') as fb:
        raw = fb.read()
    null_count = raw.count(b'\x00')
    if null_count:
        raw = raw.replace(b'\x00', b'')
    text = raw.decode('utf-8-sig', errors='replace')
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    return reader.fieldnames or [], rows, null_count


def load_rows(datos_dir):
    """Lee TODOS los *.csv de datos_dir, sea cual sea su nombre. Los ficheros
    sin columna #libreria (exports que no han pasado por el rescate con IA) se
    listan pero se ignoran para entrenar."""
    paths = sorted(glob.glob(os.path.join(datos_dir, '*.csv')))
    if not paths:
        sys.exit("No se encontro ningun .csv en {!r}".format(datos_dir))
    rows = []
    used_files = []
    skipped_files = []
    corrupted_files = []
    for p in paths:
        fieldnames, file_rows, null_count = _read_csv_dicts(p)
        if null_count:
            corrupted_files.append((os.path.basename(p), null_count))
        if '#libreria' not in fieldnames:
            skipped_files.append(os.path.basename(p))
            continue
        used_files.append(os.path.basename(p))
        rows.extend(file_rows)
    print("CSV encontrados: {} ({})".format(
        len(paths), ', '.join(os.path.basename(p) for p in paths)))
    if used_files:
        print("  Con columna #libreria (usados): {}".format(', '.join(used_files)))
    if skipped_files:
        print("  SIN columna #libreria (ignorados): {}".format(', '.join(skipped_files)))
    if corrupted_files:
        print("\nAVISO: bytes nulos encontrados y eliminados (probable corrupcion de "
              "sincronizacion en la nube al exportar) -- pueden faltar filas del final; "
              "re-exporta estos ficheros desde Calibre:")
        for name, n in corrupted_files:
            print("  - {} ({} bytes nulos)".format(name, n))
    return rows


def build_examples(rows):
    """Filtra filas con #libreria valida, deduplica por (titulo,autor) -se
    queda con la copia de sinopsis mas larga, descarta grupos con libreria en
    conflicto- y construye (texto, etiqueta) por libro."""
    diag = {'total': len(rows), 'sin_libreria': 0, 'revisar': 0, 'validas': 0,
            'duplicados_descartados': 0, 'conflictos_descartados': 0}
    groups = {}
    order = []
    for row in rows:
        lib = (row.get('#libreria') or '').strip()
        if not lib:
            diag['sin_libreria'] += 1
            continue
        if lib.lower() in REVISAR_VALUES:
            diag['revisar'] += 1
            continue
        diag['validas'] += 1
        title = row.get('title') or ''
        authors = row.get('authors') or ''
        key = (norm_key(title), norm_key(authors))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append((lib, title, row.get('comments') or '', row.get('tags') or ''))

    examples = []
    for key in order:
        members = groups[key]
        libs = {m[0] for m in members}
        if len(libs) > 1:
            # Copias del mismo libro con libreria distinta: conflicto, se descartan
            # (igual que en el reentrenamiento anterior, ver book-classifier-retrain.md).
            diag['conflictos_descartados'] += len(members)
            continue
        if len(members) > 1:
            diag['duplicados_descartados'] += len(members) - 1
        lib, title, comments, tags_raw = max(members, key=lambda m: len(m[2] or ''))
        tags = [t.strip() for t in tags_raw.split(',') if t.strip()]
        clean_tags = [tag_value(t) for t in tags if not is_leak_tag(t)]
        comments_txt = re.sub(r'<[^>]+>', ' ', comments)
        text = ' '.join([title, comments_txt, ' '.join(clean_tags)])
        examples.append((text, lib))
    return examples, diag


# --- Entrenamiento: separado de main() para poder testearlo con datos ------
# sinteticos (ver tests/test_train_book_classifier.py). NUNCA cambies estos
# hiperparametros sin sincronizar book_classifier/ml_classifier.py.
def fit_vectorizer(min_df, max_df=0.4):
    """max_df=0.4 descarta n-gramas que aparecen en mas del 40% de los
    libros (articulos/verbos genericos en cualquier idioma: 'a', 'the', 'and',
    'de', 'la'...), sin necesidad de mantener una lista de stopwords a mano.
    Solo afecta a que entra en el vocabulario EXPORTADO -- no requiere ningun
    cambio en ml_classifier.py (la inferencia solo busca en lo ya exportado).
    """
    from sklearn.feature_extraction.text import TfidfVectorizer
    return TfidfVectorizer(preprocessor=normalize, tokenizer=str.split,
                            token_pattern=None, lowercase=False,
                            ngram_range=(1, 2), min_df=min_df, max_df=max_df,
                            sublinear_tf=True, norm='l2')


def train_holdout(texts, labels, min_df, test_size, seed, max_df=0.4):
    """Entrena en un split train/test (SIN fuga: el vectorizador solo ve
    X_train) y devuelve un dict con las metricas de evaluacion sobre el
    holdout: accuracy, macro_f1, report (texto), vocab_size, can_stratify."""
    from sklearn.model_selection import train_test_split
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import classification_report, accuracy_score, f1_score

    class_counts = collections.Counter(labels)
    can_stratify = all(c >= 2 for c in class_counts.values())
    strat = labels if can_stratify else None
    X_train, X_test, y_train, y_test = train_test_split(
        texts, labels, test_size=test_size, random_state=seed, stratify=strat)

    vec = fit_vectorizer(min_df, max_df)
    Xtr = vec.fit_transform(X_train)
    Xte = vec.transform(X_test)

    clf = LogisticRegression(C=3, class_weight='balanced', max_iter=3000)
    clf.fit(Xtr, y_train)
    y_pred = clf.predict(Xte)

    return {
        'can_stratify': can_stratify,
        'vocab_size': len(vec.vocabulary_),
        'accuracy': accuracy_score(y_test, y_pred),
        'macro_f1': f1_score(y_test, y_pred, average='macro', zero_division=0),
        'report': classification_report(y_test, y_pred, zero_division=0),
        'y_test': list(y_test),
        'y_pred': list(y_pred),
    }


def train_final(texts, labels, min_df, max_df=0.4):
    """Reentrena con TODOS los ejemplos (sin holdout) y devuelve el modelo
    listo para exportar a JSON con el mismo esquema que carga
    book_classifier/ml_classifier.py::MLClassifier."""
    from sklearn.linear_model import LogisticRegression

    vec = fit_vectorizer(min_df, max_df)
    Xfull = vec.fit_transform(texts)
    clf = LogisticRegression(C=3, class_weight='balanced', max_iter=3000)
    clf.fit(Xfull, labels)

    classes = [str(c) for c in clf.classes_]
    inv_vocab = {i: ng for ng, i in vec.vocabulary_.items()}
    idf_arr = vec.idf_
    coef_arr = clf.coef_  # (n_classes, n_features), alineado a clf.classes_

    idf_by_ngram = {}
    coef_by_ngram = {}
    for i, ng in inv_vocab.items():
        idf_by_ngram[ng] = round(float(idf_arr[i]), 6)
        coef_by_ngram[ng] = [round(float(c), 6) for c in coef_arr[:, i]]

    return {
        'classes': classes,
        'intercept': [round(float(x), 6) for x in clf.intercept_],
        'idf': idf_by_ngram,
        'coef': coef_by_ngram,
        'sublinear_tf': True,
        'norm': 'l2',
        'ngram': [1, 2],
    }


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(here)
    ap.add_argument('--datos', default=os.path.join(repo_root, '_datos_ejemplo'),
                     help='carpeta con los .csv exportados de Calibre (por defecto _datos_ejemplo/)')
    ap.add_argument('--out', default=os.path.join(repo_root, 'book_classifier', 'model_weights_new.json'),
                     help='fichero de salida; NO sobreescribe el model_weights.json de produccion por defecto')
    ap.add_argument('--min-per-class', type=int, default=20,
                     help='clases con menos ejemplos que esto se AVISAN pero no se excluyen (default 20)')
    ap.add_argument('--min-df', type=int, default=10,
                     help='min_df del TfidfVectorizer (default 10, el del modelo original de 17k libros; '
                          'bajalo si tu dataset es mas pequeno)')
    ap.add_argument('--max-df', type=float, default=0.4,
                     help='max_df del TfidfVectorizer (default 0.4): descarta n-gramas que aparecen en '
                          'mas de ese porcentaje de libros -- articulos/verbos genericos en cualquier '
                          'idioma, sin lista de stopwords que mantener a mano')
    ap.add_argument('--test-size', type=float, default=0.2)
    ap.add_argument('--seed', type=int, default=42)
    args = ap.parse_args()

    try:
        import sklearn  # noqa: F401
    except ImportError:
        sys.exit("Falta scikit-learn. Instala con: pip install scikit-learn --break-system-packages")

    rows = load_rows(args.datos)
    examples, diag = build_examples(rows)
    print()
    print("Filas leidas (ficheros con #libreria): {}".format(diag['total']))
    print("  sin #libreria: {}  |  '(revisar)'/vacia: {}  |  validas: {}".format(
        diag['sin_libreria'], diag['revisar'], diag['validas']))
    print("  duplicados fusionados: {}  |  conflictos descartados: {}".format(
        diag['duplicados_descartados'], diag['conflictos_descartados']))
    print("Ejemplos unicos para entrenar: {}".format(len(examples)))

    if len(examples) < 10:
        sys.exit("\nMuy pocos ejemplos validos ({}) para entrenar nada util.".format(len(examples)))

    counts = collections.Counter(lib for _, lib in examples)
    print("\nDistribucion por libreria:")
    for lib, n in counts.most_common():
        marca = '  <-- POCOS EJEMPLOS' if n < args.min_per_class else ''
        print("  {:5d}  {}{}".format(n, lib, marca))

    missing = [l for l in EXPECTED_LIBRERIAS if l not in counts]
    if missing:
        print("\nAVISO: CERO ejemplos de estas librerias (el modelo NUNCA las podra predecir):")
        for l in missing:
            print("  - {}".format(l))
    unexpected = [l for l in counts if l not in EXPECTED_LIBRERIAS]
    if unexpected:
        print("\nAVISO: valores de #libreria que no estan en la lista esperada (revisa si son typos):")
        for l in unexpected:
            print("  - {!r} ({})".format(l, counts[l]))

    if len(counts) < 2:
        sys.exit("\nSolo hay una libreria con ejemplos: no se puede entrenar un clasificador.")

    texts = [t for t, _ in examples]
    labels = [l for _, l in examples]

    if not all(c >= 2 for c in collections.Counter(labels).values()):
        print("\nAVISO: alguna libreria tiene menos de 2 ejemplos; el holdout de evaluacion "
              "no se estratifica (la metrica sera menos fiable para esas clases).")

    holdout = train_holdout(texts, labels, args.min_df, args.test_size, args.seed, args.max_df)
    print("\nVocabulario (holdout de evaluacion): {} n-gramas (min_df={})".format(
        holdout['vocab_size'], args.min_df))
    print("\n=== Evaluacion (holdout {:.0%}, SIN fuga: tags de Genero/Biblioteca excluidas) ===".format(
        args.test_size))
    print("Accuracy: {:.3f}  |  Macro-F1: {:.3f}".format(holdout['accuracy'], holdout['macro_f1']))
    print(holdout['report'])

    # Reentrena con TODO el dataset (train+test) para el modelo final exportado
    model = train_final(texts, labels, args.min_df, args.max_df)

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(model, f, ensure_ascii=False)

    print("\nModelo final (con TODOS los ejemplos) escrito en: {}".format(args.out))
    print("Clases: {}".format(model['classes']))
    print("Features: {}".format(len(model['idf'])))
    print()
    print("Este fichero NO sustituye automaticamente al de produccion.")
    print("Revisa las metricas de arriba (ojo a las librerias con POCOS EJEMPLOS o en AVISO).")
    print("Si te convencen: copialo (bash, NUNCA Write/Edit) sobre book_classifier/model_weights.json,")
    print("corre verificar_plugin.py y luego build_plugins.py para regenerar el ZIP.")


if __name__ == '__main__':
    main()
