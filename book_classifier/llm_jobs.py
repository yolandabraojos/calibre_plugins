# -*- coding: utf-8 -*-
"""
Worker en segundo plano para el RESCATE con IA en la nube (capa híbrida).

Recoge los libros que el clasificador local dejó sin resolver —los que tienen la
librería marcada como '[REVISAR]' o '(sin datos)'— lee su sinopsis real de
Calibre, y los manda en lotes a un LLM (GLM, DeepSeek, OpenAI…) para decidir la
librería (y, opcional, los temas). Solo reescribe los que el LLM resuelve con
confianza; el resto se queda como estaba.

No toca los libros que el modelo local ya clasificó con seguridad.
"""
from __future__ import unicode_literals, division, absolute_import, print_function

import re
import time
import traceback

try:
    from qt.core import QObject, QThread, pyqtSignal as Signal
except ImportError:
    try:
        from qt.QtCore import QObject, QThread, pyqtSignal as Signal
    except ImportError:
        from PyQt5.QtCore import QObject, QThread, pyqtSignal as Signal

from calibre_plugins.book_classifier.ml_jobs import _merge_prefixed


def start_llm_rescue_threaded(gui, book_ids, settings):
    worker = LLMRescueWorker(gui, book_ids, settings)
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    return worker, thread


def _is_residue(lib_value):
    """True si el valor de librería es del plugin pero sin resolver."""
    if not lib_value:
        return False
    v = str(lib_value).strip()
    return ('[REVISAR]' in v) or v.endswith('(sin datos)')


class LLMRescueWorker(QObject):
    progress = Signal(int, str)
    finished = Signal(object)

    def __init__(self, gui, book_ids, settings):
        super(LLMRescueWorker, self).__init__()
        self.gui      = gui
        self.book_ids = book_ids
        self.s        = settings
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        s = self.s
        db = self.gui.current_db.new_api

        result = {
            'total': len(self.book_ids), 'candidates': 0, 'rescued': 0,
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
                               'Configurar plugin → Rescate con IA.')
            self.finished.emit(result)
            return

        # Vocabulario de temas (si se van a escribir)
        temas_vocab = []
        if write_temas:
            try:
                from calibre_plugins.book_classifier.ml_classifier import _load_json
                temas_vocab = list((_load_json('mood_rules.json') or {}).keys())
            except Exception:
                temas_vocab = []

        from calibre_plugins.book_classifier import llm_rescue_engine as eng

        # ── PASO 1: localizar el residuo y leer su texto real ─────────────────
        cand = []   # [(bid, title, item_dict, tags_list)]
        for i, bid in enumerate(self.book_ids, 1):
            if self._cancelled:
                result['cancelled'] = True
                break
            try:
                mi = db.get_proxy_metadata(bid)
                title = mi.title or 'Sin título'
                self.progress.emit(i, 'Buscando no clasificados: ' + title)

                tags = list(mi.tags) if mi.tags else []
                # valor actual de librería en el campo destino
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

                if not _is_residue(lib_value):
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
        if not cand:
            self.finished.emit(result)
            return

        # ── PASO 2: rescatar en lotes ─────────────────────────────────────────
        writes = result['writes_by_field']
        done = 0
        for b in range(0, len(cand), batch_sz):
            if self._cancelled:
                result['cancelled'] = True
                break
            lote = cand[b:b + batch_sz]
            items = [c[2] for c in lote]
            self.progress.emit(len(self.book_ids),
                               'Rescatando con IA: {}/{}'.format(b, len(cand)))
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
                continue

            for (bid, title, item, tags), r in zip(lote, res_list):
                lib = r.get('libreria')
                if not lib or lib == eng.REVISAR:
                    continue   # el LLM tampoco pudo: se queda como estaba
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
            time.sleep(0.2)

        self.finished.emit(result)
