# -*- coding: utf-8 -*-
from __future__ import unicode_literals, division, absolute_import, print_function

import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor

from PyQt5.Qt import QThread, pyqtSignal

logger = logging.getLogger('ebook_comparator.jobs')

# ---------------------------------------------------------------------------
# Calibre's ThreadedJob calls the worker as:
#   func(*user_positional_args, log=log, abort=abort, notifications=notifications)
#
# Only _compare_pairs_chunk is a ThreadedJob worker.
# scan_pairs_sync runs in the main thread (it only reads DB metadata, ~instant).
# ---------------------------------------------------------------------------


def _get_all_book_ids(db):
    if hasattr(db, 'all_book_ids'):
        return list(db.all_book_ids())
    if hasattr(db, 'all_ids'):
        return list(db.all_ids())
    raise AttributeError('La base de datos no expone all_book_ids ni all_ids')


def _get_best_format_path(db, book_id):
    try:
        fmts = [fmt.upper() for fmt in (db.formats(book_id) or [])]
    except Exception:
        return None, None
    for fmt in ('EPUB', 'AZW3'):
        if fmt in fmts:
            try:
                path = db.format_abspath(book_id, fmt)
                if path and os.path.exists(path):
                    return fmt, path
            except Exception:
                continue
    return None, None


def _get_format_size(db, book_id, fmt):
    for getter in (
        lambda: db.format_db_size(book_id, fmt),
        lambda: db.sizeof_format(book_id, fmt, index_is_id=True),
    ):
        try:
            size = getter()
            if size:
                return size
        except Exception:
            pass
    try:
        path = db.format_abspath(book_id, fmt)
        if path and os.path.exists(path):
            return os.path.getsize(path)
    except Exception:
        pass
    return 0


# ---------------------------------------------------------------------------
# Normalización de título y autor para el agrupamiento (mejora de recall)
# ---------------------------------------------------------------------------
# Exigir título+autor EXACTOS pierde duplicados con metadatos ligeramente
# distintos ("The Hobbit" vs "Hobbit"; "Tolkien, J.R.R." vs "J.R.R. Tolkien").
# Estas funciones canonicalizan la clave de agrupamiento sin tocar los
# metadatos mostrados al usuario.

# Artículos iniciales que se eliminan del título (varios idiomas).
_ARTICLES = {
    'the', 'a', 'an',
    'el', 'la', 'los', 'las', 'un', 'una', 'unos', 'unas',
    'le', 'les', 'der', 'die', 'das', 'il', 'lo', 'o', 'os', 'as',
}


def _normalize_title(title):
    """minúsculas, sin puntuación, sin artículo inicial, espacios colapsados."""
    t = (title or '').lower()
    t = re.sub(r'[^\w\s]', ' ', t, flags=re.UNICODE)
    tokens = t.split()
    if tokens and tokens[0] in _ARTICLES:
        tokens = tokens[1:]
    return ' '.join(tokens)


def _normalize_authors(authors):
    """
    Clave canónica de autores, independiente del orden de los nombres y de la
    forma "Apellido, Nombre" vs "Nombre Apellido".  Cada autor se reduce a sus
    tokens alfanuméricos ordenados; el conjunto de autores también se ordena.
    """
    if isinstance(authors, (list, tuple)):
        items = list(authors)
    else:
        # Cadena ya unida: separar por separadores habituales de autores.
        items = re.split(r'\s*[;&]\s*|\s+y\s+|\s+and\s+', authors or '')
    norm = []
    for a in items:
        toks = sorted(re.sub(r'[^\w\s]', ' ', (a or '').lower()).split())
        if toks:
            norm.append(' '.join(toks))
    return '|'.join(sorted(set(norm)))


# ---------------------------------------------------------------------------
# Synchronous scan -- runs in the main thread, reads only DB metadata.
# Fast even for large libraries (no file I/O, no EPUB parsing).
# Returns a list of pair dicts: [{'book_a': {...}, 'book_b': {...}}, ...]
# ---------------------------------------------------------------------------

def scan_pairs_sync(db, restrict_to_ids=None):
    """
    Scans the library (or a subset) and returns all pairs of books that
    share the same NORMALIZED (title, authors, language) and have a supported
    format (EPUB/AZW3).

    El título y el autor se canonicalizan (ver _normalize_title /
    _normalize_authors) para agrupar también ediciones con metadatos
    ligeramente distintos.  El idioma se mantiene en la clave para no mezclar
    traducciones que comparten título y autor.

    restrict_to_ids: iterable of book IDs, or None for the whole library.
    """
    logger.info('[SCAN] started. restrict=%s',
                'ALL' if restrict_to_ids is None else len(restrict_to_ids))

    if restrict_to_ids is not None:
        all_ids = list(restrict_to_ids)
    else:
        all_ids = _get_all_book_ids(db)

    logger.info('[SCAN] books to scan: %d', len(all_ids))

    groups = {}
    skipped_no_format = 0

    for book_id in all_ids:
        try:
            title = (db.field_for('title', book_id) or '').strip()
            authors_raw = db.field_for('authors', book_id)
            if isinstance(authors_raw, (list, tuple)):
                authors = ', '.join(authors_raw)
            else:
                authors = authors_raw or ''
            authors = authors.strip()
        except Exception:
            continue

        if not title:
            continue

        fmt, path = _get_best_format_path(db, book_id)
        if not fmt:
            skipped_no_format += 1
            logger.debug('[SCAN] book %d (%r) skipped: no EPUB/AZW3', book_id, title)
            continue

        try:
            languages = db.field_for('languages', book_id)
        except Exception:
            languages = None
        if isinstance(languages, (list, tuple)):
            lang = languages[0] if languages else ''
        else:
            lang = languages or ''
        lang = lang.strip().lower()

        key = (_normalize_title(title), _normalize_authors(authors_raw), lang)
        groups.setdefault(key, []).append({
            'id':      book_id,
            'title':   title,
            'authors': authors,
            'format':  fmt,
            'path':    path,
            'size':    _get_format_size(db, book_id, fmt),
        })

    logger.info('[SCAN] groups total: %d, skipped (no format): %d',
                len(groups), skipped_no_format)

    pairs = []
    for key, books in groups.items():
        if len(books) < 2:
            continue
        logger.info('[SCAN] group %r: %d books -> %d pairs',
                    key[0], len(books), len(books) * (len(books) - 1) // 2)
        for i in range(len(books)):
            for j in range(i + 1, len(books)):
                pairs.append({'book_a': books[i], 'book_b': books[j]})

    logger.info('[SCAN] total pairs: %d', len(pairs))
    return pairs


# ---------------------------------------------------------------------------
# Fast-path binario + extracción cacheada/paralela (helpers de comparación)
# ---------------------------------------------------------------------------

def _binary_identical(pair):
    """
    True si los dos ficheros del par son binariamente idénticos.

    Atajo: si los tamaños se conocen y difieren, no pueden ser iguales (sin
    leer un solo byte del contenido).  Si los tamaños coinciden (o se
    desconocen), se compara el SHA-1 del fichero completo.  No abre el EPUB ni
    extrae texto: es el camino más rápido para detectar duplicados exactos.
    """
    from .extractor import file_sha1

    a = pair['book_a']
    b = pair['book_b']
    size_a = a.get('size') or 0
    size_b = b.get('size') or 0
    if size_a and size_b and size_a != size_b:
        return False
    ha = file_sha1(a['path'])
    hb = file_sha1(b['path'])
    return ha is not None and ha == hb


def _identity_chapter_map(chapters):
    """chapter_map para un par binariamente idéntico: cada capítulo consigo mismo."""
    return [{
        'chapter_a':    name,
        'best_match_b': name,
        'similarity':   100.0,
        'is_unique':    False,
    } for name in chapters]


def _extract_pair_parallel(path_a, path_b):
    """
    Extrae los capítulos de ambos libros EN PARALELO usando la versión
    cacheada del extractor.  La extracción es E/S + parseo XML (libera el GIL),
    así que solaparla acorta el tiempo de pared frente a hacerlo en serie.
    Devuelve (chaps_a, ignored_a, chaps_b, ignored_b).
    """
    from .extractor import extract_book_chapters_cached

    with ThreadPoolExecutor(max_workers=2) as ex:
        fut_a = ex.submit(extract_book_chapters_cached, path_a)
        fut_b = ex.submit(extract_book_chapters_cached, path_b)
        chaps_a, ignored_a = fut_a.result()
        chaps_b, ignored_b = fut_b.result()
    return chaps_a, ignored_a, chaps_b, ignored_b


# ---------------------------------------------------------------------------
# ThreadedJob worker -- compare a chunk of pairs (slow: reads EPUB files)
# ---------------------------------------------------------------------------

def _compare_pairs_chunk(result_holder, pairs_chunk, log=None, abort=None, notifications=None):
    from .extractor import extract_book_chapters_cached
    from .comparator import compare_books

    logger.info('[CHUNK] started. pairs=%d holder_id=%d', len(pairs_chunk), id(result_holder))
    results = []
    total = len(pairs_chunk)

    for n, pair in enumerate(pairs_chunk):
        if abort is not None and abort.is_set():
            logger.info('[CHUNK] aborted at pair %d', n)
            if log: log('[CHUNK] Aborted by user.')
            break

        # Cálculos para que el porcentaje global en Calibre sea preciso
        base_pct = n / max(total, 1)
        weight = 1.0 / max(total, 1)

        def _notify(sub_pct, msg):
            if log: log(msg)
            if notifications:
                try:
                    notifications.put((base_pct + (sub_pct * weight), msg))
                except Exception:
                    pass

        try:
            # 0. FAST-PATH BINARIO: ficheros byte a byte idénticos -> 100 %
            _notify(0.0, 'Par {}/{}: Comprobando duplicado binario...'.format(n + 1, total))
            if _binary_identical(pair):
                chaps_a, ignored_a = extract_book_chapters_cached(pair['book_a']['path'])
                results.append({
                    'book_a':      pair['book_a'],
                    'book_b':      pair['book_b'],
                    'similarity':  100.0,
                    'method':      'binary',
                    'chapter_map': _identity_chapter_map(chaps_a),
                    'unique_to_a': [],
                    'unique_to_b': [],
                    'ignored_a':   ignored_a,
                    'ignored_b':   list(ignored_a),
                })
                continue

            # 1-2. Extracción de ambos libros en paralelo (cacheada)
            _notify(0.3, 'Par {}/{}: Extrayendo libros (IDs {} / {})'.format(
                n + 1, total, pair['book_a']['id'], pair['book_b']['id']))
            chaps_a, ignored_a, chaps_b, ignored_b = _extract_pair_parallel(
                pair['book_a']['path'], pair['book_b']['path'])

            # 3. Comparación TF-IDF y Estructural
            _notify(0.6, 'Par {}/{}: Preparando comparación...'.format(n + 1, total))

            def prog_cb(p):
                if p % 10 == 0 or p == 100:
                    _notify(0.6 + (p / 100.0) * 0.4, 'Par {}/{}: Comparando... {}%'.format(n + 1, total, p))

            cmp = compare_books(chaps_a, chaps_b, method='combined', progress_cb=prog_cb)

            results.append({
                'book_a':      pair['book_a'],
                'book_b':      pair['book_b'],
                'similarity':  cmp['global_similarity'],
                'chapter_map': cmp.get('chapter_map', []),
                'unique_to_a': cmp.get('unique_to_a', []),
                'unique_to_b': cmp.get('unique_to_b', []),
                'ignored_a':   ignored_a,
                'ignored_b':   ignored_b,
            })
        except Exception as exc:
            logger.exception('[CHUNK] error comparing %s / %s',
                             pair['book_a']['path'], pair['book_b']['path'])
            results.append({
                'book_a':      pair['book_a'],
                'book_b':      pair['book_b'],
                'similarity':  -1.0,
                'error':       str(exc),
                'chapter_map': [],
                'unique_to_a': [],
                'unique_to_b': [],
            })

    logger.info('[CHUNK] finished. results=%d', len(results))
    result_holder.append(results)


# ---------------------------------------------------------------------------
# ThreadedJob worker -- ultrafast mode (100 % identical pairs only)
# ---------------------------------------------------------------------------

def _compare_pairs_chunk_ultrafast(result_holder, pairs_chunk, log=None, abort=None, notifications=None):
    """
    Variante ultrarrápida de _compare_pairs_chunk.

    Para cada par:
      0. Si los ficheros son binariamente idénticos -> 100 % inmediato
         (sin extraer ni comparar texto).
      1. Si no, extrae los capítulos de ambos libros (en paralelo, cacheados).
      2. Llama a compare_books_ultrafast(), que detiene la comparación
         en cuanto detecta que el resultado será inferior al 100%.
      3. Solo añade el par a los resultados si la similitud es exactamente 100%.
      4. Los pares con similitud < 100% se descartan silenciosamente.

    Los errores de extracción también se descartan (no se emite ninguna
    entrada de error en los resultados) para no contaminar la lista de
    duplicados exactos.
    """
    from .extractor import extract_book_chapters_cached
    from .comparator import compare_books_ultrafast

    logger.info('[CHUNK-UF] started. pairs=%d holder_id=%d', len(pairs_chunk), id(result_holder))
    results = []
    total   = len(pairs_chunk)

    for n, pair in enumerate(pairs_chunk):
        if abort is not None and abort.is_set():
            logger.info('[CHUNK-UF] aborted at pair %d', n)
            if log:
                log('[CHUNK-UF] Aborted by user.')
            break

        base_pct = n / max(total, 1)
        weight   = 1.0 / max(total, 1)

        def _notify(sub_pct, msg):
            if log:
                log(msg)
            if notifications:
                try:
                    notifications.put((base_pct + (sub_pct * weight), msg))
                except Exception:
                    pass

        try:
            # 0. FAST-PATH BINARIO
            _notify(0.0, 'Ultrarrápido {}/{}: Comprobando duplicado binario...'.format(n + 1, total))
            if _binary_identical(pair):
                chaps_a, ignored_a = extract_book_chapters_cached(pair['book_a']['path'])
                results.append({
                    'book_a':      pair['book_a'],
                    'book_b':      pair['book_b'],
                    'similarity':  100.0,
                    'method':      'binary',
                    'chapter_map': _identity_chapter_map(chaps_a),
                    'unique_to_a': [],
                    'unique_to_b': [],
                    'ignored_a':   ignored_a,
                    'ignored_b':   list(ignored_a),
                })
                continue

            _notify(0.3, 'Ultrarrápido {}/{}: Extrayendo libros (IDs {} / {})'.format(
                n + 1, total, pair['book_a']['id'], pair['book_b']['id']))
            chaps_a, ignored_a, chaps_b, ignored_b = _extract_pair_parallel(
                pair['book_a']['path'], pair['book_b']['path'])

            _notify(0.6, 'Ultrarrápido {}/{}: Comparando...'.format(n + 1, total))

            cmp = compare_books_ultrafast(chaps_a, chaps_b)

            if cmp is not None:
                # Similitud exactamente 100 %: incluir en resultados
                results.append({
                    'book_a':      pair['book_a'],
                    'book_b':      pair['book_b'],
                    'similarity':  cmp['global_similarity'],
                    'chapter_map': cmp.get('chapter_map', []),
                    'unique_to_a': cmp.get('unique_to_a', []),
                    'unique_to_b': cmp.get('unique_to_b', []),
                    'ignored_a':   ignored_a,
                    'ignored_b':   ignored_b,
                })
            # else: similitud < 100 %, par descartado silenciosamente
        except Exception:
            logger.exception('[CHUNK-UF] error comparing %s / %s',
                             pair['book_a']['path'], pair['book_b']['path'])
            # En modo ultrarrápido los errores no se reportan como resultados

    logger.info('[CHUNK-UF] finished. results=%d (100%% pairs only)', len(results))
    result_holder.append(results)


# ---------------------------------------------------------------------------
# QThread worker -- manual 2-book comparison (ComparisonDialog)
# ---------------------------------------------------------------------------

class ComparisonWorker(QThread):
    progress = pyqtSignal(int)
    status   = pyqtSignal(str)   # <--- NUEVA SEÑAL PARA TEXTO
    finished = pyqtSignal(dict)
    error    = pyqtSignal(str)

    def __init__(self, path_a, path_b, method):
        super().__init__()
        self.path_a = path_a
        self.path_b = path_b
        self.method = method

    def run(self):
        try:
            from .extractor import extract_book_chapters_cached, file_sha1
            from .comparator import compare_books

            # Fast-path binario también en modo manual.
            self.status.emit("Comprobando duplicado binario...")
            self.progress.emit(5)
            ha = file_sha1(self.path_a)
            hb = file_sha1(self.path_b)
            if ha is not None and ha == hb:
                self.status.emit("Ficheros binariamente idénticos.")
                self.progress.emit(90)
                chaps_a, ignored_a = extract_book_chapters_cached(self.path_a)
                chapter_map = [{
                    'chapter_a': n, 'best_match_b': n,
                    'similarity': 100.0, 'is_unique': False,
                } for n in chaps_a]
                self.progress.emit(100)
                self.finished.emit({
                    'global_similarity': 100.0,
                    'method':            'binary',
                    'chapter_map':       chapter_map,
                    'unique_to_a':       [],
                    'unique_to_b':       [],
                    'ignored_a':         ignored_a,
                    'ignored_b':         list(ignored_a),
                })
                return

            self.status.emit("Extrayendo capítulos del Libro 1...")
            self.progress.emit(10)
            chaps_a, ignored_a = extract_book_chapters_cached(self.path_a)

            self.status.emit("Extrayendo capítulos del Libro 2...")
            self.progress.emit(30)
            chaps_b, ignored_b = extract_book_chapters_cached(self.path_b)

            self.status.emit("Generando matrices y comparando...")
            self.progress.emit(50)

            def _prog(p):
                self.progress.emit(50 + p // 2)
                self.status.emit("Comparando fragmentos... {}%".format(p))

            result = compare_books(
                chaps_a, chaps_b,
                method=self.method,
                progress_cb=_prog,
            )
            result['ignored_a'] = ignored_a
            result['ignored_b'] = ignored_b
            self.status.emit("¡Comparación finalizada!")
            self.finished.emit(result)
        except Exception as exc:
            logger.exception('ComparisonWorker failed')
            self.error.emit(str(exc))
