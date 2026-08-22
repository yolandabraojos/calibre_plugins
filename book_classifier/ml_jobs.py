# -*- coding: utf-8 -*-
"""
Worker en segundo plano para la clasificación con IA local (modelo entrenado).

Niveles de decisión de librería (de más a menos fiable):
  0) PROMOCIÓN DESDE LA IA EN LA NUBE (opcional, `llm_promote_enabled`): si el
     libro ya tiene un valor en el campo DEDICADO del rescate LLM
     (`llm_library_field`, ver `llm_jobs.py`) con confianza muy alta
     (`llm_promote_threshold`), se usa tal cual. Solo LEE ese campo, nunca
     escribe en él — lo único que escribe este módulo es el campo principal
     (`ml_library_field`).
  1) Predicción individual del modelo, si supera el umbral de confianza.
  2) CONSENSO DE GRUPO: libros del mismo universo (#universe) o, en su defecto,
     misma serie → todos la librería de mayor confianza sumada del grupo.
     (Puede sobreescribir también un libro resuelto por el nivel 0.)
  3) CONSENSO DE AUTOR (opcional): si un libro sigue dudoso, hereda la librería
     dominante del autor, siempre que el autor tenga una mayoría clara.
Si nada de eso resuelve, queda "(revisar)".

Los tags de tema (eje 2) se unifican por grupo si se activa.
"""
from __future__ import unicode_literals, division, absolute_import, print_function

import re
import traceback

def _group_key(db, bid, settings):
    """Universo si existe; si no, serie. None si no aplica (libro suelto)."""
    if not settings.get('group_unify', True):
        return None
    universe_field = settings.get('universe_field', '#universe')
    try:
        universe = db.field_for(universe_field, bid)
        universe = (universe or '').strip() if isinstance(universe, str) else (universe or '')
    except Exception:
        universe = ''
    if universe:
        return ('U', universe)
    try:
        series = (db.field_for('series', bid) or '').strip()
    except Exception:
        series = ''
    if series:
        return ('S', series)
    return None


def _llm_promoted_library(db, bid, settings, stats=None):
    """
    Nivel adicional (promocion): lee -nunca escribe- el campo DEDICADO de la
    IA en la nube (`llm_library_field`, escrito solo por
    `llm_jobs.run_rescue_batch_task`) y su confianza (`llm_conf_field`,
    entero 0-100). Si hay valor y su confianza supera `llm_promote_threshold`
    (mas estricto que `llm_min_conf`, que solo decide si el rescate resuelve
    el residuo), devuelve (libreria, confianza_0_1) para usarlo tal cual como
    clasificacion de este libro. Devuelve None si no aplica. NUNCA escribe en
    `llm_library_field` -eso lo dejaria contaminado con datos que no vienen
    de la IA-.
    """
    lib_field = (settings.get('llm_library_field') or '').strip()
    if not lib_field:
        return None
    try:
        raw = db.field_for(lib_field, bid)
    except Exception:
        return None
    if lib_field != 'tags' and isinstance(raw, (list, tuple)):
        # Columna PROPIA multivalor: el valor entero es de la IA, no lleva
        # prefijo. Buscarlo dejaba `value` a None y la promocion no ocurria
        # nunca con ese tipo de columna.
        value = next((str(v).strip() for v in raw if str(v).strip()), None)
    elif lib_field == 'tags' or isinstance(raw, (list, tuple)):
        prefix = settings.get('llm_library_prefix', 'Biblioteca IA: ')
        value = None
        for v in (raw or []):
            v = str(v)
            if v.startswith(prefix):
                value = v[len(prefix):].strip()
                break
    else:
        value = (raw or '').strip() if isinstance(raw, str) else (raw or None)
    if not value:
        return None

    conf_field = (settings.get('llm_conf_field') or '').strip()
    if not conf_field:
        return None
    try:
        conf_raw = db.field_for(conf_field, bid)
        conf_frac = float(conf_raw) / 100.0 if conf_raw is not None else 0.0
    except Exception:
        return None

    threshold = settings.get('llm_promote_threshold', 0.90)
    if conf_frac < threshold:
        return None

    # El valor se VALIDA contra el catalogo actual (desde 3.17.0). Antes se
    # copiaba literal, asi que un nombre de un catalogo anterior guardado en
    # el campo de la IA -p.ej. 'Misterio·Thriller·Terror' despues de trocearlo-
    # resucitaba en el campo principal en la siguiente clasificacion local, y
    # habia que acordarse de re-rescatar ANTES de clasificar. `norm_libreria`
    # ademas canoniza: 'Ciencia Ficcion' sin tilde o 'Misterio' a secas entran
    # como el nombre exacto del catalogo.
    try:
        from calibre_plugins.book_classifier import llm_rescue_engine as eng
    except Exception:
        return None   # sin catalogo no se promociona: mejor eso que copiar mal
    canonico = eng.norm_libreria(value)
    if canonico == eng.REVISAR:
        if stats is not None:
            stats['promocion_nombre_invalido'] = \
                stats.get('promocion_nombre_invalido', 0) + 1
            malos = stats.setdefault('promocion_nombres', {})
            clave = str(value)[:40]
            malos[clave] = malos.get(clave, 0) + 1
        return None
    return canonico, conf_frac


def _llm_promoted_temas(db, bid, settings, vocab):
    """Temas que la IA guardo en su campo propio (`llm_temas_field`), listos
    para SUSTITUIR a los que detecta el motor local por regex.

    Mismo nivel 0 que la libreria y con el mismo liston (`llm_conf_field` /
    100 >= `llm_promote_threshold`): los temas no traen confianza propia -son
    multietiqueta-, pero si la IA entendio mal el libro sus temas tampoco
    valen. Solo LEE el campo de la IA, nunca escribe en el.

    Se validan contra el vocabulario ACTUAL de mood_rules.json: un nombre de
    una version anterior del vocabulario (los 11 que se desdoblaron en 3.10.0)
    no debe resucitar en el campo bueno. Devuelve [] si no aplica.
    """
    if not settings.get('llm_promote_temas_enabled', True):
        return []
    campo = (settings.get('llm_temas_field') or '').strip()
    if not campo or not vocab:
        return []
    try:
        raw = db.field_for(campo, bid)
    except Exception:
        return []
    prefijo = (settings.get('llm_temas_prefix', 'Tema IA: ')
               if campo == 'tags' else '')
    valores = []
    if isinstance(raw, (list, tuple)):
        for v in raw:
            v = str(v)
            if prefijo:
                if not v.startswith(prefijo):
                    continue
                v = v[len(prefijo):]
            valores.append(v.strip())
    elif isinstance(raw, str):
        valores = [x.strip() for x in raw.split(',') if x.strip()]
    valores = [v for v in valores if v]
    if not valores:
        return []

    conf_field = (settings.get('llm_conf_field') or '').strip()
    if not conf_field:
        return []
    try:
        conf_raw = db.field_for(conf_field, bid)
        conf_frac = float(conf_raw) / 100.0 if conf_raw is not None else 0.0
    except Exception:
        return []
    if conf_frac < settings.get('llm_promote_threshold', 0.90):
        return []

    try:
        from calibre_plugins.book_classifier import llm_rescue_engine as eng
        return eng.norm_temas(valores, vocab)
    except Exception:
        return [v for v in valores if v in vocab]


def plan_classify_chunks(gui, book_ids, settings):
    """
    Agrupa book_ids por serie/universo (lectura rapida en el hilo de la GUI) y
    reparte el trabajo en chunks -uno por ThreadedJob-, empaquetando varios
    grupos pequenos juntos para que ningun job sea demasiado chico ni
    demasiado grande:

      - Cada serie/universo se mantiene ENTERA dentro de un mismo chunk (el
        consenso de grupo necesita verla completa), pero un chunk puede
        contener VARIAS series/universos pequenos juntos.
      - El tamano de referencia es `ai_batch_ref` (el "libros por llamada"
        configurado para el rescate con IA en la nube, reutilizado aqui solo
        como unidad de medida -esta clasificacion es local, no llama a
        ningun proveedor-). Los chunks apuntan a ese tamano y no superan
        2x, salvo que una sola serie/universo ya sea mas grande que eso
        (entonces ocupa su propio chunk igualmente, no se puede partir sin
        romper el consenso).
      - Los libros sueltos (sin serie/universo) rellenan el hueco de los
        chunks de grupos y, lo que sobre, se reparte en chunks de ese mismo
        tamano maximo, sin consenso entre ellos.

    Devuelve una lista de chunks: [{'subgroups', 'loose_ids', 'book_ids',
    'label'}, ...]. `subgroups` es una lista de listas de book_id (cada una
    una serie/universo completa); `loose_ids` son libros sin grupo metidos en
    ese mismo job para no desperdiciar hueco.
    """
    db = gui.current_db.new_api
    groups = {}
    standalone = []
    for bid in book_ids:
        gkey = _group_key(db, bid, settings)
        if gkey is not None:
            groups.setdefault(gkey, []).append(bid)
        else:
            standalone.append(bid)

    batch = int(settings.get('ai_batch_ref', 10) or 10)
    target_max = max(batch, 1) * 2

    group_items = sorted(groups.items(), key=lambda kv: -len(kv[1]))
    standalone_pool = list(standalone)

    chunks = []
    cur_groups, cur_labels, cur_size = [], [], 0

    def _label_for(labels, size):
        if not labels:
            return 'Sueltos ({} libros)'.format(size)
        if len(labels) <= 3:
            return ' + '.join(labels)
        return '{} series/universos ({} libros)'.format(len(labels), size)

    def _take_filler(room):
        if room <= 0 or not standalone_pool:
            return []
        part = standalone_pool[:room]
        del standalone_pool[:len(part)]
        return part

    def _flush():
        nonlocal cur_groups, cur_labels, cur_size
        if not cur_groups:
            return
        filler = _take_filler(target_max - cur_size)
        chunks.append({
            'subgroups': list(cur_groups),
            'loose_ids': filler,
            'book_ids': [bid for g in cur_groups for bid in g] + filler,
            'label': _label_for(cur_labels, cur_size + len(filler)),
        })
        cur_groups, cur_labels, cur_size = [], [], 0

    for gkey, ids in group_items:
        label = '{}: {}'.format('Universo' if gkey[0] == 'U' else 'Serie', gkey[1])
        if cur_groups and cur_size + len(ids) > target_max:
            _flush()
        cur_groups.append(ids)
        cur_labels.append(label)
        cur_size += len(ids)
        if cur_size >= target_max:
            _flush()
    _flush()

    for i in range(0, len(standalone_pool), target_max):
        part = standalone_pool[i:i + target_max]
        chunks.append({
            'subgroups': [], 'loose_ids': part, 'book_ids': part,
            'label': 'Sueltos {}-{}'.format(i + 1, i + len(part)),
        })
    return chunks


def run_classify_chunk_task(db, subgroups, loose_ids, settings, label,
                            log=None, abort=None, notifications=None):
    """
    Tarea de ThreadedJob para UN job de clasificacion local. `subgroups` es
    una lista de listas de book_id -cada una una serie/universo COMPLETA-: el
    consenso de grupo (Nivel 2) se calcula por separado DENTRO de cada una,
    nunca mezclando series distintas aunque compartan el mismo job.
    `loose_ids` son libros sin grupo metidos en el mismo job para no
    desperdiciar hueco: cada uno conserva su propia prediccion individual,
    sin consenso. El consenso de autor (Nivel 3) se hace aparte, en una
    pasada final tras acabar TODOS los jobs (ver `run_author_fallback_task`).

    Lee la base de datos (permitido desde un ThreadedJob: leer esta bien, lo
    que hay que evitar desde este hilo es escribir en la BD o tocar objetos
    Qt -eso se hace en el callback, en el hilo de la GUI-).
    """
    import re
    import traceback as _tb
    from calibre_plugins.book_classifier.ml_classifier import MLClassifier

    # El ThreadedJob puede recibir la BD antigua (LibraryDatabase); los metodos
    # get_proxy_metadata/field_for viven en la API nueva (Cache). Normalizamos.
    db = getattr(db, 'new_api', db)

    s = settings
    all_ids = [bid for g in subgroups for bid in g] + list(loose_ids)
    result = {
        'label': label, 'total': len(all_ids), 'classified': 0, 'errors': 0,
        'writes_by_field': {}, 'dist': {}, 'unified_books': 0,
        'group_count': 0, 'book_details': [], 'failed': False, 'error': '',
        'first_error': '', 'error_samples': [],
    }

    try:
        clf = MLClassifier(default_threshold=s.get('threshold', 0.55))
    except Exception as e:
        result['failed'] = True
        result['error'] = str(e)
        return result

    lib_field   = s.get('library_field', 'tags')
    mood_field  = s.get('mood_field', 'tags')
    lib_prefix  = s.get('library_prefix', 'Biblioteca: ')
    mood_prefix = s.get('mood_prefix', 'Tema: ')
    threshold   = s.get('threshold', 0.55)
    write_lib   = s.get('write_library', True)
    write_mood  = s.get('write_moods', True)
    overwrite   = s.get('overwrite', True)
    source_fields  = s.get('source_fields', ['title', 'comments', 'tags'])
    use_subtitle   = s.get('use_subtitle', False)
    subtitle_field = s.get('subtitle_field', '#subtitle')
    unify_moods    = s.get('group_unify_moods', True)

    # Vocabulario ACTUAL de temas, para validar los que venga de la IA (ver
    # _llm_promoted_temas). Sale del propio clasificador, que ya cargo
    # mood_rules.json, asi que no se relee el fichero.
    try:
        vocab_temas = list(getattr(clf, 'mood_desc', {}).keys()) or \
            [n for n, _rx in getattr(clf, '_mood', [])]
    except Exception:
        vocab_temas = []

    # ── Pasada 1: clasificacion individual de TODOS los libros del job ───────
    per_book = {}
    total = len(all_ids)
    for i, bid in enumerate(all_ids, 1):
        if abort is not None and abort.is_set():
            break
        try:
            mi = db.get_proxy_metadata(bid)
            title = mi.title or 'Sin titulo'
            if notifications is not None:
                try:
                    notifications.put((i / float(max(total, 1)), '{}: {}'.format(label, title)))
                except Exception:
                    pass

            comments = re.sub(r'<[^>]+>', ' ', mi.comments) if mi.comments else ''
            tags     = list(mi.tags) if mi.tags else []
            series   = (mi.series or '').strip()
            authors  = [a for a in (list(mi.authors) if mi.authors else []) if a]

            parts = []
            if 'title' in source_fields:    parts.append(title)
            if 'tags' in source_fields:     parts.extend(tags)
            if 'comments' in source_fields: parts.append(comments)
            if 'series' in source_fields:   parts.append(series)
            if use_subtitle:
                try:
                    sub = db.field_for(subtitle_field, bid)
                    sub = (sub or '').strip() if isinstance(sub, str) else (sub or '')
                except Exception:
                    sub = ''
                if sub:
                    parts.append(sub)
            text = ' '.join(p for p in parts if p)

            res = clf.classify(text, threshold=threshold)
            library, confidence, uncertain = res['library'], res['confidence'], res['uncertain']

            # Nivel de promocion: si hay un valor de la IA en la nube con
            # confianza muy alta en su campo DEDICADO, se usa tal cual -sin
            # tocar ese campo, solo se lee-. Se aplica ANTES del consenso de
            # grupo/autor, que pueden seguir sobreescribiendolo (misma logica
            # deliberada que para una prediccion individual bien clasificada,
            # ver COMPORTAMIENTO_PLUGIN.md).
            promoted = False
            if s.get('llm_promote_enabled', True):
                promo = _llm_promoted_library(db, bid, s, result)
                if promo is not None:
                    library, confidence = promo
                    uncertain = False
                    promoted = True

            # Los TEMAS de la IA sustituyen a los del motor local cuando la
            # confianza llega al umbral: los de la IA salen de razonar sobre
            # la sinopsis, los de regex son coincidencias literales. El campo
            # propio de la IA conserva el original, asi que es reversible.
            moods = res['moods']
            temas_ia = _llm_promoted_temas(db, bid, s, vocab_temas)
            if temas_ia:
                moods = temas_ia
                result['temas_promovidos'] = result.get('temas_promovidos', 0) + 1

            per_book[bid] = {
                'title': title, 'tags': tags, 'authors': authors,
                'library': library, 'confidence': confidence,
                'uncertain': uncertain, 'moods': moods,
                'llm_promoted': promoted,
            }
        except Exception as e:
            tb = _tb.format_exc()
            msg = '{}: {}'.format(type(e).__name__, e)
            print('ML ERROR (chunk {}) libro {}: {}'.format(label, bid, msg))
            print(tb)
            result['errors'] += 1
            if not result['first_error']:
                result['first_error'] = 'libro {}: {}\n{}'.format(bid, msg, tb)
            if len(result['error_samples']) < 8:
                result['error_samples'].append('libro {}: {}'.format(bid, msg))

    writes = result['writes_by_field']
    lib_prefix_eff  = lib_prefix if lib_field == 'tags' else ''
    mood_prefix_eff = mood_prefix if mood_field == 'tags' else ''

    def _emit(bid, pb, library, uncertain, moods, tier):
        if library is None:
            lib_value = lib_prefix_eff + '(sin datos)'
        elif uncertain:
            lib_value = lib_prefix_eff + library + ' [REVISAR]'
        else:
            lib_value = lib_prefix_eff + library

        new_by_field = {}
        if write_lib:
            new_by_field.setdefault(lib_field, []).append(lib_value)
        if write_mood and moods:
            new_by_field.setdefault(mood_field, []).extend(mood_prefix_eff + m for m in moods)

        for field, newvals in new_by_field.items():
            prev = list(pb['tags']) if field == 'tags' else db.field_for(field, bid)
            own_prefixes = []
            if write_lib and field == lib_field:
                own_prefixes.append(lib_prefix_eff)
            if write_mood and field == mood_field:
                own_prefixes.append(mood_prefix_eff)
            merged = _merge_prefixed(newvals, prev, field, own_prefixes, overwrite)
            writes.setdefault(field, {})[bid] = merged

        key = library if (library and not uncertain) else '(revisar/sin datos)'
        result['dist'][key] = result['dist'].get(key, 0) + 1
        result['classified'] += 1
        if len(result['book_details']) < 400:
            result['book_details'].append({
                'title': pb['title'], 'library': library,
                'confidence': round(pb['confidence'], 3),
                'uncertain': uncertain, 'moods': moods, 'tier': tier,
            })

    # ── Nivel 2: consenso de grupo, POR CADA subgrupo por separado ───────────
    for group_ids in subgroups:
        score = {}
        for bid in group_ids:
            pb = per_book.get(bid)
            if pb and pb['library'] and not pb['uncertain']:
                score[pb['library']] = score.get(pb['library'], 0.0) + pb['confidence']
        consensus = max(score, key=lambda k: score[k]) if score else None
        if consensus is not None:
            result['group_count'] += 1

        moods_union = []
        if unify_moods:
            for bid in group_ids:
                pb = per_book.get(bid)
                if not pb:
                    continue
                for m in pb['moods']:
                    if m not in moods_union:
                        moods_union.append(m)

        for bid in group_ids:
            pb = per_book.get(bid)
            if pb is None:
                continue
            library, uncertain = pb['library'], pb['uncertain']
            moods = moods_union if unify_moods else pb['moods']
            tier = 'llm_alto' if pb.get('llm_promoted') else 'individual'
            if consensus is not None:
                if consensus != library or uncertain:
                    result['unified_books'] += 1
                library, uncertain, tier = consensus, False, 'grupo'
            _emit(bid, pb, library, uncertain, moods, tier)

    # ── Libros sueltos metidos en este job: sin consenso, cada uno el suyo ───
    for bid in loose_ids:
        pb = per_book.get(bid)
        if pb is None:
            continue
        tier = 'llm_alto' if pb.get('llm_promoted') else 'individual'
        _emit(bid, pb, pb['library'], pb['uncertain'], pb['moods'], tier)

    return result


_REVISAR_SUFFIX = ' [REVISAR]'


def _parse_current_library(lib_field, val, lib_prefix_eff):
    """Devuelve (libreria_o_None, incierto_bool) leyendo el valor YA escrito
    del campo de libreria. `val` puede ser lista/tupla (tags o columna
    multivalor) o cadena (columna de texto dedicada)."""
    if lib_field == 'tags' or isinstance(val, (list, tuple)):
        for v in (val or []):
            v = str(v)
            if v.startswith(lib_prefix_eff):
                rest = v[len(lib_prefix_eff):]
                if rest.endswith(_REVISAR_SUFFIX):
                    return (rest[:-len(_REVISAR_SUFFIX)].strip() or None), True
                if rest == '(sin datos)':
                    return None, True
                return rest, False
        return None, True
    v = str(val or '').strip()
    if not v:
        return None, True
    rest = v[len(lib_prefix_eff):] if v.startswith(lib_prefix_eff) else v
    if rest.endswith(_REVISAR_SUFFIX):
        return (rest[:-len(_REVISAR_SUFFIX)].strip() or None), True
    if rest == '(sin datos)':
        return None, True
    return rest, False


def run_author_fallback_task(db, book_ids, settings, log=None, abort=None, notifications=None):
    """
    Nivel 3 (aparte, tras acabar TODOS los chunks): para los libros que sigan
    '[REVISAR]'/'(sin datos)' en el campo de libreria, mira que libreria
    domina entre los OTROS libros del mismo autor (dentro del mismo lote
    `book_ids`) que ya quedaron resueltos -leyendo la BD, ya actualizada por
    los chunks anteriores- y si hay mayoria clara se la asigna.
    """
    db = getattr(db, 'new_api', db)
    s = settings
    result = {
        'total': 0, 'author_resolved': 0, 'writes_by_field': {},
        'book_details': [], 'failed': False, 'error': '',
    }
    if not s.get('author_fallback', True):
        return result

    lib_field  = s.get('library_field', 'tags')
    lib_prefix = s.get('library_prefix', 'Biblioteca: ')
    overwrite  = s.get('overwrite', True)
    dominance  = s.get('author_dominance', 0.6)
    min_books  = s.get('author_min_books', 3)
    lib_prefix_eff = lib_prefix if lib_field == 'tags' else ''

    author_counts = {}
    pending = []
    for bid in book_ids:
        if abort is not None and abort.is_set():
            break
        try:
            authors = [a for a in (list(db.field_for('authors', bid) or [])) if a]
        except Exception:
            authors = []
        try:
            val = db.field_for(lib_field, bid)
        except Exception:
            val = None
        lib, uncertain = _parse_current_library(lib_field, val, lib_prefix_eff)
        if lib and not uncertain:
            for a in authors:
                d = author_counts.setdefault(a, {})
                d[lib] = d.get(lib, 0) + 1
        elif uncertain:
            pending.append((bid, authors))

    result['total'] = len(pending)
    writes = result['writes_by_field']
    for bid, authors in pending:
        if abort is not None and abort.is_set():
            break
        choice = None
        for a in authors:
            d = author_counts.get(a)
            if not d:
                continue
            total_a = sum(d.values())
            best = max(d, key=lambda k: d[k])
            if total_a >= min_books and (d[best] / float(total_a)) >= dominance:
                choice = best
                break
        if not choice:
            continue
        try:
            title = db.field_for('title', bid) or ''
        except Exception:
            title = ''
        lib_value = lib_prefix_eff + choice
        prev = (list(db.field_for(lib_field, bid) or [])
                if lib_field == 'tags' else db.field_for(lib_field, bid))
        merged = _merge_prefixed([lib_value], prev, lib_field, [lib_prefix_eff], overwrite)
        writes.setdefault(lib_field, {})[bid] = merged
        result['author_resolved'] += 1
        if len(result['book_details']) < 400:
            result['book_details'].append({
                'title': title, 'library': choice, 'confidence': 0.0,
                'uncertain': False, 'moods': [], 'tier': 'autor',
            })
    return result


def _merge_prefixed(new_values, existing, field, prefixes, overwrite):
    """
    Funde new_values con los existentes.
      overwrite=True  → quita los valores antiguos que empiecen por alguno de los
                        prefijos del plugin y los reemplaza (no toca otros tags).
      overwrite=False → añade sin duplicar, respetando todo lo existente.
    Devuelve lista (campos multi-valor) o cadena con comas (texto simple).
    """
    is_list = isinstance(existing, (list, tuple)) or field == 'tags'
    existing_list = []
    if isinstance(existing, (list, tuple)):
        existing_list = [v for v in existing if v]
    elif existing:
        existing_list = [v.strip() for v in str(existing).split(',') if v.strip()]

    if overwrite:
        kept = [v for v in existing_list
                if not any(str(v).startswith(p) for p in prefixes)]
    else:
        kept = list(existing_list)

    seen = set(kept)
    for v in new_values:
        if v not in seen:
            kept.append(v)
            seen.add(v)

    if is_list:
        return kept
    return ', '.join(kept)


def apply_ml_writes(gui, writes_by_field):
    """Aplica los cambios acumulados por campo a la base de datos."""
    from calibre.gui2 import error_dialog
    db = gui.current_db.new_api
    touched = set()
    failed_fields = []
    for field, id_map in writes_by_field.items():
        if not id_map:
            continue
        norm = {}
        field_meta = getattr(db, 'field_metadata', {}).get(field, {}) \
            if hasattr(db, 'field_metadata') else {}
        is_multiple = (field == 'tags') or field_meta.get('is_multiple', False)
        for bid, val in id_map.items():
            if isinstance(val, (list, tuple)):
                norm[bid] = list(val) if is_multiple else ', '.join(str(v) for v in val)
            else:
                norm[bid] = val
        try:
            db.set_field(field, norm)
            touched.update(norm.keys())
        except Exception as e:
            traceback.print_exc()
            failed_fields.append((field, str(e)))
    if touched:
        try:
            gui.library_view.model().refresh_ids(list(touched))
        except Exception:
            pass
    if failed_fields:
        detail = '\n'.join('  - {}: {}'.format(f, e) for f, e in failed_fields)
        error_dialog(
            gui, 'Error al guardar la clasificación',
            'No se pudo escribir en uno o más campos (¿la columna no existe en '
            'esta biblioteca?):\n\n{}'.format(detail),
            show=True)
