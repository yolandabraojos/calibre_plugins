# -*- coding: utf-8 -*-
from __future__ import unicode_literals, division, absolute_import, print_function

import logging
import os

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
# Synchronous scan — runs in the main thread, reads only DB metadata.
# Fast even for large libraries (no file I/O, no EPUB parsing).
# Returns a list of pair dicts: [{'book_a': {...}, 'book_b': {...}}, ...]
# ---------------------------------------------------------------------------

def scan_pairs_sync(db, restrict_to_ids=None):
    """
    Scans the library (or a subset) and returns all pairs of books that
    share the same (title, authors) and have a supported format (EPUB/AZW3).

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
            authors = db.field_for('authors', book_id)
            if isinstance(authors, (list, tuple)):
                authors = ', '.join(authors)
            authors = (authors or '').strip()
        except Exception:
            continue

        if not title:
            continue

        fmt, path = _get_best_format_path(db, book_id)
        if not fmt:
            skipped_no_format += 1
            logger.debug('[SCAN] book %d (%r) skipped: no EPUB/AZW3', book_id, title)
            continue

        key = (title.lower(), authors.lower())
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
        logger.info('[SCAN] group %r: %d books → %d pairs',
                    key[0], len(books), len(books) * (len(books) - 1) // 2)
        for i in range(len(books)):
            for j in range(i + 1, len(books)):
                pairs.append({'book_a': books[i], 'book_b': books[j]})

    logger.info('[SCAN] total pairs: %d', len(pairs))
    return pairs


# ---------------------------------------------------------------------------
# ThreadedJob worker — compare a chunk of pairs (slow: reads EPUB files)
# ---------------------------------------------------------------------------

def _compare_pairs_chunk(result_holder, pairs_chunk, log=None, abort=None, notifications=None):
    from .extractor import extract_book_chapters
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
            # 1. Extracción Libro A
            _notify(0.0, 'Par {}/{}: Extrayendo Libro A (ID {})'.format(n + 1, total, pair['book_a']['id']))
            chaps_a, ignored_a = extract_book_chapters(pair['book_a']['path'])

            # 2. Extracción Libro B
            _notify(0.3, 'Par {}/{}: Extrayendo Libro B (ID {})'.format(n + 1, total, pair['book_b']['id']))
            chaps_b, ignored_b = extract_book_chapters(pair['book_b']['path'])

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
# QThread worker — manual 2-book comparison (ComparisonDialog)
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
            from .extractor import extract_book_chapters
            from .comparator import compare_books

            self.status.emit("Extrayendo capítulos del Libro 1...")
            self.progress.emit(10)
            chaps_a, ignored_a = extract_book_chapters(self.path_a)

            self.status.emit("Extrayendo capítulos del Libro 2...")
            self.progress.emit(30)
            chaps_b, ignored_b = extract_book_chapters(self.path_b)
            
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