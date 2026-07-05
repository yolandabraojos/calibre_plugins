# -*- coding: utf-8 -*-
from __future__ import unicode_literals, division, absolute_import, print_function

__license__ = 'GPL v3'

import pkgutil
import traceback
from calibre.gui2.actions import InterfaceAction
from calibre.gui2 import error_dialog, question_dialog
from qt.core import QIcon, QMenu, QAction, QPixmap, QProgressDialog, Qt, QFontMetrics

from calibre_plugins.book_classifier.config import prefs
from calibre_plugins.book_classifier.ml_jobs import start_ml_classify_threaded, apply_ml_writes
from calibre_plugins.book_classifier.llm_jobs import start_llm_rescue_threaded

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

            worker, thread = start_ml_classify_threaded(self.gui, book_ids, settings)

            self._progress_dialog = QProgressDialog(
                'Clasificando con IA...', 'Cancelar', 0, len(book_ids), self.gui)
            self._progress_dialog.setWindowTitle('Clasificación IA')
            self._progress_dialog.setWindowModality(Qt.WindowModal)
            self._progress_dialog.setMinimumDuration(0)
            self._progress_dialog.setValue(0)
            self._progress_dialog.canceled.connect(worker.cancel)

            worker.progress.connect(self._update_progress)
            worker.finished.connect(self._finish_progress)
            worker.finished.connect(self._ml_job_finished)
            thread.finished.connect(self._clear_thread)

            self._active_worker = worker
            self._active_thread = thread
            thread.start()
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

    def _ml_job_finished(self, result):
        try:
            if not isinstance(result, dict):
                error_dialog(self.gui, 'Error', 'Resultado IA inesperado.', show=True)
                return
            if result.get('failed'):
                error_dialog(self.gui, 'Error',
                             'No se pudo cargar el modelo IA:\n{}'.format(result.get('error', '')),
                             show=True)
                return
            if result.get('writes_by_field'):
                apply_ml_writes(self.gui, result['writes_by_field'])
            self._show_ml_results(result)
        except Exception:
            print("DEBUG ERROR en _ml_job_finished:")
            traceback.print_exc()

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

            btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
            btns.accepted.connect(dialog.accept)
            layout.addWidget(btns)
            dialog.exec()
        except Exception:
            print("DEBUG ERROR en _show_ml_results:")
            traceback.print_exc()

    # ─── Rescate con IA (capa hibrida LLM) ────────────────────────────────────

    def _method_llm_rescue(self, all_books=False):
        book_ids = self._resolve_book_ids(all_books)
        if book_ids is None:
            return
        self._run_llm_rescue(book_ids)

    def _run_llm_rescue(self, book_ids):
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
            }
            worker, thread = start_llm_rescue_threaded(self.gui, book_ids, settings)

            self._progress_dialog = QProgressDialog(
                'Rescatando con IA...', 'Cancelar', 0, len(book_ids), self.gui)
            self._progress_dialog.setWindowTitle('Rescate con IA')
            self._progress_dialog.setWindowModality(Qt.WindowModal)
            self._progress_dialog.setMinimumDuration(0)
            self._progress_dialog.setValue(0)
            self._progress_dialog.canceled.connect(worker.cancel)

            worker.progress.connect(self._update_progress)
            worker.finished.connect(self._finish_progress)
            worker.finished.connect(self._llm_job_finished)
            thread.finished.connect(self._clear_thread)

            self._active_worker = worker
            self._active_thread = thread
            thread.start()
        except Exception:
            print("DEBUG ERROR: Fallo al lanzar el rescate IA")
            traceback.print_exc()

    def _llm_job_finished(self, result):
        try:
            if not isinstance(result, dict):
                error_dialog(self.gui, 'Error', 'Resultado de rescate inesperado.', show=True)
                return
            if result.get('failed'):
                error_dialog(self.gui, 'Rescate con IA',
                             result.get('error', 'Fallo desconocido'), show=True)
                return
            if result.get('writes_by_field'):
                apply_ml_writes(self.gui, result['writes_by_field'])
            self._show_llm_results(result)
        except Exception:
            print("DEBUG ERROR en _llm_job_finished:")
            traceback.print_exc()

    def _show_llm_results(self, stats):
        try:
            from qt.core import QDialog, QVBoxLayout, QDialogButtonBox, QLabel, QTextEdit
            dialog = QDialog(self.gui)
            dialog.setWindowTitle('Resultados del rescate con IA')
            dialog.resize(620, 520)
            layout = QVBoxLayout(dialog)

            lines = []
            if stats.get('cancelled'):
                lines.append('Cancelado por el usuario.')
            lines += [
                'Libros revisados:         {}'.format(stats.get('total', 0)),
                'No clasificados hallados: {}'.format(stats.get('candidates', 0)),
                'Rescatados por la IA:     {}'.format(stats.get('rescued', 0)),
                'Errores:                  {}'.format(stats.get('errors', 0)),
            ]
            if stats.get('first_error'):
                lines.append('Primer error: {}'.format(str(stats['first_error'])[:200]))
            lines += ['', 'Reparto por libreria (IA):']
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
                    body.append('{}  ->  {} ({:.0%})'.format(
                        d['title'][:46], d.get('library') or '?', d.get('confidence', 0)))
                    if d.get('moods'):
                        body.append('      tema: {}'.format(', '.join(d['moods'])))
                txt.setPlainText('\n'.join(body))
                layout.addWidget(txt)

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

    def _update_progress(self, index, title):
        if hasattr(self, '_progress_dialog') and self._progress_dialog:
            fm = QFontMetrics(self._progress_dialog.font())
            elided = fm.elidedText(title, Qt.ElideRight, 320)
            self._progress_dialog.setLabelText('Analizando: ' + elided)
            self._progress_dialog.setValue(index)

    def _finish_progress(self, result):
        if hasattr(self, '_progress_dialog') and self._progress_dialog:
            self._progress_dialog.setValue(self._progress_dialog.maximum())
            self._progress_dialog.close()
            self._progress_dialog = None

    def _clear_thread(self):
        self._active_worker = None
        self._active_thread = None

    def show_config(self):
        from calibre_plugins.book_classifier.config import show_config_dialog
        show_config_dialog(self.gui)
