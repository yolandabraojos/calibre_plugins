#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Similitud titulo/autor para decidir "seguro" vs "dudoso".
# Deterministico, offline, sin dependencias externas (solo stdlib).
from __future__ import unicode_literals, division, absolute_import, print_function

import re
import unicodedata
from difflib import SequenceMatcher

__license__ = 'GPL v3'
__copyright__ = '2026, Yolanda Braojos'


def _strip_accents(s):
    s = unicodedata.normalize('NFKD', s)
    return ''.join(c for c in s if not unicodedata.combining(c))


def _norm(s):
    """Minusculas, sin acentos, solo alfanumerico, espacios colapsados."""
    if not s:
        return ''
    s = _strip_accents(unicode_type(s)).lower()
    s = re.sub(r'[^a-z0-9]+', ' ', s)
    return ' '.join(s.split())


try:
    unicode_type = unicode  # noqa: F821  (Python 2)
except NameError:
    unicode_type = str


def _ratio(a, b):
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _token_sort_ratio(a, b):
    """Ratio ignorando el orden de las palabras (p.ej. 'Nombre Apellido'
    vs 'Apellido, Nombre')."""
    if not a or not b:
        return 0.0
    ta = ' '.join(sorted(a.split()))
    tb = ' '.join(sorted(b.split()))
    return SequenceMatcher(None, ta, tb).ratio()


def title_similarity(old_title, new_title):
    """Devuelve 0..1. Toma el mejor de: comparacion directa, orden-insensible
    y comparacion solo del titulo principal (antes de ':')."""
    o, n = _norm(old_title), _norm(new_title)
    if not o or not n:
        return 0.0
    cands = [_ratio(o, n), _token_sort_ratio(o, n)]
    # Solo el titulo principal, descartando subtitulo tras ':'
    oh = _norm(unicode_type(old_title).split(':')[0])
    nh = _norm(unicode_type(new_title).split(':')[0])
    if oh and nh:
        cands.append(_ratio(oh, nh))
    return max(cands)


def author_similarity(old_authors, new_authors):
    """Mejor coincidencia por pares entre las dos listas de autores, 0..1."""
    if not new_authors or not old_authors:
        return 0.0
    olds = [_norm(a) for a in old_authors if a]
    news = [_norm(a) for a in new_authors if a]
    olds = [a for a in olds if a]
    news = [a for a in news if a]
    if not olds or not news:
        return 0.0
    best = 0.0
    for a in olds:
        for b in news:
            best = max(best, _token_sort_ratio(a, b))
    return best


def classify(oldmi, newmi, title_thr, author_thr, require_author):
    """(seguro, title_sim, author_sim).

    Calibre guarda titulo/autor como null en el OPF descargado cuando son
    identicos al original (optimizacion): eso se trata como coincidencia 1.0.
    """
    if newmi.is_null('title'):
        ts = 1.0
    else:
        ts = title_similarity(oldmi.title, newmi.title)

    if newmi.is_null('authors'):
        asim = 1.0
    else:
        asim = author_similarity(oldmi.authors or [], newmi.authors or [])

    ok_author = (asim >= author_thr) if require_author else True
    seguro = (ts >= title_thr) and ok_author
    return seguro, ts, asim
