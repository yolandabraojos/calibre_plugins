# -*- coding: utf-8 -*-
from __future__ import unicode_literals, division, absolute_import, print_function

__license__ = 'GPL v3'

import pkgutil
import traceback
from calibre.gui2.actions import InterfaceAction
from calibre.gui2 import error_dialog, info_dialog, question_dialog
from qt.core import QIcon, QMenu, QAction, QPixmap, QProgressDialog, Qt, QFontMetrics

from calibre_plugins.book_classifier.config import prefs
from calibre_plugins.book_classifier.jobs import start_classify_threaded, apply_writes

try:
    from calibre_plugins.book_classifier import get_icons
except ImportError:
    get_icons = None

class BookClassifierAction(InterfaceAction):
    name = 'Book Classifier'
    action_spec = ('Clasificar Libros', None, 'Clasificar libros automáticamente', None)
    action_type = 'current'

    def genesis(self):
        print("DEBUG: Plugin Book Classifier cargando...")
        self._load_icon()
        
        # Crear el menú desplegable
        menu = QMenu(self.gui)
        self.qaction.setMenu(menu)
        
        # Opción 1: Clasificar seleccionados
        act_selected = QAction('Clasificar seleccionados', self.gui)
        act_selected.triggered.connect(self.classify_selected)
        menu.addAction(act_selected)

        # Opción 2: Clasificar todos
        act_all = QAction('Clasificar TODOS los libros', self.gui)
        act_all.triggered.connect(self.classify_all)
        menu.addAction(act_all)
        
        # Separador visual
        menu.addSeparator()

        # Añadir la opción de configuración al menú
        act_config = QAction('Configurar plugin...', self.gui)
        act_config.triggered.connect(self.show_rules)
        menu.addAction(act_config)

        # Qué hacer si hacen clic en el botón directamente (no en el menú)
        self.qaction.triggered.connect(self.classify_selected)

        print("DEBUG: Plugin Book Classifier listo.")

    def _load_icon(self):
        try:
            if get_icons is not None:
                icon = get_icons('images/icon.png')
                if icon is not None:
                    self.qaction.setIcon(icon)
                    return

            data = pkgutil.get_data(__package__, 'images/icon.png')
            if data:
                pixmap = QPixmap()
                if pixmap.loadFromData(data, 'PNG'):
                    self.qaction.setIcon(QIcon(pixmap))
                else:
                    print('DEBUG ERROR: No se pudo cargar pixmap del icono')
            else:
                print('DEBUG ERROR: No se encontró images/icon.png en el paquete')
        except Exception as e:
            print('DEBUG ERROR: No se pudo cargar el icono manualmente -', e)

    def classify_selected(self):
        rows = self.gui.library_view.selectionModel().selectedRows()
        if not rows:
            error_dialog(self.gui, 'Error', 'No hay libros seleccionados.', show=True)
            return
        book_ids = [self.gui.library_view.model().id(r) for r in rows]
        print("DEBUG: Iniciando clasificación de {} libros".format(len(book_ids)))
        self._run_classifier(book_ids)

    def classify_all(self):
        if not question_dialog(self.gui, 'Confirmar', '¿Clasificar TODA la biblioteca?'):
            return
        book_ids = self.gui.current_db.all_ids()
        self._run_classifier(book_ids)

    def _run_classifier(self, book_ids):
        try:
            rules = prefs.get('rules', {})
            if not rules or not rules.get('categories'):
                error_dialog(self.gui, 'Error', 'No hay reglas configuradas. Ve a Configurar plugin.', show=True)
                return

            worker, thread = start_classify_threaded(
                gui           = self.gui,
                book_ids      = book_ids,
                rules         = rules,
                target_field  = prefs.get('target_field', 'tags'),
                overwrite     = prefs.get('overwrite_existing', False),
                dry_run       = prefs.get('dry_run', False),
                source_fields = prefs.get('source_fields', ['title', 'comments', 'tags', 'series']),
                extra_fields  = prefs.get('extra_fields', []),
            )

            self._progress_dialog = QProgressDialog('Analizando metadatos...', 'Cancelar', 0, len(book_ids), self.gui)
            self._progress_dialog.setWindowTitle('Clasificando libros')
            self._progress_dialog.setWindowModality(Qt.WindowModal)
            self._progress_dialog.setMinimumDuration(0)
            self._progress_dialog.setValue(0)
            self._progress_dialog.canceled.connect(worker.cancel)

            worker.progress.connect(self._update_progress)
            worker.finished.connect(self._finish_progress)
            worker.finished.connect(self._job_finished)
            thread.finished.connect(self._clear_thread)

            self._active_worker = worker
            self._active_thread = thread
            thread.start()
        except Exception:
            print("DEBUG ERROR: Fallo al lanzar el clasificador")
            traceback.print_exc()

    def _update_progress(self, index, title):
        if hasattr(self, '_progress_dialog') and self._progress_dialog:
            fm = QFontMetrics(self._progress_dialog.font())
            elided_title = fm.elidedText(title, Qt.ElideRight, 320)
            self._progress_dialog.setLabelText('Analizando: ' + elided_title)
            self._progress_dialog.setValue(index)

    def _finish_progress(self, result):
        if hasattr(self, '_progress_dialog') and self._progress_dialog:
            self._progress_dialog.setValue(self._progress_dialog.maximum())
            self._progress_dialog.close()
            self._progress_dialog = None

    def _clear_thread(self):
        self._active_thread = None

    def _job_finished(self, result):
        if isinstance(result, dict):
            job_failed = result.get('failed', False)
            stats = result
        else:
            job_failed = result.failed
            stats = result.result

        if job_failed:
            print("DEBUG: El trabajo de fondo falló")
            error_dialog(self.gui, 'Error', 'El trabajo falló. Revisa el log.', show=True)
            return

        if not prefs.get('dry_run', False) and stats.get('writes'):
            print("DEBUG: Aplicando cambios a la DB...")
            apply_writes(self.gui, stats['writes'], prefs.get('target_field', 'tags'))

        status_lines = [
            'Total escaneados: {}'.format(stats.get('total', 0)),
            'Clasificados: {}'.format(stats.get('classified', 0)),
            'Saltados: {}'.format(stats.get('skipped', 0)),
            'Errores: {}'.format(stats.get('errors', 0)),
        ]
        if stats.get('cancelled'):
            status_lines.insert(0, 'Cancelado por el usuario.')

        info_dialog(self.gui, 'Fin', '\n'.join(status_lines), show=True)

    def show_rules(self):
        from calibre_plugins.book_classifier.config import show_config_dialog
        show_config_dialog(self.gui)