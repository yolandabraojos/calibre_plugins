# -*- coding: utf-8 -*-
from __future__ import unicode_literals, division, absolute_import, print_function

import logging
import traceback
import threading

try:
    from qt.core import QMenu, QAction, pyqtSignal
except ImportError:
    from PyQt5.Qt import QMenu, QAction, pyqtSignal

from calibre.gui2 import error_dialog
from calibre.gui2.actions import InterfaceAction
from calibre.gui2.threaded_jobs import ThreadedJob

from .ui import ComparisonDialog, PairReviewDialog
from .jobs import scan_pairs_sync, _compare_pairs_chunk, _compare_pairs_chunk_ultrafast

logger = logging.getLogger('ebook_comparator.action')

CHUNK_SIZE = 20  # Number of pairs to compare in each chunk job


class _AutoSession:
    """All state for one automatic comparison run. Fully isolated."""
    def __init__(self, db, current_db, ultrafast=False):
        self.db            = db
        self.current_db    = current_db
        self.chunk_holders = []   # list of lists; each slot filled by one job
        self.lock          = threading.Lock()
        self.pending       = 0
        self.ultrafast     = ultrafast


class EbookComparatorAction(InterfaceAction):
    name = 'Ebook Comparator'
    action_type = 'current'
    action_spec = ('Comparar ebooks', None,
                   'Comparar similitud entre libros seleccionados', None)

    # Signal carries the session object; always emitted from any thread so the
    # GUI slot runs safely in the main thread.
    results_ready = pyqtSignal(object)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Single persistent review dialog; reused / updated across jobs.
        self._review_dialog = None
        # Track deleted book IDs across dialog sessions
        self._deleted_book_ids = set()

    def genesis(self):
        self.results_ready.connect(self._on_results_ready)
        menu = QMenu(self.gui)
        self.qaction.setMenu(menu)
        self.qaction.setIcon(get_icons('plugin.svg'))

        act_manual = QAction('Comparar manualmente', self.gui)
        act_manual.triggered.connect(self.compare_manual)
        menu.addAction(act_manual)

        act_sel = QAction('Comparar seleccionados automáticamente', self.gui)
        act_sel.triggered.connect(self.compare_automatic_selected)
        menu.addAction(act_sel)

        act_all = QAction('Comparar toda la biblioteca', self.gui)
        act_all.triggered.connect(self.compare_automatic_all)
        menu.addAction(act_all)

        menu.addSeparator()

        act_uf_sel = QAction('Ultrarrápido: solo 100% — seleccionados', self.gui)
        act_uf_sel.triggered.connect(self.compare_ultrafast_selected)
        menu.addAction(act_uf_sel)

        act_uf_all = QAction('Ultrarrápido: solo 100% — biblioteca completa', self.gui)
        act_uf_all.triggered.connect(self.compare_ultrafast_all)
        menu.addAction(act_uf_all)

        self.qaction.triggered.connect(self.compare_manual)

    # ------------------------------------------------------------------
    # Manual mode: exactly 2 books selected
    # ------------------------------------------------------------------

    def compare_manual(self):
        rows = self.gui.library_view.selectionModel().selectedRows()
        if len(rows) != 2:
            error_dialog(self.gui, 'Selección incorrecta',
                         'Selecciona exactamente 2 libros para comparar manualmente.',
                         show=True)
            return
        selected_ids = [self.gui.library_view.model().id(r) for r in rows]
        current_db = self.gui.current_db
        db = current_db.new_api if hasattr(current_db, 'new_api') else current_db
        dlg = ComparisonDialog(self.gui, db, selected_ids, current_db=current_db)
        dlg.exec_()

    # ------------------------------------------------------------------
    # Automatic mode: selected books
    # ------------------------------------------------------------------

    def compare_automatic_selected(self):
        rows = self.gui.library_view.selectionModel().selectedRows()
        if len(rows) < 2:
            error_dialog(self.gui, 'Selección incorrecta',
                         'Selecciona al menos 2 libros para la comparación automática.',
                         show=True)
            return
        selected_ids = [self.gui.library_view.model().id(r) for r in rows]
        current_db = self.gui.current_db
        db = current_db.new_api if hasattr(current_db, 'new_api') else current_db
        self._launch(db, current_db, restrict_to_ids=selected_ids)

    # ------------------------------------------------------------------
    # Automatic mode: whole library
    # ------------------------------------------------------------------

    def compare_automatic_all(self):
        current_db = self.gui.current_db
        db = current_db.new_api if hasattr(current_db, 'new_api') else current_db
        self._launch(db, current_db, restrict_to_ids=None)

    # ------------------------------------------------------------------
    # Ultra-fast mode: selected books (100 % identical pairs only)
    # ------------------------------------------------------------------

    def compare_ultrafast_selected(self):
        rows = self.gui.library_view.selectionModel().selectedRows()
        if len(rows) < 2:
            error_dialog(self.gui, 'Selección incorrecta',
                         'Selecciona al menos 2 libros para la comparación ultrarrápida.',
                         show=True)
            return
        selected_ids = [self.gui.library_view.model().id(r) for r in rows]
        current_db   = self.gui.current_db
        db           = current_db.new_api if hasattr(current_db, 'new_api') else current_db
        self._launch(db, current_db, restrict_to_ids=selected_ids, ultrafast=True)

    # ------------------------------------------------------------------
    # Ultra-fast mode: whole library (100 % identical pairs only)
    # ------------------------------------------------------------------

    def compare_ultrafast_all(self):
        current_db = self.gui.current_db
        db         = current_db.new_api if hasattr(current_db, 'new_api') else current_db
        self._launch(db, current_db, restrict_to_ids=None, ultrafast=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _launch(self, db, current_db, restrict_to_ids, ultrafast=False):
        scope = ('{} libros seleccionados'.format(len(restrict_to_ids))
                 if restrict_to_ids is not None else 'biblioteca completa')
        logger.info('[AUTO] _launch: %s', scope)

        # Close any previous review dialog so results don't mix between runs.
        if self._review_dialog is not None:
            try:
                if self._review_dialog.isVisible():
                    self._review_dialog.close()
            except Exception:
                pass
            self._review_dialog = None

        try:
            pairs = scan_pairs_sync(db, restrict_to_ids=restrict_to_ids)
        except Exception:
            logger.error('[AUTO] scan failed:\n%s', traceback.format_exc())
            error_dialog(self.gui, 'Error al escanear',
                         traceback.format_exc(), show=True)
            return

        logger.info('[AUTO] pairs found: %d', len(pairs))

        if not pairs:
            error_dialog(
                self.gui, 'Sin duplicados',
                'No se encontraron libros con el mismo título y autor '
                'en la selección indicada.\n\n'
                'Los libros deben compartir título Y autor exactos.',
                show=True)
            return

        total  = len(pairs)
        chunks = [pairs[i:i + CHUNK_SIZE]
                  for i in range(0, len(pairs), CHUNK_SIZE)]

        self.gui.status_bar.show_message(
            'Encontrados {} pares. Lanzando {} lotes...'.format(
                total, len(chunks)), 5000)

        session = _AutoSession(db, current_db, ultrafast=ultrafast)
        # Pre-allocate one slot per chunk so results can be accumulated safely
        # even if jobs complete out of order.
        session.chunk_holders = [[] for _ in chunks]
        with session.lock:
            session.pending = len(chunks)

        logger.info('[AUTO] launching %d chunk jobs', len(chunks))

        chunk_func = _compare_pairs_chunk_ultrafast if ultrafast else _compare_pairs_chunk
        mode_label = 'Ultrarrápido' if ultrafast else 'Comparando'

        submitted = 0
        for idx, (chunk, holder) in enumerate(zip(chunks, session.chunk_holders)):
            label = '{} pares {}-{} de {}'.format(
                mode_label,
                idx * CHUNK_SIZE + 1,
                min((idx + 1) * CHUNK_SIZE, total),
                total)
            try:
                job = ThreadedJob(
                    'ebook_comparator_compare',
                    label,
                    chunk_func,
                    (holder, chunk),
                    {},
                    # Capture idx and session by value via default args
                    lambda job, s=session, i=idx: self._on_chunk_done(job, s, i),
                )
                self.gui.job_manager.run_threaded_job(job)
                submitted += 1
                logger.info('[AUTO] chunk job %d submitted', idx)
            except Exception:
                logger.error('[AUTO] failed to submit chunk %d:\n%s',
                             idx, traceback.format_exc())
                with session.lock:
                    session.pending -= 1

        if submitted == 0:
            logger.warning('[AUTO] no jobs could be submitted')
            error_dialog(self.gui, 'Error al lanzar jobs',
                         'No se pudo lanzar ningún lote de comparación.', show=True)

    def _on_chunk_done(self, job, session, chunk_idx):
        """
        Called by Calibre's job manager when a chunk job finishes.
        This callback may arrive from a non-GUI thread, so we emit a signal
        to ensure all GUI work runs in the main thread.
        """
        failed    = job.failed
        exception = getattr(job, 'exception', None)
        logger.info('[AUTO] _on_chunk_done chunk=%d failed=%s session=%d',
                    chunk_idx, failed, id(session))

        if failed:
            logger.error('[AUTO] chunk %d failed: %s', chunk_idx, exception)

        with session.lock:
            session.pending -= 1
            pending = session.pending

        logger.info('[AUTO] pending=%d after chunk %d', pending, chunk_idx)

        # Emit after every completed job so the dialog is shown / updated as
        # soon as the first results are available.  The signal is queued and
        # runs in the GUI thread.
        self.results_ready.emit(session)

    def _on_results_ready(self, session):
        """
        GUI-thread slot: collect all results produced so far and either create
        the review dialog (first job) or append new results to it (subsequent jobs).

        KEY FIX: we never close and re-create the dialog.  Instead we call
        `add_results()` so the user keeps their current position and already-
        reviewed pairs are not lost.
        """
        # Collect every result that has been written by completed jobs so far.
        # chunk_holders[i] is [] until the job finishes, then [[...results...]]
        results = []
        for holder in session.chunk_holders:
            if holder:                  # job has finished and appended its list
                results.extend(holder[0])

        logger.info('[AUTO] _on_results_ready: %d total results so far, session=%d',
                    len(results), id(session))

        if not results:
            # First job finished but produced nothing (e.g. all errors).
            # Don't show an empty dialog yet; wait for more jobs unless all done.
            with session.lock:
                pending = session.pending
            if pending == 0:
                if session.ultrafast:
                    msg = ('No se encontró ningún par de libros con similitud del 100 %.\n\n'
                           'El modo ultrarrápido solo muestra libros idénticos '
                           'capítulo a capítulo.')
                else:
                    msg = 'No se pudo comparar ningún par de libros.'
                error_dialog(self.gui, 'Sin resultados', msg, show=True)
            return

        try:
            if self._review_dialog is None or not self._review_dialog.isVisible():
                # First time (or dialog was closed by user): create it.
                logger.info('[AUTO] creating new PairReviewDialog (%d results)',
                            len(results))
                dlg = PairReviewDialog(
                    self.gui,
                    session.db,
                    results,
                    current_db=session.current_db,
                    deleted_book_ids=self._deleted_book_ids,
                )
                self._review_dialog = dlg
                # Use show() (non-blocking) so subsequent job callbacks can
                # still reach this slot and call add_results() while the dialog
                # is open.
                dlg.show()
                dlg.raise_()
                dlg.activateWindow()
            else:
                # Dialog already open: just push the new accumulated results.
                # PairReviewDialog.add_results() is idempotent — it keeps track
                # of which pairs are already shown and only appends new ones.
                logger.info('[AUTO] updating existing PairReviewDialog (%d results)',
                            len(results))
                self._review_dialog.add_results(results)

        except Exception:
            logger.error('[AUTO] error showing/updating dialog:\n%s',
                         traceback.format_exc())
            error_dialog(self.gui, 'Error al mostrar resultados',
                         traceback.format_exc(), show=True)
            self._review_dialog = None