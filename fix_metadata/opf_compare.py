#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Lee los metadatos EMBEBIDOS en el fichero del libro (el OPF interno de un
# EPUB, o los metadatos de un AZW3/MOBI) y los compara con lo que Calibre tiene
# ahora mismo en su base de datos.
#
# La decision "igual vs distinto" reutiliza el metodo de comparacion de Smart
# Metadata (matching.py): similitud difusa de titulo y autor (tolerante a
# acentos, orden de palabras y "Apellido, Nombre") mas el chequeo de conflicto
# de idioma.  La serie se compara de forma normalizada (titulo/indice).
#
# TITULO: se compara solo el "nucleo" del titulo.  Antes de medir la similitud
# se le quita a AMBOS lados (Calibre y OPF) todo lo que sea serie o subtitulo
# embebido en el propio titulo (p.ej. "Titulo (Serie #2)" o "Titulo: Subtitulo"),
# para no marcar como distinto un titulo que solo cambia en la serie/subtitulo.
# La serie se sigue comparando aparte, en su propio campo.
#
# Devuelve, por libro, la lista de campos que difieren y un Metadata "propuesto"
# (copia del actual con los valores del OPF aplicados) listo para CompareMany.
from __future__ import unicode_literals, division, absolute_import, print_function

__license__   = 'GPL v3'
__copyright__ = '2026, Yolanda Braojos'

import copy
import logging

from calibre_plugins.fix_metadata.matching import (
    title_similarity, author_similarity, languages_conflict, _norm)
from calibre_plugins.fix_metadata.fix_title import (
    find_series_in_title, find_language_in_title,
    find_subtitle_in_title, make_clean_title)

logger = logging.getLogger('FIX_METADATA_PLUGIN')

# Formatos de los que sabemos leer un OPF/metadatos embebidos, por preferencia.
PREFERRED_FORMATS = ('EPUB', 'AZW3', 'MOBI', 'AZW', 'KEPUB')

# Campos que leemos del OPF y mostramos en CompareMany.
COMPARE_FIELDS = ('title', 'authors', 'series', 'languages')


def _pick_format(db, book_id):
    """Devuelve (fmt, ruta_absoluta) del mejor formato disponible, o (None, None)."""
    try:
        fmts = db.formats(book_id, index_is_id=True) or ''
    except Exception:
        fmts = ''
    available = [f.strip().upper() for f in fmts.split(',') if f.strip()]
    order = list(PREFERRED_FORMATS) + [f for f in available if f not in PREFERRED_FORMATS]
    for fmt in order:
        if fmt not in available:
            continue
        try:
            path = db.format_abspath(book_id, fmt, index_is_id=True)
        except Exception:
            path = None
        if path:
            return fmt, path
    return None, None


def read_file_metadata(db, book_id):
    """Lee los metadatos embebidos en el fichero del libro.

    Devuelve (filemi, fmt) o (None, None) si no hay formato legible.  ``filemi``
    es un :class:`Metadata` de Calibre con titulo/autores/serie/idioma tal y
    como estan escritos DENTRO del fichero (el OPF de un EPUB)."""
    from calibre.ebooks.metadata.meta import get_metadata as _get_file_metadata

    fmt, path = _pick_format(db, book_id)
    if not path:
        return None, None
    try:
        with open(path, 'rb') as f:
            filemi = _get_file_metadata(f, fmt)
        return filemi, fmt
    except Exception as e:
        logger.warning("No se pudieron leer metadatos de %s (id=%s): %s"
                       % (fmt, book_id, e))
        return None, None


def core_title(title, author=None, author_sort=None):
    """Devuelve el 'nucleo' del titulo: el titulo sin la serie ni el subtitulo
    que pudieran ir embebidos en el propio texto.

    1. Detecta idioma/serie/indice/subtitulo dentro del titulo (misma logica
       que usa "Fix series"/"Fix subtitle").
    2. ``make_clean_title`` retira serie, idioma, prefijo de autor y subtitulo
       entre parentesis.
    3. Ademas, si queda un subtitulo con dos puntos ("Principal: Subtitulo"),
       se recorta a la parte principal.

    El resultado se usa SOLO para comparar; nunca se escribe."""
    if not title:
        return ''
    try:
        lang = find_language_in_title(title)
        series, index, _sub = find_series_in_title(
            title, language=lang, author=author, author_sort=author_sort)
        subtitle = find_subtitle_in_title(title)
        core = make_clean_title(
            title, series=series, index=index, language=lang,
            author=author, author_sort=author_sort, subtitle=subtitle)
    except Exception as e:
        logger.debug("core_title fallback for %r: %s" % (title, e))
        core = title
    # Subtitulo con dos puntos: "Principal: Subtitulo" -> "Principal".
    try:
        if find_subtitle_in_title(core):
            core = core.split(': ', 1)[0].strip()
    except Exception:
        pass
    return (core or title).strip()


def _book_author(mi):
    author = (mi.authors[0] if getattr(mi, 'authors', None) else '') or None
    asort  = (getattr(mi, 'author_sort', '') or '') or None
    return author, asort


def _series_differs(oldmi, filemi):
    """La serie del OPF difiere de la de Calibre (normalizada), y el OPF trae
    serie.  Tambien detecta un cambio de indice cuando el nombre de serie casa."""
    fs = (filemi.series or '').strip()
    if not fs:
        return False, None, None            # el OPF no aporta serie: no forzar
    os_ = (oldmi.series or '').strip()
    if _norm(fs) != _norm(os_):
        return True, fs, filemi.series_index
    # Mismo nombre de serie: comprobar el indice.
    try:
        fi = float(filemi.series_index) if filemi.series_index is not None else None
        oi = float(oldmi.series_index) if oldmi.series_index is not None else None
    except Exception:
        fi = oi = None
    if fi is not None and oi is not None and abs(fi - oi) > 1e-9:
        return True, fs, filemi.series_index
    return False, None, None


def compare(oldmi, filemi, title_thr, author_thr, require_author):
    """Compara el OPF (filemi) con Calibre (oldmi) usando el metodo de
    Smart Metadata para titulo/autor/idioma y comparacion normalizada de serie.

    El titulo se compara por su NUCLEO (sin serie ni subtitulo embebidos, en
    ambos lados).

    Devuelve (changed_fields, newmi) donde:
      * changed_fields: lista de campos que difieren (subconjunto de
        COMPARE_FIELDS).  Vacia => son iguales, el libro se omite.
      * newmi: copia de oldmi con los valores del OPF aplicados SOLO en los
        campos que difieren (lo que CompareMany propondra a la izquierda).
    """
    thr_t = title_thr / 100.0 if title_thr > 1 else title_thr
    thr_a = author_thr / 100.0 if author_thr > 1 else author_thr

    changed = []
    newmi = copy.deepcopy(oldmi)

    # --- Titulo: comparar solo el nucleo (sin serie ni subtitulo) ---
    ft = (filemi.title or '').strip()
    if ft and not filemi.is_null('title'):
        o_auth, o_asort = _book_author(oldmi)
        f_auth, f_asort = _book_author(filemi)
        if not f_auth:
            f_auth, f_asort = o_auth, o_asort
        core_old  = core_title(oldmi.title or '', o_auth, o_asort)
        core_file = core_title(filemi.title, f_auth, f_asort)
        ts = title_similarity(core_old, core_file)
        if ts < thr_t:
            changed.append('title')
            newmi.title = filemi.title

    # --- Autores (mejor coincidencia por pares) ---
    fa = [a for a in (filemi.authors or []) if a and a.strip()
          and a.strip().lower() != 'unknown']
    if fa:
        asim = author_similarity(oldmi.authors or [], fa)
        if asim < thr_a:
            changed.append('authors')
            newmi.authors = list(filemi.authors)

    # --- Serie (+ indice), comparacion normalizada ---
    sdiff, s_name, s_index = _series_differs(oldmi, filemi)
    if sdiff:
        changed.append('series')
        newmi.series = s_name
        if s_index is not None:
            newmi.series_index = s_index

    # --- Idioma (conflicto real de idioma declarado en ambos) ---
    if languages_conflict(oldmi, filemi):
        changed.append('languages')
        newmi.languages = list(filemi.languages)

    return changed, newmi
