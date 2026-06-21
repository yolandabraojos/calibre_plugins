# -*- coding: utf-8 -*-
"""
Worker en segundo plano para la clasificación con IA local (modelo entrenado).

Tres niveles de decisión de librería (de más a menos fiable):
  1) Predicción individual del modelo, si supera el umbral de confianza.
  2) CONSENSO DE GRUPO: libros del mismo universo (#universe) o, en su defecto,
     misma serie → todos la librería de mayor confianza sumada del grupo.
  3) CONSENSO DE AUTOR (opcional): si un libro sigue dudoso, hereda la librería
     dominante del autor, siempre que el autor tenga una mayoría clara.
Si nada de eso resuelve, queda "(revisar)".

Los tags de tema (eje 2) se unifican por grupo si se activa.
"""
from __future__ import unicode_literals, division, absolute_import, print_function

import re
import traceback

try:
    from qt.core import QObject, QThread, pyqtSignal as Signal
except ImportError:
    try:
        from qt.QtCore import QObject, QThread, pyqtSignal as Signal
    except ImportError:
        from PyQt5.QtCore import QObject, QThread, pyqtSignal as Signal


def start_ml_classify_threaded(gui, book_ids, settings):
    worker = MLClassifyWorker(gui, book_ids, settings)
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    return worker, thread


class MLClassifyWorker(QObject):
    progress = Signal(int, str)
    finished = Signal(object)

    def __init__(self, gui, book_ids, settings):
        super(MLClassifyWorker, self).__init__()
        self.gui       = gui
        self.book_ids  = book_ids
        self.s         = settings
        self._cancelled = False

    def run(self):
        db = self.gui.current_db.new_api
        s = self.s

        from calibre_plugins.book_classifier.ml_classifier import MLClassifier
        try:
            clf = MLClassifier(default_threshold=s.get('threshold', 0.55))
        except Exception as e:
            traceback.print_exc()
            self.finished.emit({'failed': True, 'error': str(e),
                                'total': len(self.book_ids), 'writes_by_field': {},
                                'classified': 0, 'errors': 0, 'book_details': []})
            return

        lib_field   = s.get('library_field', 'tags')
        mood_field  = s.get('mood_field', 'tags')
        lib_prefix  = s.get('library_prefix', 'Biblioteca: ')
        mood_prefix = s.get('mood_prefix', 'Tema: ')
        threshold   = s.get('threshold', 0.55)
        write_lib   = s.get('write_library', True)
        write_mood  = s.get('write_moods', True)
        overwrite   = s.get('overwrite', True)
        source_fields = s.get('source_fields', ['title', 'comments', 'tags'])
        use_subtitle   = s.get('use_subtitle', False)
        subtitle_field = s.get('subtitle_field', '#subtitle')

        unify          = s.get('group_unify', True)
        unify_moods    = s.get('group_unify_moods', True)
        universe_field = s.get('universe_field', '#universe')

        author_fallback  = s.get('author_fallback', True)
        author_dominance = s.get('author_dominance', 0.6)
        author_min_books = s.get('author_min_books', 3)

        results = {
            'total': len(self.book_ids), 'classified': 0, 'errors': 0,
            'cancelled': False, 'writes_by_field': {}, 'dist': {},
            'unified_books': 0, 'group_count': 0, 'author_resolved': 0,
            'book_details': [],
        }

        # ── PASADA 1: clasificar libro a libro ────────────────────────────────
        per_book = {}          # bid -> dict
        groups   = {}          # group_key -> [bid, ...]
        for i, bid in enumerate(self.book_ids, start=1):
            if self._cancelled:
                results['cancelled'] = True
                break
            try:
                mi = db.get_proxy_metadata(bid)
                title = mi.title or 'Sin título'
                self.progress.emit(i, title)

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

                # clave de grupo: universo manda; si no, serie
                gkey = None
                if unify:
                    universe = ''
                    try:
                        uv = db.field_for(universe_field, bid)
                        universe = (uv or '').strip() if isinstance(uv, str) else (uv or '')
                    except Exception:
                        universe = ''
                    if universe:
                        gkey = ('U', universe)
                    elif series:
                        gkey = ('S', series)

                per_book[bid] = {
                    'title': title, 'tags': tags, 'authors': authors,
                    'library': res['library'], 'confidence': res['confidence'],
                    'uncertain': res['uncertain'], 'moods': res['moods'], 'gkey': gkey,
                }
                if gkey is not None:
                    groups.setdefault(gkey, []).append(bid)
            except Exception as e:
                print("ML ERROR (pasada 1) libro {}: {}".format(bid, e))
                traceback.print_exc()
                results['errors'] += 1

        # ── NIVEL 2: consenso por grupo (serie / universo) ────────────────────
        group_lib   = {}
        group_moods = {}
        for gkey, bids in groups.items():
            score = {}
            for bid in bids:
                pb = per_book[bid]
                if pb['library'] and not pb['uncertain']:
                    score[pb['library']] = score.get(pb['library'], 0.0) + pb['confidence']
            if score:
                group_lib[gkey] = max(score, key=lambda k: score[k])
            if unify_moods:
                union = []
                for bid in bids:
                    for m in per_book[bid]['moods']:
                        if m not in union:
                            union.append(m)
                group_moods[gkey] = union
        results['group_count'] = len(group_lib)

        # ── NIVEL 3: tabla de librería dominante por autor ────────────────────
        # Se construye con lo ya resuelto con fiabilidad (individual confiable o
        # consenso de grupo), ponderando por confianza.
        author_scores = {}   # autor -> { librería: peso }
        if author_fallback:
            for bid, pb in per_book.items():
                resolved = None
                gkey = pb['gkey']
                if gkey is not None and gkey in group_lib:
                    resolved = group_lib[gkey]
                    weight = 1.0
                elif pb['library'] and not pb['uncertain']:
                    resolved = pb['library']
                    weight = pb['confidence']
                if resolved:
                    for a in pb['authors']:
                        d = author_scores.setdefault(a, {})
                        d[resolved] = d.get(resolved, 0.0) + weight

        def author_choice(authors):
            """Librería dominante entre los autores del libro, o None."""
            for a in authors:
                d = author_scores.get(a)
                if not d:
                    continue
                total = sum(d.values())
                best = max(d, key=lambda k: d[k])
                # nº de libros ~ aproximado por nº de entradas con ese peso; exigimos
                # mayoría clara y un mínimo de señal.
                if total >= author_min_books and (d[best] / total) >= author_dominance:
                    return best
            return None

        # ── PASADA 2: decidir y construir escrituras ──────────────────────────
        writes = results['writes_by_field']
        for bid, pb in per_book.items():
            try:
                gkey = pb['gkey']
                library   = pb['library']
                uncertain = pb['uncertain']
                moods     = pb['moods']
                source_tier = 'individual'

                # nivel 2
                if gkey is not None and gkey in group_lib:
                    consensus = group_lib[gkey]
                    if consensus != library or uncertain:
                        results['unified_books'] += 1
                    library = consensus
                    uncertain = False
                    source_tier = 'grupo'
                # nivel 3 (solo si sigue dudoso)
                elif uncertain and author_fallback:
                    choice = author_choice(pb['authors'])
                    if choice:
                        library = choice
                        uncertain = False
                        source_tier = 'autor'
                        results['author_resolved'] += 1

                if gkey is not None and unify_moods and gkey in group_moods:
                    moods = group_moods[gkey]

                if library is None:
                    lib_value = lib_prefix + '(sin datos)'
                elif uncertain:
                    lib_value = lib_prefix + '(revisar)'
                else:
                    lib_value = lib_prefix + library

                new_by_field = {}
                if write_lib:
                    new_by_field.setdefault(lib_field, []).append(lib_value)
                if write_mood and moods:
                    new_by_field.setdefault(mood_field, []).extend(mood_prefix + m for m in moods)

                for field, newvals in new_by_field.items():
                    prev = list(pb['tags']) if field == 'tags' else db.field_for(field, bid)
                    merged = _merge_prefixed(newvals, prev, field,
                                             [lib_prefix, mood_prefix], overwrite)
                    writes.setdefault(field, {})[bid] = merged

                key = library if (library and not uncertain) else '(revisar/sin datos)'
                results['dist'][key] = results['dist'].get(key, 0) + 1
                results['classified'] += 1

                if len(results['book_details']) < 400:
                    results['book_details'].append({
                        'title': pb['title'], 'library': library,
                        'confidence': round(pb['confidence'], 3),
                        'uncertain': uncertain, 'moods': moods, 'tier': source_tier,
                    })
            except Exception as e:
                print("ML ERROR (pasada 2) libro {}: {}".format(bid, e))
                traceback.print_exc()
                results['errors'] += 1

        self.finished.emit(results)

    def cancel(self):
        self._cancelled = True


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
    db = gui.current_db.new_api
    touched = set()
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
        except Exception:
            traceback.print_exc()
    if touched:
        try:
            gui.library_view.model().refresh_ids(list(touched))
        except Exception:
            pass
