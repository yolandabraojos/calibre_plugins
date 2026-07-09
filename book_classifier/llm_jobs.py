# -*- coding: utf-8 -*-
"""
Rescate con IA en la nube como TAREA DE CALIBRE (ThreadedJob).

Corre en el gestor de tareas de Calibre: aparece en la lista de trabajos
(abajo a la derecha), se puede cancelar desde ahí y NO bloquea la interfaz —
puedes seguir usando Calibre mientras rescata.

Recoge los libros que el clasificador local dejó sin resolver ('[REVISAR]' o
'(sin datos)'), lee su sinopsis real, y los manda en lotes al LLM. Solo
reescribe los que el LLM resuelve con confianza. Las escrituras a la base se
aplican en el callback (hilo de GUI), no aquí.
"""
from __future__ import unicode_literals, division, absolute_import, print_function

import re
import time
import math
import traceback

from calibre_plugins.book_classifier.ml_jobs import _merge_prefixed


def _is_residue(lib_value):
    """True si el valor de librería es del plugin pero sin resolver."""
    if not lib_value:
        return False
    v = str(lib_value).strip()
    return ('[REVISAR]' in v) or v.endswith('(sin datos)')


def _do_rescue(db, book_ids, settings, progress, is_cancelled):
    """
    Núcleo del rescate, independiente de Qt/Calibre.
      progress(frac_0_a_1, mensaje)   -> informar avance
      is_cancelled() -> bool          -> ¿cancelar?
    Devuelve el dict de resultado (incluye 'writes_by_field').
    """
    s = settings
    result = {
        'total': len(book_ids), 'candidates': 0, 'rescued': 0,
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
    force = bool(s.get('force_all', False))

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

    # ── PASO 1: localizar el residuo y leer su texto real ─────────────────────
    total = len(book_ids)
    cand = []
    for i, bid in enumerate(book_ids, 1):
        if is_cancelled():
            result['cancelled'] = True
            break
        try:
            mi = db.get_proxy_metadata(bid)
            title = mi.title or 'Sin título'
            if i % 25 == 0 or i == total:
                progress(0.0, 'Analizando biblioteca: {}/{}'.format(i, total))

            tags = list(mi.tags) if mi.tags else []
            if lib_field == 'tags':
                lib_value = None
                for t in tags:
                    if str(t).startswith(lib_prefix_eff):
                        lib_value = str(t)
                        break
            else:
                try:
                    lib_value = db.field_for(lib_field, bid)
                except Exception:
                    lib_value = None

            if lib_value:
                result['with_value'] += 1
                if len(result['sample']) < 4:
                    result['sample'].append(repr(lib_value)[:70])
            if not force and not _is_residue(lib_value):
                continue

            authors = [a for a in (list(mi.authors) if mi.authors else []) if a]
            comments = re.sub(r'<[^>]+>', ' ', mi.comments) if mi.comments else ''
            comments = re.sub(r'\s+', ' ', comments).strip()
            item = {
                'titulo': title,
                'autor': ', '.join(authors),
                'sinopsis': comments,
                'tags': ', '.join(str(t) for t in tags
                                  if not str(t).startswith(lib_prefix_eff)
                                  and not str(t).startswith(mood_prefix_eff)),
            }
            cand.append((bid, title, item, tags))
        except Exception as e:
            print('LLM RESCUE (paso 1) libro {}: {}'.format(bid, e))
            traceback.print_exc()
            result['errors'] += 1

    result['candidates'] = len(cand)
    if not cand or result['cancelled']:
        return result

    # ── PASO 2: rescatar en lotes ─────────────────────────────────────────────
    writes = result['writes_by_field']
    nbatches = int(math.ceil(len(cand) / float(max(batch_sz, 1))))
    done = 0
    for b in range(0, len(cand), batch_sz):
        if is_cancelled():
            result['cancelled'] = True
            break
        lote = cand[b:b + batch_sz]
        items = [c[2] for c in lote]
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

        for (bid, title, item, tags), r in zip(lote, res_list):
            lib = r.get('libreria')
            if not lib or lib == eng.REVISAR:
                continue
            temas = r.get('temas') or []
            new_by_field = {}
            new_by_field.setdefault(lib_field, []).append(lib_prefix_eff + lib)
            if write_temas and temas:
                new_by_field.setdefault(mood_field, []).extend(
                    mood_prefix_eff + m for m in temas)
            for field, newvals in new_by_field.items():
                prev = list(tags) if field == 'tags' else db.field_for(field, bid)
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
                    'title': title, 'library': lib,
                    'confidence': round(float(r.get('confianza', 0)), 3),
                    'uncertain': False, 'moods': temas, 'tier': 'IA',
                })
        done += len(lote)
        progress(done / float(len(cand)),
                 'IA lote {}/{} completado ({}/{} libros)'.format(
                     bi, nbatches, min(done, len(cand)), len(cand)))
        time.sleep(1.0)

    return result


def run_rescue_job(first, *rest):
    """Punto de entrada del ThreadedJob. Es defensivo respecto a si Calibre
    inyecta el objeto job como primer argumento o no."""
    if hasattr(first, 'abort') and hasattr(first, 'notifications'):
        job = first
        gui, book_ids, settings = rest
    else:
        job = None
        gui, book_ids, settings = (first,) + tuple(rest)

    def progress(frac, msg):
        if job is None:
            return
        try:
            job.notifications.put((float(max(0.0, min(1.0, frac))), msg))
        except Exception:
            pass

    def is_cancelled():
        if job is None:
            return False
        try:
            return job.abort.is_set()
        except Exception:
            return False

    db = gui.current_db.new_api
    return _do_rescue(db, book_ids, settings, progress, is_cancelled)


def run_rescue_task(gui, book_ids, settings, log=None, abort=None, notifications=None):
    """Tarea para el ThreadedJob de Calibre. Calibre inyecta log/abort/
    notifications como keyword args (mismo patron que all_libraries_stats/jobs.py).
    Corre en un hilo del gestor de tareas: no bloquea la GUI y es cancelable.
    Las escrituras a la base se aplican en el callback (hilo de GUI)."""
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

    db = gui.current_db.new_api
    return _do_rescue(db, book_ids, settings, progress, is_cancelled)
