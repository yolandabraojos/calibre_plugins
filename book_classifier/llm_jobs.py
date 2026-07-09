# -*- coding: utf-8 -*-
"""
Rescate con IA en la nube como TAREA DE CALIBRE (ThreadedJob).

IMPORTANTE (patron de all_libraries_stats/jobs.py): el job corre en un hilo del
gestor de tareas y NO debe tocar la base de datos ni objetos Qt (hacerlo crashea
con "Cannot set parent, new parent is in a different thread"). Por eso los datos
de los libros se LEEN antes, en el hilo de la GUI (en action._run_llm_rescue), y
aqui solo se hace red + calculo. Las escrituras se aplican luego en el callback.

Recoge los libros que el clasificador local dejo sin resolver ('[REVISAR]' o
'(sin datos)') — o TODOS si force_all — y los manda en lotes al LLM. Solo
reescribe los que el LLM resuelve con confianza.
"""
from __future__ import unicode_literals, division, absolute_import, print_function

import re
import time
import math
import traceback

from calibre_plugins.book_classifier.ml_jobs import _merge_prefixed


def _is_residue(lib_value):
    """True si el valor de libreria es del plugin pero sin resolver."""
    if not lib_value:
        return False
    v = str(lib_value).strip()
    return ('[REVISAR]' in v) or v.endswith('(sin datos)')


def _do_rescue(books, settings, progress, is_cancelled):
    """
    Nucleo del rescate. NO toca base de datos ni Qt: recibe `books`, una lista de
    dicts YA leidos en el hilo de la GUI, cada uno con:
      id, title, authors(list), comments(str), tags(list),
      lib_value (valor actual de la libreria, para detectar residuo),
      prev (dict campo_destino -> valor actual, para fundir al escribir)
    Devuelve el dict de resultado (incluye 'writes_by_field').
    """
    s = settings
    result = {
        'total': len(books), 'candidates': 0, 'rescued': 0,
        'errors': 0, 'cancelled': False, 'writes_by_field': {},
        'dist': {}, 'book_details': [], 'failed': False, 'error': '',
        'first_error': '',
    }

    provider  = s.get('llm_provider', 'glm')
    key       = (s.get('llm_api_key') or '').strip()
    model     = (s.get('llm_model') or '').strip() or None
    batch_sz  = int(s.get('llm_batch', 10) or 10)
    min_conf  = float(s.get('llm_min_conf', 0.55) or 0.55)
    write_temas = s.get('llm_write_temas', True)
    force     = bool(s.get('force_all', False))

    lib_field   = s.get('library_field', 'tags')
    mood_field  = s.get('mood_field', 'tags')
    lib_prefix  = s.get('library_prefix', 'Biblioteca: ')
    mood_prefix = s.get('mood_prefix', 'Tema: ')
    overwrite   = s.get('overwrite', True)
    lib_prefix_eff  = lib_prefix if lib_field == 'tags' else ''
    mood_prefix_eff = mood_prefix if mood_field == 'tags' else ''

    if provider != 'local' and not key:
        result['failed'] = True
        result['error'] = ('No hay clave de API configurada. Ponla en '
                           'Configurar plugin -> Rescate con IA.')
        return result

    temas_vocab = []
    if write_temas:
        try:
            from calibre_plugins.book_classifier.ml_classifier import _load_json
            temas_vocab = list((_load_json('mood_rules.json') or {}).keys())
        except Exception:
            temas_vocab = []

    from calibre_plugins.book_classifier import llm_rescue_engine as eng
    try:
        _kind, _dmodel, _base = eng.PROVIDERS.get(provider, ('', model or '?', '?'))
    except Exception:
        _dmodel, _base = (model or '?'), '?'
    result['provider'] = provider
    result['model_used'] = model or _dmodel
    result['base_used'] = _base
    result['lib_field'] = lib_field
    result['with_value'] = 0
    result['sample'] = []

    # ── PASO 1: seleccionar candidatos (datos ya leidos, sin tocar la BD) ─────
    total = len(books)
    cand = []
    for i, bk in enumerate(books, 1):
        if is_cancelled():
            result['cancelled'] = True
            break
        lib_value = bk.get('lib_value')
        if lib_value:
            result['with_value'] += 1
            if len(result['sample']) < 4:
                result['sample'].append(repr(lib_value)[:70])
        if not force and not _is_residue(lib_value):
            continue
        tags = bk.get('tags') or []
        comments = re.sub(r'<[^>]+>', ' ', bk.get('comments') or '')
        comments = re.sub(r'\s+', ' ', comments).strip()
        item = {
            'titulo': bk.get('title') or 'Sin titulo',
            'autor': ', '.join(bk.get('authors') or []),
            'sinopsis': comments,
            'tags': ', '.join(str(t) for t in tags
                              if not str(t).startswith(lib_prefix_eff)
                              and not str(t).startswith(mood_prefix_eff)),
        }
        cand.append((bk, item))
        if i % 50 == 0 or i == total:
            progress(0.0, 'Analizando libros: {}/{}'.format(i, total))

    result['candidates'] = len(cand)
    if not cand or result['cancelled']:
        return result

    # ── PASO 2: rescatar en lotes (solo red; escrituras en memoria) ───────────
    writes = result['writes_by_field']
    nbatches = int(math.ceil(len(cand) / float(max(batch_sz, 1))))
    done = 0
    for b in range(0, len(cand), batch_sz):
        if is_cancelled():
            result['cancelled'] = True
            break
        lote = cand[b:b + batch_sz]
        items = [c[1] for c in lote]
        bi = b // batch_sz + 1
        progress(done / float(len(cand)),
                 'IA lote {}/{} ({}/{} libros) - llamando al modelo...'.format(
                     bi, nbatches, done, len(cand)))
        try:
            res_list = eng.classify_batch(
                items, provider, key, model=model,
                temas_vocab=temas_vocab, librerias=eng.LIBRERIAS,
                min_conf=min_conf)
        except Exception as e:
            if not result['first_error']:
                result['first_error'] = str(e)
                print('[LLM RESCUE] primer error:', e)
            result['errors'] += len(lote)
            done += len(lote)
            continue

        for (bk, item), r in zip(lote, res_list):
            lib = r.get('libreria')
            if not lib or lib == eng.REVISAR:
                continue
            temas = r.get('temas') or []
            bid = bk['id']
            new_by_field = {}
            new_by_field.setdefault(lib_field, []).append(lib_prefix_eff + lib)
            if write_temas and temas:
                new_by_field.setdefault(mood_field, []).extend(
                    mood_prefix_eff + m for m in temas)
            for field, newvals in new_by_field.items():
                prev = (bk.get('prev') or {}).get(field)
                own_prefixes = []
                if field == lib_field:
                    own_prefixes.append(lib_prefix_eff)
                if write_temas and field == mood_field:
                    own_prefixes.append(mood_prefix_eff)
                merged = _merge_prefixed(newvals, prev, field, own_prefixes, overwrite)
                writes.setdefault(field, {})[bid] = merged
            result['rescued'] += 1
            result['dist'][lib] = result['dist'].get(lib, 0) + 1
            if len(result['book_details']) < 400:
                result['book_details'].append({
                    'title': bk.get('title') or '', 'library': lib,
                    'confidence': round(float(r.get('confianza', 0)), 3),
                    'uncertain': False, 'moods': temas, 'tier': 'IA',
                })
        done += len(lote)
        progress(done / float(len(cand)),
                 'IA lote {}/{} completado ({}/{} libros)'.format(
                     bi, nbatches, min(done, len(cand)), len(cand)))
        time.sleep(1.0)

    return result


def run_rescue_task(books, settings, log=None, abort=None, notifications=None):
    """Tarea para el ThreadedJob de Calibre. Calibre inyecta log/abort/
    notifications como keyword args (mismo patron que all_libraries_stats/jobs.py).
    NO toca la base de datos: `books` ya viene leido del hilo de la GUI."""
    def progress(frac, msg):
        if notifications is not None:
            try:
                notifications.put((float(max(0.0, min(1.0, frac))), msg))
            except Exception:
                pass

    def is_cancelled():
        try:
            return bool(abort is not None and abort.is_set())
        except Exception:
            return False

    return _do_rescue(books, settings, progress, is_cancelled)
