# -*- coding: utf-8 -*-
from __future__ import unicode_literals, division, absolute_import, print_function

__license__ = 'GPL v3'

import pkgutil
import traceback
from calibre.gui2.actions import InterfaceAction
from calibre.gui2 import Dispatcher, error_dialog, question_dialog
from qt.core import QIcon, QMenu, QAction, QPixmap, Qt

from calibre_plugins.book_classifier.config import prefs
from calibre_plugins.book_classifier.ml_jobs import (
    plan_classify_chunks, run_classify_chunk_task, run_author_fallback_task,
    apply_ml_writes)
from calibre.gui2.threaded_jobs import ThreadedJob
from calibre_plugins.book_classifier.llm_jobs import (
    select_rescue_candidates, plan_rescue_chunks, run_rescue_batch_task)

try:
    from calibre_plugins.book_classifier import get_icons
except ImportError:
    get_icons = None


class BookClassifierAction(InterfaceAction):
    name = 'Book Classifier'
    action_spec = ('Clasificar Libros', None, 'Clasificar libros con IA local', None)
    action_type = 'current'

    def genesis(self):
        print("DEBUG: Plugin Book Classifier (IA) cargando...")
        self._load_icon()

        menu = QMenu(self.gui)
        self.qaction.setMenu(menu)

        act_sel = QAction('Clasificar libros seleccionados', self.gui)
        act_sel.triggered.connect(lambda: self._method_ml(all_books=False))
        menu.addAction(act_sel)

        act_all = QAction('Clasificar TODA la biblioteca', self.gui)
        act_all.triggered.connect(lambda: self._method_ml(all_books=True))
        menu.addAction(act_all)

        menu.addSeparator()

        act_llm_sel = QAction('Rescatar con IA los no clasificados (seleccion)', self.gui)
        act_llm_sel.triggered.connect(lambda: self._method_llm_rescue(all_books=False))
        menu.addAction(act_llm_sel)

        act_llm_all = QAction('Rescatar con IA los no clasificados (toda la biblioteca)', self.gui)
        act_llm_all.triggered.connect(lambda: self._method_llm_rescue(all_books=True))
        menu.addAction(act_llm_all)

        act_llm_reeval = QAction('Reevaluar con IA la seleccion (ignora marcas)', self.gui)
        act_llm_reeval.triggered.connect(lambda: self._method_llm_rescue(all_books=False, force=True))
        menu.addAction(act_llm_reeval)

        menu.addSeparator()

        sub_clear = QMenu('Limpiar clasificaciones del plugin', self.gui)
        act_clear_sel = QAction('Libros seleccionados', self.gui)
        act_clear_all = QAction('Toda la biblioteca', self.gui)
        act_clear_sel.triggered.connect(lambda: self._clear_classifications(all_books=False))
        act_clear_all.triggered.connect(lambda: self._clear_classifications(all_books=True))
        sub_clear.addAction(act_clear_sel)
        sub_clear.addAction(act_clear_all)
        menu.addMenu(sub_clear)

        menu.addSeparator()

        act_config = QAction('Configurar plugin...', self.gui)
        act_config.triggered.connect(self.show_config)
        menu.addAction(act_config)

        self.qaction.triggered.connect(lambda: self._method_ml(all_books=False))
        print("DEBUG: Plugin Book Classifier (IA) listo.")

    # ─── Selección ────────────────────────────────────────────────────────────

    def _get_selected_ids(self):
        rows = self.gui.library_view.selectionModel().selectedRows()
        return [self.gui.library_view.model().id(r) for r in rows]

    def _get_all_ids(self):
        return list(self.gui.current_db.all_ids())

    def _resolve_book_ids(self, all_books):
        if all_books:
            if not question_dialog(self.gui, 'Confirmar', '¿Aplicar a TODA la biblioteca?'):
                return None
            return self._get_all_ids()
        ids = self._get_selected_ids()
        if not ids:
            error_dialog(self.gui, 'Error', 'No hay libros seleccionados.', show=True)
            return None
        return ids

    # ─── Clasificación con IA ─────────────────────────────────────────────────

    def _method_ml(self, all_books=False):
        book_ids = self._resolve_book_ids(all_books)
        if book_ids is None:
            return
        print("DEBUG: IA local en {} libros".format(len(book_ids)))
        self._run_ml_classifier(book_ids)

    def _run_ml_classifier(self, book_ids):
        try:
            settings = {
                'library_field':  prefs.get('ml_library_field', 'tags'),
                'mood_field':     prefs.get('ml_mood_field', 'tags'),
                'library_prefix': prefs.get('ml_library_prefix', 'Biblioteca: '),
                'mood_prefix':    prefs.get('ml_mood_prefix', 'Tema: '),
                'threshold':      prefs.get('ml_threshold', 0.55),
                'write_library':  prefs.get('ml_write_library', True),
                'write_moods':    prefs.get('ml_write_moods', True),
                'overwrite':      prefs.get('ml_overwrite', True),
                'source_fields':  prefs.get('source_fields', ['title', 'comments', 'tags']),
                'use_subtitle':   prefs.get('ml_use_subtitle', True),
                'subtitle_field': prefs.get('ml_subtitle_field', '#subtitle'),
                'group_unify':       prefs.get('ml_group_unify', True),
                'group_unify_moods': prefs.get('ml_group_unify_moods', True),
                'universe_field':    prefs.get('ml_universe_field', '#universe'),
                'author_fallback':   prefs.get('ml_author_fallback', True),
                'author_dominance':  prefs.get('ml_author_dominance', 0.6),
                'ai_batch_ref':      prefs.get('llm_batch', 10),
            }

            missing = self._check_missing_fields(settings)
            if missing:
                error_dialog(
                    self.gui, 'Columna no encontrada',
                    'Estas columnas configuradas en Book Classifier no existen en '
                    'esta biblioteca:\n\n{}\n\n'
                    'Créalas (Preferencias → Añadir columnas personalizadas) o '
                    'corrige la configuración del plugin antes de clasificar.'.format(
                        '\n'.join('  - {} ({})'.format(f, u) for f, u in missing)),
                    show=True)
                return

            # Agrupa por serie/universo ANTES de lanzar nada (lectura rapida en
            # el hilo de la GUI) y lanza UN ThreadedJob POR GRUPO (+ lotes de
            # libros sueltos), en vez de un unico hilo que clasifica toda la
            # biblioteca de un tiron. Asi: (1) cada grupo aplica sus cambios en
            # cuanto termina, sin esperar al resto; (2) corre en segundo plano
            # (lista de tareas de Calibre), sin dialogo modal bloqueante; (3)
            # cada tarea es cancelable por separado desde esa lista.
            chunks = plan_classify_chunks(self.gui, book_ids, settings)
            if not chunks:
                error_dialog(self.gui, 'Sin libros', 'No hay libros que clasificar.', show=True)
                return

            self._ml_run = {
                'pending': len(chunks), 'book_ids': list(book_ids), 'settings': settings,
                'total': 0, 'classified': 0, 'errors': 0, 'dist': {},
                'group_count': 0, 'unified_books': 0, 'author_resolved': 0,
                'book_details': [], 'failed_chunks': [],
                'first_error': '', 'error_samples': [],
            }
            for chunk in chunks:
                job = ThreadedJob(
                    'book_classifier_ml_classify',
                    'Clasificar IA - {}'.format(chunk['label']),
                    run_classify_chunk_task,
                    (self.gui.current_db, chunk['subgroups'], chunk['loose_ids'],
                     settings, chunk['label']),
                    {}, Dispatcher(self._ml_chunk_done))
                self.gui.job_manager.run_threaded_job(job)

            try:
                self.gui.status_bar.show_message(
                    'Clasificacion IA lanzada en {} tarea(s) (una por serie/universo '
                    '+ lotes de sueltos). Mira la lista de tareas; puedes seguir '
                    'usando Calibre.'.format(len(chunks)), 6000)
            except Exception:
                pass
        except Exception:
            print("DEBUG ERROR: Fallo al lanzar el clasificador IA")
            traceback.print_exc()

    def _check_missing_fields(self, settings):
        """Devuelve [(campo, uso)] para los campos configurados que no existen
        en esta biblioteca ('tags' es estándar y siempre existe)."""
        db = self.gui.current_db.new_api
        try:
            valid = set(db.field_metadata.all_field_keys())
        except Exception:
            return []
        checks = [
            (settings['library_field'], 'campo de librería'),
            (settings['mood_field'], 'campo de temas'),
        ]
        if settings.get('use_subtitle'):
            checks.append((settings['subtitle_field'], 'subtítulo'))
        if settings.get('group_unify'):
            checks.append((settings['universe_field'], 'universo'))
        missing = []
        seen = set()
        for field, uso in checks:
            if not field or field == 'tags' or field in seen:
                continue
            seen.add(field)
            if field not in valid:
                missing.append((field, uso))
        return missing

    def _ml_chunk_done(self, job):
        try:
            run = getattr(self, '_ml_run', None)
            if run is None:
                return
            if getattr(job, 'failed', False):
                tb = getattr(job, 'traceback', '') or ''
                run['failed_chunks'].append(
                    (str(getattr(job, 'exception', '')) + '\n' + tb).strip())
            else:
                result = getattr(job, 'result', None) or {}
                if result.get('failed'):
                    run['failed_chunks'].append(result.get('error', ''))
                else:
                    if result.get('writes_by_field'):
                        apply_ml_writes(self.gui, result['writes_by_field'])
                    if not run['first_error'] and result.get('first_error'):
                        run['first_error'] = result['first_error']
                    for smp in result.get('error_samples', []):
                        if len(run['error_samples']) < 20:
                            run['error_samples'].append(smp)
                    run['total']         += result.get('total', 0)
                    run['classified']    += result.get('classified', 0)
                    run['errors']        += result.get('errors', 0)
                    run['group_count']   += result.get('group_count', 0)
                    run['unified_books'] += result.get('unified_books', 0)
                    for k, v in result.get('dist', {}).items():
                        run['dist'][k] = run['dist'].get(k, 0) + v
                    room = 400 - len(run['book_details'])
                    if room > 0:
                        run['book_details'].extend(result.get('book_details', [])[:room])
            run['pending'] -= 1
            if run['pending'] <= 0:
                self._ml_start_author_fallback()
        except Exception:
            print("DEBUG ERROR en _ml_chunk_done:")
            traceback.print_exc()

    def _ml_start_author_fallback(self):
        try:
            run = self._ml_run
            settings = run['settings']
            if not settings.get('author_fallback', True):
                self._finish_ml_run()
                return
            job = ThreadedJob(
                'book_classifier_ml_author', 'Clasificar IA - consenso por autor',
                run_author_fallback_task,
                (self.gui.current_db, run['book_ids'], settings), {},
                Dispatcher(self._ml_author_done))
            self.gui.job_manager.run_threaded_job(job)
        except Exception:
            print("DEBUG ERROR en _ml_start_author_fallback:")
            traceback.print_exc()
            self._finish_ml_run()

    def _ml_author_done(self, job):
        try:
            run = getattr(self, '_ml_run', None)
            if run is None:
                return
            if getattr(job, 'failed', False):
                tb = getattr(job, 'traceback', '') or ''
                run['failed_chunks'].append(
                    ('consenso por autor: ' + str(getattr(job, 'exception', ''))
                     + '\n' + tb).strip())
            else:
                result = getattr(job, 'result', None) or {}
                if result.get('failed') and not run['first_error']:
                    run['first_error'] = result.get('error', '')
                if result.get('writes_by_field'):
                    apply_ml_writes(self.gui, result['writes_by_field'])
                run['author_resolved'] += result.get('author_resolved', 0)
                room = 400 - len(run['book_details'])
                if room > 0:
                    run['book_details'].extend(result.get('book_details', [])[:room])
        except Exception:
            print("DEBUG ERROR en _ml_author_done:")
            traceback.print_exc()
        finally:
            self._finish_ml_run()

    def _finish_ml_run(self):
        run = getattr(self, '_ml_run', None)
        self._ml_run = None
        if run is None:
            return
        if run.get('failed_chunks'):
            print("DEBUG: chunks con error en clasificacion IA:", run['failed_chunks'])
        self._show_ml_results(run)

    def _show_ml_results(self, stats):
        try:
            from qt.core import QDialog, QVBoxLayout, QDialogButtonBox, QLabel, QTextEdit

            dialog = QDialog(self.gui)
            dialog.setWindowTitle('Resultados de clasificación IA')
            dialog.resize(620, 520)
            layout = QVBoxLayout(dialog)

            lines = []
            if stats.get('cancelled'):
                lines.append('Cancelado por el usuario.')
            lines += [
                'Total escaneados:  {}'.format(stats.get('total', 0)),
                'Clasificados:      {}'.format(stats.get('classified', 0)),
                'Errores:           {}'.format(stats.get('errors', 0)),
                'Grupos unificados: {}  ({} libros heredaron la librería del grupo)'.format(
                    stats.get('group_count', 0), stats.get('unified_books', 0)),
                'Resueltos por autor: {}'.format(stats.get('author_resolved', 0)),
                '',
                'Reparto por librería:',
            ]
            dist = stats.get('dist', {})
            for name in sorted(dist, key=lambda k: -dist[k]):
                lines.append('   {:<28} {}'.format(name, dist[name]))
            layout.addWidget(QLabel('\n'.join(lines)))

            details = stats.get('book_details', [])
            if details:
                txt = QTextEdit()
                txt.setReadOnly(True)
                body = []
                for d in details:
                    flag = '  [REVISAR]' if d.get('uncertain') else ''
                    tier = d.get('tier', '')
                    tier_s = '  ·{}'.format(tier) if tier and tier != 'individual' else ''
                    body.append('{}  ->  {} ({:.0%}){}{}'.format(
                        d['title'][:46], d.get('library') or '(sin datos)',
                        d.get('confidence', 0), tier_s, flag))
                    if d.get('moods'):
                        body.append('      tema: {}'.format(', '.join(d['moods'])))
                txt.setPlainText('\n'.join(body))
                layout.addWidget(txt)

            err_bits = []
            if stats.get('first_error'):
                err_bits.append('Primer error (con traza):\n' + str(stats['first_error']))
            if stats.get('error_samples'):
                err_bits.append('Libros con error ({}):\n{}'.format(
                    len(stats['error_samples']), '\n'.join(stats['error_samples'])))
            if stats.get('failed_chunks'):
                err_bits.append('Tareas que fallaron por completo:\n' +
                                '\n\n'.join(str(x) for x in stats['failed_chunks']))
            if err_bits:
                dialog.resize(700, 580)
                layout.addWidget(QLabel('Detalles de los errores:'))
                errbox = QTextEdit()
                errbox.setReadOnly(True)
                errbox.setPlainText('\n\n'.join(err_bits))
                layout.addWidget(errbox)

            btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
            btns.accepted.connect(dialog.accept)
            layout.addWidget(btns)
            dialog.exec()
        except Exception:
            print("DEBUG ERROR en _show_ml_results:")
            traceback.print_exc()

    # ─── Rescate con IA (capa hibrida LLM) ────────────────────────────────────

    def _method_llm_rescue(self, all_books=False, force=False):
        book_ids = self._resolve_book_ids(all_books)
        if book_ids is None:
            return
        self._run_llm_rescue(book_ids, force=force)

    def _prefetch_books(self, book_ids, settings):
        """Lee los datos de los libros en el hilo de la GUI (el job NO debe tocar
        la base de datos: hacerlo crashea Calibre con errores de hilo Qt)."""
        db = self.gui.current_db.new_api
        lib_field  = settings.get('library_field', 'tags')
        mood_field = settings.get('mood_field', 'tags')
        lib_prefix = settings.get('library_prefix', 'Biblioteca: ')
        lib_prefix_eff = lib_prefix if lib_field == 'tags' else ''
        books = []
        for bid in book_ids:
            try:
                tags = list(db.field_for('tags', bid) or [])
                title = db.field_for('title', bid) or 'Sin titulo'
                authors = list(db.field_for('authors', bid) or [])
                comments = db.field_for('comments', bid) or ''
                languages = list(db.field_for('languages', bid) or [])
            except Exception:
                continue
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

            def _fval(field, _tags=tags, _bid=bid):
                if field == 'tags':
                    return list(_tags)
                try:
                    return db.field_for(field, _bid)
                except Exception:
                    return None

            prev = {lib_field: _fval(lib_field), mood_field: _fval(mood_field)}
            idioma = ','.join(sorted(str(x) for x in languages))
            books.append({'id': bid, 'title': title, 'authors': authors,
                          'comments': comments, 'tags': tags, 'idioma': idioma,
                          'lib_value': lib_value, 'prev': prev})
        return books

    def _run_llm_rescue(self, book_ids, force=False):
        try:
            provider = prefs.get('llm_provider', 'glm')
            key = (prefs.get('llm_api_key') or '').strip()
            if provider != 'local' and not key:
                error_dialog(
                    self.gui, 'Falta la clave de API',
                    'Configura el proveedor y la clave en '
                    'Configurar plugin -> Rescate con IA en la nube.', show=True)
                return
            settings = {
                'library_field':  prefs.get('ml_library_field', 'tags'),
                'mood_field':     prefs.get('ml_mood_field', 'tags'),
                'library_prefix': prefs.get('ml_library_prefix', 'Biblioteca: '),
                'mood_prefix':    prefs.get('ml_mood_prefix', 'Tema: '),
                'overwrite':      prefs.get('ml_overwrite', True),
                'llm_provider':   provider,
                'llm_api_key':    key,
                'llm_model':      prefs.get('llm_model', ''),
                'llm_batch':      prefs.get('llm_batch', 10),
                'llm_min_conf':   prefs.get('llm_min_conf', 0.55),
                'llm_write_temas': prefs.get('llm_write_temas', True),
                'llm_write_reason': prefs.get('llm_write_reason', True),
                'llm_reason_field': prefs.get('llm_reason_field', '#motivo_ia'),
                'llm_write_serie': prefs.get('llm_write_serie', True),
                'llm_serie_field': prefs.get('llm_serie_field', '#serie_ia'),
                'llm_write_conf':  prefs.get('llm_write_conf', True),
                'llm_conf_field':  prefs.get('llm_conf_field', '#confianza_ia'),
                'force_all':       force,
            }
            books = self._prefetch_books(book_ids, settings)

            # Filtra los candidatos ANTES de lanzar nada (rapido, sin red) y
            # reparte el rescate en VARIOS jobs (en vez de uno solo con todos
            # los libros): cada job hace 1-2 llamadas a la IA y aplica sus
            # cambios en cuanto termina, sin esperar a que acabe el resto.
            cand, diag = select_rescue_candidates(books, settings)

            if not cand:
                self._show_llm_results({
                    'candidates': 0, 'total': len(books), 'cancelled': False,
                    'lib_field': settings.get('library_field', 'tags'),
                    'with_value': diag['with_value'], 'sample': diag['sample'],
                })
                return

            chunks = plan_rescue_chunks(cand, settings)

            from calibre_plugins.book_classifier import llm_rescue_engine as eng
            try:
                _kind, _dmodel, _base = eng.PROVIDERS.get(
                    provider, ('', settings.get('llm_model') or '?', '?'))
            except Exception:
                _dmodel, _base = (settings.get('llm_model') or '?'), '?'

            self._llm_run = {
                'pending': len(chunks), 'settings': settings,
                'total': len(books), 'candidates': len(cand),
                'rescued': 0, 'errors': 0, 'dist': {}, 'book_details': [],
                'first_error': '', 'failed_chunks': [],
                'provider': provider,
                'model_used': settings.get('llm_model') or _dmodel,
                'base_used': _base,
                'lib_field': settings.get('library_field', 'tags'),
                'with_value': diag['with_value'], 'sample': diag['sample'],
            }
            for chunk in chunks:
                job = ThreadedJob(
                    'book_classifier_llm_rescue',
                    '{} con IA - {}'.format(
                        'Reevaluacion' if force else 'Rescate', chunk['label']),
                    run_rescue_batch_task,
                    (chunk['cand'], settings, chunk['label']), {},
                    Dispatcher(self._llm_chunk_done))
                self.gui.job_manager.run_threaded_job(job)

            try:
                self.gui.status_bar.show_message(
                    '{} con IA lanzado en {} tarea(s) sobre {} libro(s){}. Mira '
                    'la lista de tareas; puedes seguir usando Calibre.'.format(
                        'Reevaluacion' if force else 'Rescate',
                        len(chunks), len(cand),
                        (' ({} copias duplicadas agrupadas, no se reenvian)'.format(
                            diag.get('duplicates_saved', 0))
                         if diag.get('duplicates_saved') else '')), 6000)
            except Exception:
                pass
        except Exception:
            print("DEBUG ERROR: Fallo al lanzar el rescate IA")
            traceback.print_exc()

    def _llm_chunk_done(self, job):
        try:
            run = getattr(self, '_llm_run', None)
            if run is None:
                return
            if getattr(job, 'failed', False):
                run['failed_chunks'].append(str(getattr(job, 'exception', '')))
            else:
                result = getattr(job, 'result', None) or {}
                if result.get('failed'):
                    run['failed_chunks'].append(result.get('error', ''))
                else:
                    if result.get('writes_by_field'):
                        apply_ml_writes(self.gui, result['writes_by_field'])
                    reason_field = (run['settings'].get('llm_reason_field')
                                    if run['settings'].get('llm_write_reason', True) else None)
                    if result.get('reason_writes') and reason_field:
                        self._apply_reason_writes(reason_field, result['reason_writes'])
                    serie_field = (run['settings'].get('llm_serie_field')
                                   if run['settings'].get('llm_write_serie', True) else None)
                    if result.get('serie_writes') and serie_field:
                        self._apply_custom_writes(serie_field, result['serie_writes'],
                                                  'la serie detectada por la IA', 'texto')
                    conf_field = (run['settings'].get('llm_conf_field')
                                  if run['settings'].get('llm_write_conf', True) else None)
                    if result.get('conf_writes') and conf_field:
                        self._apply_custom_writes(conf_field, result['conf_writes'],
                                                  'el % de confianza de la IA',
                                                  'entero (numero)')
                    run['rescued'] += result.get('rescued', 0)
                    run['errors']  += result.get('errors', 0)
                    for k, v in result.get('dist', {}).items():
                        run['dist'][k] = run['dist'].get(k, 0) + v
                    if not run['first_error'] and result.get('first_error'):
                        run['first_error'] = result['first_error']
                    room = 400 - len(run['book_details'])
                    if room > 0:
                        run['book_details'].extend(result.get('book_details', [])[:room])
            run['pending'] -= 1
            if run['pending'] <= 0:
                self._finish_llm_run()
        except Exception:
            print("DEBUG ERROR en _llm_chunk_done:")
            traceback.print_exc()

    def _finish_llm_run(self):
        run = getattr(self, '_llm_run', None)
        self._llm_run = None
        if run is None:
            return
        if run.get('failed_chunks'):
            print("DEBUG: chunks con error en rescate IA:", run['failed_chunks'])
        self._show_llm_results(run)
    def _apply_custom_writes(self, field, id_map, what='el dato', tipo='texto'):
        # Escribe valores de la IA en una columna personalizada.
        # No fatal si la columna no existe: avisa pero no rompe el resto.
        try:
            db = self.gui.current_db.new_api
            valid = set(db.field_metadata.all_field_keys())
            if field not in valid:
                error_dialog(
                    self.gui, 'Falta una columna',
                    'La columna "{}" no existe en esta biblioteca, asi que no se '
                    'pudo guardar {} (el resto de la clasificacion si se aplico).'
                    '\n\nCreala en Preferencias -> Anadir columnas personalizadas '
                    '(tipo {}) o cambia el nombre en Configurar plugin -> Rescate '
                    'con IA.'.format(field, what, tipo), show=True)
                return
            db.set_field(field, id_map)
        except Exception:
            print("DEBUG ERROR en _apply_custom_writes:")
            traceback.print_exc()

    def _apply_reason_writes(self, field, id_map):
        self._apply_custom_writes(field, id_map, 'el motivo de la IA', 'texto largo')

    def _show_llm_results(self, stats):
        try:
            from qt.core import (QDialog, QVBoxLayout, QDialogButtonBox, QLabel,
                                 QTextEdit, Qt)

            candidates = stats.get('candidates', 0)
            details = stats.get('book_details', [])

            dialog = QDialog(self.gui)
            dialog.setWindowTitle('Resultados del rescate con IA')
            layout = QVBoxLayout(dialog)

            # Sin candidatos: mensaje breve y claro
            if candidates == 0 and not stats.get('cancelled'):
                dialog.resize(470, 210)
                msg = QLabel(
                    'No se encontraron libros sin clasificar entre los {} '
                    'revisados.\n\nEl rescate con IA solo actua sobre los libros '
                    'marcados como "[REVISAR]" o "(sin datos)". Clasifica primero '
                    'en local; el rescate se ocupa despues de los dudosos.'.format(
                        stats.get('total', 0)))
                msg.setWordWrap(True)
                msg.setAlignment(Qt.AlignmentFlag.AlignTop)
                layout.addWidget(msg)
                diag = QLabel(
                    'Diagnostico -> campo de libreria leido: "{}"  |  '
                    'libros con valor en ese campo: {}/{}\nEjemplos vistos: {}'.format(
                        stats.get('lib_field', '?'), stats.get('with_value', 0),
                        stats.get('total', 0),
                        '  //  '.join(stats.get('sample', [])) or '(ninguno)'))
                diag.setWordWrap(True)
                diag.setAlignment(Qt.AlignmentFlag.AlignTop)
                layout.addWidget(diag)
                dialog.resize(560, 300)
                btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
                btns.accepted.connect(dialog.accept)
                layout.addWidget(btns)
                dialog.exec()
                return

            lines = []
            if stats.get('cancelled'):
                lines.append('Cancelado por el usuario.')
            lines += [
                'Proveedor: {}   modelo: {}'.format(
                    stats.get('provider', '?'), stats.get('model_used', '?')),
                'Servidor:  {}'.format(stats.get('base_used', '?')),
                '',
                'Libros revisados:         {}'.format(stats.get('total', 0)),
                'No clasificados hallados: {}'.format(candidates),
                'Rescatados por la IA:     {}'.format(stats.get('rescued', 0)),
                'Errores:                  {}'.format(stats.get('errors', 0)),
            ]
            dist = stats.get('dist', {})
            if dist:
                lines += ['', 'Reparto por libreria (IA):']
                for name in sorted(dist, key=lambda k: -dist[k]):
                    lines.append('   {:<28} {}'.format(name, dist[name]))
            lbl = QLabel('\n'.join(lines))
            lbl.setAlignment(Qt.AlignmentFlag.AlignTop)
            layout.addWidget(lbl)

            if details:
                dialog.resize(620, 520)
                txt = QTextEdit()
                txt.setReadOnly(True)
                body = []
                for d in details:
                    body.append('{}  ->  {} ({:.0%})'.format(
                        d['title'][:46], d.get('library') or '?', d.get('confidence', 0)))
                    if d.get('moods'):
                        body.append('      tema: {}'.format(', '.join(d['moods'])))
                    if d.get('motivo'):
                        body.append('      motivo: {}'.format(d['motivo']))
                txt.setPlainText('\n'.join(body))
                layout.addWidget(txt)
            else:
                dialog.resize(470, 320)
                layout.addStretch(1)

            err_bits = []
            if stats.get('first_error'):
                err_bits.append('Primer error (con traza):\n' + str(stats['first_error']))
            if stats.get('failed_chunks'):
                err_bits.append('Tareas que fallaron:\n' +
                                '\n\n'.join(str(x) for x in stats['failed_chunks']))
            if err_bits:
                dialog.resize(700, 580)
                layout.addWidget(QLabel('Detalles de los errores:'))
                errbox = QTextEdit()
                errbox.setReadOnly(True)
                errbox.setPlainText('\n\n'.join(err_bits))
                layout.addWidget(errbox)

            btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
            btns.accepted.connect(dialog.accept)
            layout.addWidget(btns)
            dialog.exec()
        except Exception:
            print("DEBUG ERROR en _show_llm_results:")
            traceback.print_exc()

    # ─── Limpiar ──────────────────────────────────────────────────────────────

    def _clear_classifications(self, all_books=False):
        lib_field   = prefs.get('ml_library_field', 'tags')
        mood_field  = prefs.get('ml_mood_field', 'tags')
        lib_prefix  = prefs.get('ml_library_prefix', 'Biblioteca: ')
        mood_prefix = prefs.get('ml_mood_prefix', 'Tema: ')

        # Prefijos "propios" de cada campo destino: en 'tags' (compartido) se
        # filtra por el prefijo real; en una columna dedicada del plugin
        # (p.ej. #biblioteca) no hay prefijo — se vacía entera, porque todo su
        # contenido pertenece al plugin.
        field_prefixes = {}
        field_prefixes.setdefault(lib_field, set()).add(lib_prefix if lib_field == 'tags' else '')
        field_prefixes.setdefault(mood_field, set()).add(mood_prefix if mood_field == 'tags' else '')

        scope_label = 'TODA la biblioteca' if all_books else 'los libros seleccionados'
        if not question_dialog(
            self.gui, 'Confirmar limpieza',
            '¿Quitar las clasificaciones del plugin (librería y temas) de {}?'.format(scope_label)
        ):
            return

        book_ids = self._resolve_book_ids(all_books)
        if book_ids is None:
            return

        db = self.gui.current_db.new_api
        touched = set()
        try:
            for field, prefixes in field_prefixes.items():
                id_map = {}
                for bid in book_ids:
                    val = list(db.field_for(field, bid)) if field == 'tags' else db.field_for(field, bid)
                    if isinstance(val, (list, tuple)):
                        kept = [v for v in val if not any(str(v).startswith(p) for p in prefixes)]
                        id_map[bid] = kept
                    elif val:
                        kept = [v.strip() for v in str(val).split(',')
                                if v.strip() and not any(v.strip().startswith(p) for p in prefixes)]
                        id_map[bid] = ', '.join(kept)
                if id_map:
                    db.set_field(field, id_map)
                    touched.update(id_map.keys())
            if touched:
                self.gui.library_view.model().refresh_ids(list(touched))

            from qt.core import QDialog, QVBoxLayout, QDialogButtonBox, QLabel
            dlg = QDialog(self.gui)
            dlg.setWindowTitle('Limpieza completada')
            layout = QVBoxLayout(dlg)
            layout.addWidget(QLabel('Clasificaciones del plugin quitadas de <b>{}</b> libros.'.format(len(touched))))
            btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
            btns.accepted.connect(dlg.accept)
            layout.addWidget(btns)
            dlg.exec()
        except Exception:
            traceback.print_exc()
            error_dialog(self.gui, 'Error', 'No se pudo limpiar. Revisa el log.', show=True)

    # ─── Progreso / icono / config ────────────────────────────────────────────

    def _load_icon(self):
        try:
            if get_icons is not None:
                icon = get_icons('images/icon.png')
                if icon is not None:
                    self.qaction.setIcon(icon)
                    return
            data = None
            try:
                data = pkgutil.get_data(__package__, 'images/icon.png')
            except Exception:
                data = None
            if not data:
                # mismo problema que con model_weights.json: pkgutil no
                # siempre puede leer del zip real del plugin instalado.
                try:
                    from calibre.customize.ui import find_plugin
                    plugin = find_plugin('Book Classifier')
                    if plugin is not None:
                        data = plugin.load_resources(['images/icon.png']).get('images/icon.png')
                except Exception:
                    data = None
            if data:
                pixmap = QPixmap()
                if pixmap.loadFromData(data, 'PNG'):
                    self.qaction.setIcon(QIcon(pixmap))
        except Exception as e:
            print('DEBUG ERROR: No se pudo cargar el icono -', e)


    def show_config(self):
        from calibre_plugins.book_classifier.config import show_config_dialog
        show_config_dialog(self.gui)