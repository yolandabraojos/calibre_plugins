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
import unicodedata

from calibre_plugins.book_classifier.ml_jobs import _merge_prefixed


def _norm_txt(v):
    """Normaliza para comparar: minusculas, sin acentos, espacios colapsados."""
    s = '' if v is None else str(v)
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return ' '.join(s.lower().split())


def _is_residue(lib_value):
    """True si el valor de libreria es del plugin pero sin resolver."""
    if not lib_value:
        return False
    v = str(lib_value).strip()
    return ('[REVISAR]' in v) or v.endswith('(sin datos)')


# Prefijos "en crudo" (formato PRE-fix_metadata: jerarquia con puntos) que
# codifican directamente la libreria/genero. fix_metadata los canoniza a
# 'Genero · X', pero un libro que aun no ha pasado por fix_metadata puede
# conservarlos tal cual.
_LEAK_RAW_PREFIX_RE = re.compile(
    r'^(_?Biblioteca\.|_?Libreria\.|English\.|Spanish\.|Temas\.|Themes\.|FICTION/)',
    re.IGNORECASE)

# Grupos canonicos 'Grupo · Valor' (ver fix_metadata/tags_map.json) que
# codifican la libreria/genero de forma practicamente 1:1. OJO: fix_metadata
# canoniza TODA la taxonomia (Subgenero/Ambientacion/Tono/Dinamica/Arquetipo/
# Paranormal incluidos) al mismo separador ' · ', asi que ya NO vale usar
# "contiene ·" como señal de fuga -eso descartaria tambien las tags de tropos/
# ambientacion, que son señal legitima y no repiten la clase-. Solo el grupo
# 'Genero' (y los alias estructurales Biblioteca/Libreria) equivale a la
# propia etiqueta #libreria.
_LEAK_GROUPS = ('genero', 'biblioteca', 'libreria')


def _leak_group(tag):
    """Grupo normalizado (sin acentos, minusculas) de una tag canonica
    'Grupo · Valor'; '' si la tag no tiene ese formato."""
    t = str(tag or '')
    if '·' not in t:
        return ''
    grupo = t.split('·', 1)[0].strip()
    grupo = unicodedata.normalize('NFKD', grupo)
    grupo = ''.join(c for c in grupo if not unicodedata.combining(c))
    return grupo.lower()


def _is_leak_tag(tag):
    """True si la tag equivale a la propia libreria/genero que se le pide a
    la IA (grupo 'Genero'/'Biblioteca'/'Libreria' en formato canonico, o el
    prefijo en crudo pre-fix_metadata). Mismo criterio de fuga que en el
    reentrenamiento (ver memory/book-classifier-retrain.md), pero acotado al
    grupo que de verdad es circular: si se manda tal cual a la IA de rescate
    como contexto, puede sesgar #libreria hacia lo que ya diga (a veces mal)
    una tag anterior en vez de basarse en la sinopsis. Las demas tags
    canonicas (Subgenero/Ambientacion/Tono/Dinamica/Arquetipo/Paranormal) NO
    se filtran: son señal de contenido derivada del texto, no un eco de la
    clase.
    """
    t = str(tag or '').strip()
    if not t:
        return False
    if _leak_group(t) in _LEAK_GROUPS:
        return True
    return bool(_LEAK_RAW_PREFIX_RE.match(t))


def select_rescue_candidates(books, settings):
    """
    PASO 1 (puro, sin red ni BD ni Qt: puede llamarse desde el hilo de la
    GUI, es rapido). Filtra `books` (ya leidos de la BD en
    action._prefetch_books) a los que hay que mandar al LLM -residuo
    '[REVISAR]'/'(sin datos)', o TODOS si force_all-. Devuelve (candidatos,
    diag): candidatos es una lista de tuplas (bk, item) lista para
    `classify_batch`; diag trae 'with_value' y 'sample' para el diagnostico
    cuando no se encuentra ningun candidato.
    """
    s = settings
    force = bool(s.get('force_all', False))
    lib_field  = s.get('library_field', 'tags')
    mood_field = s.get('mood_field', 'tags')
    lib_prefix  = s.get('library_prefix', 'Biblioteca: ')
    mood_prefix = s.get('mood_prefix', 'Tema: ')
    lib_prefix_eff  = lib_prefix if lib_field == 'tags' else ''
    mood_prefix_eff = mood_prefix if mood_field == 'tags' else ''

    diag = {'with_value': 0, 'sample': []}
    cand = []
    for bk in books:
        lib_value = bk.get('lib_value')
        if lib_value:
            diag['with_value'] += 1
            if len(diag['sample']) < 4:
                diag['sample'].append(repr(lib_value)[:70])
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
                              and not str(t).startswith(mood_prefix_eff)
                              and not _is_leak_tag(t)),
        }
        cand.append((bk, item))

    # Deduplicacion: agrupa copias con el mismo autor+titulo+idioma y manda a la
    # IA UN SOLO representante por grupo (el de sinopsis mas larga). El resultado
    # se aplica luego a todas las copias del grupo (ver run_rescue_batch_task).
    groups = {}
    order = []
    for bk, item in cand:
        key = (_norm_txt(item.get('autor')),
               _norm_txt(item.get('titulo')),
               _norm_txt(bk.get('idioma')))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append((bk, item))
    deduped = []
    for key in order:
        members = groups[key]
        rep_bk, rep_item = max(
            members, key=lambda mi: len(mi[1].get('sinopsis') or ''))
        rep_bk = dict(rep_bk)
        rep_bk['dup_group'] = [m[0] for m in members]
        deduped.append((rep_bk, rep_item))
    diag['groups'] = len(deduped)
    diag['duplicates_saved'] = len(cand) - len(deduped)
    return deduped, diag


def plan_rescue_chunks(cand, settings):
    """
    Reparte los candidatos YA filtrados en varios jobs -en vez de uno solo
    con todos-, de hasta 2x el tamano de lote configurado (`llm_batch`, el
    "libros por llamada"): cada job hace 1-2 llamadas a la IA y aplica sus
    cambios en cuanto termina, sin esperar a los demas.
    """
    batch_sz = int(settings.get('llm_batch', 10) or 10)
    job_size = max(batch_sz, 1) * 2
    chunks = []
    for i in range(0, len(cand), job_size):
        part = cand[i:i + job_size]
        chunks.append({'cand': part, 'label': 'lote {}-{}'.format(i + 1, i + len(part))})
    return chunks


def run_rescue_batch_task(cand, settings, label, log=None, abort=None, notifications=None):
    """
    Tarea de ThreadedJob para UN job del rescate: procesa un trozo YA
    filtrado de candidatos (de `select_rescue_candidates`), llamando a la IA
    en sub-lotes de `llm_batch`. Varios de estos jobs corren por separado
    -uno tras otro- en vez de un unico job gigante con todos los libros, asi
    que cada uno aplica sus escrituras en cuanto termina.
    """
    s = settings
    result = {
        'label': label, 'candidates': len(cand), 'rescued': 0, 'errors': 0,
        'cancelled': False, 'writes_by_field': {}, 'dist': {},
        'book_details': [], 'failed': False, 'error': '', 'first_error': '',
        'reason_writes': {}, 'serie_writes': {}, 'conf_writes': {},
    }

    provider  = s.get('llm_provider', 'glm')
    key       = (s.get('llm_api_key') or '').strip()
    model     = (s.get('llm_model') or '').strip() or None
    batch_sz  = int(s.get('llm_batch', 10) or 10)
    min_conf  = float(s.get('llm_min_conf', 0.55) or 0.55)
    write_temas  = s.get('llm_write_temas', True)
    write_reason = s.get('llm_write_reason', True)
    reason_field = (s.get('llm_reason_field') or '').strip()
    write_serie  = s.get('llm_write_serie', True)
    write_conf   = s.get('llm_write_conf', True)

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

    def is_cancelled():
        try:
            return bool(abort is not None and abort.is_set())
        except Exception:
            return False

    def progress(frac, msg):
        if notifications is not None:
            try:
                notifications.put((float(max(0.0, min(1.0, frac))), msg))
            except Exception:
                pass

    writes = result['writes_by_field']
    total = len(cand)
    nbatches = int(math.ceil(total / float(max(batch_sz, 1))))
    done = 0
    for b in range(0, total, batch_sz):
        if is_cancelled():
            result['cancelled'] = True
            break
        lote = cand[b:b + batch_sz]
        items = [c[1] for c in lote]
        bi = b // batch_sz + 1
        progress(done / float(max(total, 1)),
                 '{}: lote {}/{} ({}/{} libros) - llamando al modelo...'.format(
                     label, bi, nbatches, done, total))
        try:
            res_list = eng.classify_batch(
                items, provider, key, model=model,
                temas_vocab=temas_vocab, librerias=eng.LIBRERIAS,
                min_conf=min_conf, pedir_serie=write_serie)
        except Exception as e:
            tb = traceback.format_exc()
            if not result['first_error']:
                result['first_error'] = '{}: {}\n{}'.format(type(e).__name__, e, tb)
                print('[LLM RESCUE] primer error ({}):'.format(label), e)
                print(tb)
            result['errors'] += len(lote)
            done += len(lote)
            continue

        for (bk, item), r in zip(lote, res_list):
            lib = r.get('libreria')
            resolved = bool(lib) and lib != eng.REVISAR
            temas = r.get('temas') or []
            motivo = (r.get('motivo') or '').strip()
            serie = (r.get('serie') or '').strip() if write_serie else ''
            try:
                conf_pct = int(round(float(r.get('confianza', 0) or 0) * 100))
            except (ValueError, TypeError):
                conf_pct = None
            # Aplica el MISMO resultado a todas las copias del grupo (dedup).
            # % de confianza y motivo se guardan SIEMPRE que la IA responda algo,
            # aunque no llegue al umbral y no se toquen libreria/temas -asi se
            # puede analizar el residuo "(revisar)" sin perder la senal de la IA.
            for m in (bk.get('dup_group') or [bk]):
                bid = m['id']
                if resolved:
                    new_by_field = {}
                    new_by_field.setdefault(lib_field, []).append(lib_prefix_eff + lib)
                    if write_temas and temas:
                        new_by_field.setdefault(mood_field, []).extend(
                            mood_prefix_eff + t for t in temas)
                    for field, newvals in new_by_field.items():
                        prev = (m.get('prev') or {}).get(field)
                        own_prefixes = []
                        if field == lib_field:
                            own_prefixes.append(lib_prefix_eff)
                        if write_temas and field == mood_field:
                            own_prefixes.append(mood_prefix_eff)
                        merged = _merge_prefixed(newvals, prev, field, own_prefixes, overwrite)
                        writes.setdefault(field, {})[bid] = merged
                    if write_serie and serie:
                        result['serie_writes'][bid] = serie
                    result['rescued'] += 1
                    result['dist'][lib] = result['dist'].get(lib, 0) + 1
                if write_reason and reason_field and motivo:
                    result['reason_writes'][bid] = motivo[:300]
                if write_conf and conf_pct is not None:
                    result['conf_writes'][bid] = conf_pct
                if len(result['book_details']) < 400:
                    result['book_details'].append({
                        'title': m.get('title') or '', 'library': lib or eng.REVISAR,
                        'confidence': round(float(r.get('confianza', 0) or 0), 3),
                        'uncertain': not resolved, 'moods': temas, 'tier': 'IA',
                        'motivo': motivo,
                    })
        done += len(lote)
        progress(done / float(max(total, 1)),
                 '{}: lote {}/{} completado ({}/{} libros)'.format(
                     label, bi, nbatches, min(done, total), total))
        if b + batch_sz < total:
            time.sleep(1.0)

    return result
