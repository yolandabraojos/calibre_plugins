# -*- coding: utf-8 -*-
from __future__ import unicode_literals, division, absolute_import, print_function

__license__ = 'GPL v3'

import re
import traceback
try:
    from qt.core import QObject, QThread, pyqtSignal as Signal
except ImportError:
    try:
        from qt.QtCore import QObject, QThread, pyqtSignal as Signal
    except ImportError:
        from PyQt5.QtCore import QObject, QThread, pyqtSignal as Signal


def start_classify_threaded(gui, book_ids, rules, target_field, overwrite,
                             dry_run, source_fields, extra_fields):

    worker = ClassifyWorker(gui, book_ids, rules, target_field, overwrite,
                            dry_run, source_fields, extra_fields)
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    return worker, thread


class ClassifyWorker(QObject):
    progress = Signal(int, str)
    finished = Signal(object)

    def __init__(self, gui, book_ids, rules, target_field, overwrite,
                 dry_run, source_fields, extra_fields):
        super(ClassifyWorker, self).__init__()
        self.gui          = gui
        self.book_ids     = book_ids
        self.rules        = rules
        self.target_field = target_field
        self.overwrite    = overwrite
        self.dry_run      = dry_run
        self.source_fields = source_fields
        self.extra_fields  = extra_fields
        self._cancelled   = False

    def run(self):
        print("DEBUG: Iniciando clasificación en background...")
        db = self.gui.current_db.new_api
        from calibre_plugins.book_classifier.classifier import BookClassifier
        classifier = BookClassifier(self.rules)

        results = {
            'total':     len(self.book_ids),
            'classified': 0,
            'skipped':   0,
            'errors':    0,
            'writes':    [],
            'cancelled': False,
        }

        for i, bid in enumerate(self.book_ids, start=1):
            if self._cancelled:
                print("DEBUG: Clasificación cancelada por el usuario.")
                results['cancelled'] = True
                break

            try:
                mi    = db.get_proxy_metadata(bid)
                title = mi.title or 'Sin título'

                self.progress.emit(i, title)

                # ── Recopilar texto de todos los campos configurados ──────────
                comments  = re.sub(r'<[^>]+>', ' ', mi.comments) if mi.comments else ''
                tags      = list(mi.tags) if mi.tags else []
                series    = mi.series or ''
                authors   = list(mi.authors) if mi.authors else []
                publisher = mi.publisher or ''

                text_parts = []
                if 'title'     in self.source_fields: text_parts.append(title)
                if 'comments'  in self.source_fields: text_parts.append(comments)
                if 'series'    in self.source_fields: text_parts.append(series)
                if 'tags'      in self.source_fields: text_parts.extend(tags)
                if 'authors'   in self.source_fields: text_parts.extend(authors)
                if 'publisher' in self.source_fields: text_parts.append(publisher)

                # ── Campos personalizados extra (#mi_campo…) ──────────────────
                for field in self.extra_fields:
                    try:
                        val = db.field_for(field, bid)
                        if val:
                            if isinstance(val, (list, tuple)):
                                text_parts.extend(str(v) for v in val if v)
                            else:
                                text_parts.append(str(val))
                    except Exception:
                        pass  # campo no existente o error de lectura → ignorar

                text = ' '.join(p for p in text_parts if p)
                cats = classifier.classify(text)

                if cats:
                    if self.target_field == 'tags':
                        prev_val = tags
                    else:
                        prev_val = db.field_for(self.target_field, bid)

                    new_val = _merge(cats, prev_val, self.target_field, self.overwrite)
                    results['writes'].append({'book_id': bid, 'value': new_val})
                    results['classified'] += 1
                else:
                    results['skipped'] += 1

            except Exception as e:
                print("ERROR en libro {}: {}".format(bid, e))
                traceback.print_exc()
                results['errors'] += 1

        self.finished.emit(results)

    def cancel(self):
        self._cancelled = True


def _merge(cats, existing, target_field, overwrite):
    if overwrite or not existing:
        return cats
    if isinstance(existing, (list, tuple)):
        existing_list = [v for v in existing if v is not None]
        return sorted(set(existing_list) | set(cats))
    existing_set = set(str(existing).split(', ')) if existing else set()
    return sorted(existing_set | set(cats))


def _normalize_writes_for_field(db, target_field, id_map):
    if target_field == 'tags':
        return id_map

    field_meta  = getattr(db, 'field_metadata', {}).get(target_field, {}) \
                  if hasattr(db, 'field_metadata') else {}
    is_multiple = field_meta.get('is_multiple', False)

    normalized = {}
    for book_id, value in id_map.items():
        if isinstance(value, (list, tuple)):
            if is_multiple:
                normalized[book_id] = list(value)
            else:
                normalized[book_id] = ', '.join(str(v) for v in value if v is not None)
        elif value is None:
            normalized[book_id] = ''
        else:
            normalized[book_id] = value
    return normalized


def apply_writes(gui, writes, target_field):
    print("DEBUG: Aplicando cambios a la base de datos...")
    db     = gui.current_db.new_api
    id_map = {w['book_id']: w['value'] for w in writes}
    id_map = _normalize_writes_for_field(db, target_field, id_map)

    try:
        db.set_field(target_field, id_map)
        gui.library_view.model().refresh_ids(list(id_map.keys()))
        print("DEBUG: Escritura completada.")
    except Exception:
        traceback.print_exc()
