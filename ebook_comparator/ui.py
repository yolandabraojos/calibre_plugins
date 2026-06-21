# -*- coding: utf-8 -*-
from __future__ import unicode_literals, division, absolute_import, print_function

import logging
import os
from collections import defaultdict
from functools import partial

from PyQt5.Qt import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QColor, Qt, QFrame, QSizePolicy
)
from calibre.gui2 import error_dialog, question_dialog

from .jobs import ComparisonWorker

logger = logging.getLogger('ebook_comparator.ui')


def _resize_mode(header, mode_name):
    if hasattr(QHeaderView, mode_name):
        return getattr(QHeaderView, mode_name)
    return getattr(QHeaderView.ResizeMode, mode_name)


def _human_size(size):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size < 1024.0:
            return '{:.1f} {}'.format(size, unit)
        size /= 1024.0
    return '{:.1f} TB'.format(size)


def _pct_color(pct):
    if pct >= 75:
        return '#27ae60'
    if pct >= 40:
        return '#e67e22'
    return '#c0392b'


def _open_in_editor(gui, book_id, fmt, path=None):
    """
    Abre un libro en el EDITOR de libros de calibre (Tweak ePub / "Editar
    libro").  Si por cualquier motivo no se puede, intenta abrirlo con la
    aplicación por defecto del sistema operativo.  Devuelve True si tuvo éxito.
    """
    if book_id is not None and fmt:
        try:
            gui.iactions['Tweak ePub'].ebook_edit_format(book_id, fmt)
            return True
        except Exception:
            logger.exception('No se pudo abrir en el editor de calibre (id=%s fmt=%s)',
                             book_id, fmt)
    if path:
        try:
            from calibre.gui2 import open_local_file
            open_local_file(path)
            return True
        except Exception:
            logger.exception('No se pudo abrir el fichero localmente: %s', path)
    return False


# ===========================================================================
# PairReviewDialog — shows comparison results pair by pair, allows deletion
# ===========================================================================

class PairReviewDialog(QDialog):
    """
    Shows a list of compared pairs.  The user can navigate pair by pair,
    see the similarity score + chapter table, and delete one of the two books.

    Results can be added incrementally via add_results() as automatic jobs
    complete, without closing or resetting the dialog.
    """

    def __init__(self, parent, db, results, current_db=None, deleted_book_ids=None):
        super().__init__(parent)
        self.gui = parent
        self.db = db
        self.current_db = current_db or db
        # Track IDs that have already been deleted (shared across dialog sessions)
        self.ids_deleted = deleted_book_ids if deleted_book_ids is not None else set()
        
        # Mutable list of result dicts.  New pairs are appended by add_results().
        # Filter out pairs containing already-deleted books
        self.results = [r for r in results 
                       if r.get('book_a', {}).get('id') not in self.ids_deleted and
                          r.get('book_b', {}).get('id') not in self.ids_deleted]
        
        # Track pair IDs already present to avoid duplicates when add_results()
        # is called multiple times with the accumulated list.
        self._seen_pair_keys = set(self._pair_key(r) for r in self.results)
        self.index = 0
        # Track IDs to delete (marked for deletion but not yet deleted)
        self.ids_to_delete = []
        # Metadatos de los libros marcados, guardados en el momento del marcado
        # para poder mostrarlos en la confirmación aunque el par ya no esté en
        # self.results (por ejemplo si fue filtrado por un borrado anterior).
        self._marked_books_info = {}   # {book_id: {'title':..,'format':..,'id':..}}
        # Pair keys already processed by _auto_mark_100pct_pairs to avoid
        # re-marking when add_results() is called with accumulated results.
        self._auto_considered_pair_keys = set()
        self._setup_ui()
        self._auto_mark_100pct_pairs()
        self._load_pair()

    # ------------------------------------------------------------------
    # Public API used by action.py to push new results from later jobs
    # ------------------------------------------------------------------

    def add_results(self, all_results_so_far):
        """
        Called from the GUI thread each time a new chunk job completes.
        ``all_results_so_far`` is the full accumulated list (not just the delta).
        We detect new pairs by their (book_a_id, book_b_id) key and append only
        those that haven't been shown yet and don't contain deleted books.

        The user's current navigation position is preserved.
        """
        new_pairs = []
        for r in all_results_so_far:
            key = self._pair_key(r)
            a = r.get('book_a', {})
            b = r.get('book_b', {})
            # Skip if already seen OR if any book in the pair has been deleted
            if key not in self._seen_pair_keys and \
               a.get('id') not in self.ids_deleted and \
               b.get('id') not in self.ids_deleted:
                self._seen_pair_keys.add(key)
                new_pairs.append(r)

        if not new_pairs:
            return

        logger.info('[UI] add_results: %d new pairs (total now %d)',
                    len(new_pairs), len(self.results) + len(new_pairs))

        self.results.extend(new_pairs)
        self._auto_mark_100pct_pairs()
        # Refresh navigation labels (total count changes) without moving index.
        self._refresh_nav()
        # Refresh delete buttons for the currently displayed pair in case one of
        # the new auto-marks affects it.
        if self.results:
            idx = max(0, min(self.index, len(self.results) - 1))
            pair = self.results[idx]
            self._refresh_delete_btns(pair['book_a']['id'], pair['book_b']['id'])

    @staticmethod
    def _pair_key(result):
        """Stable key that identifies a pair regardless of job order."""
        a = result.get('book_a', {})
        b = result.get('book_b', {})
        return (a.get('id'), b.get('id'))

    # ------------------------------------------------------------------
    # Auto-marking of 100 % identical pairs
    # ------------------------------------------------------------------

    def _auto_mark_100pct_pairs(self):
        """
        For every pair with exactly 100 % similarity that has not been
        processed yet, automatically mark one of the two books for deletion:

        - EPUB vs AZW3  → mark the AZW3.
        - Same format   → mark the larger file (by size).

        Safety guarantee: at least one book per (title, authors) group is
        always left unmarked, even if that means overriding the rule above.
        The book kept alive is the one with the best "quality" score
        (EPUB preferred over AZW3, then smallest file size).
        """
        # ── Step 1: collect candidate marks from new 100 % pairs ──────────
        # Maps book_id → book-info dict for books we want to mark.
        candidate_marks = {}

        for pair in self.results:
            key = self._pair_key(pair)
            if key in self._auto_considered_pair_keys:
                continue
            self._auto_considered_pair_keys.add(key)

            if pair.get('similarity', -1.0) < 100.0:
                continue

            a = pair['book_a']
            b = pair['book_b']
            fmt_a = a.get('format', '').upper()
            fmt_b = b.get('format', '').upper()

            if fmt_a != fmt_b:
                # Mixed formats: always prefer EPUB → mark the AZW3
                to_mark = a if fmt_a == 'AZW3' else b
            else:
                # Same format: mark the smaller file (keep the larger)
                to_mark = a if a.get('size', 0) <= b.get('size', 0) else b

            if to_mark['id'] not in self.ids_deleted:
                candidate_marks[to_mark['id']] = to_mark

        if not candidate_marks:
            return

        # ── Step 2: build group map (title + authors) ─────────────────────
        groups = defaultdict(set)   # group_key → set of all book_ids
        all_books = {}              # book_id   → book-info dict

        for pair in self.results:
            a = pair['book_a']
            b = pair['book_b']
            group_key = (a.get('title', '').lower(), a.get('authors', '').lower())
            groups[group_key].add(a['id'])
            groups[group_key].add(b['id'])
            all_books[a['id']] = a
            all_books[b['id']] = b

        # ── Step 3: safety check — at least one book per group survives ───
        for group_key, book_ids in groups.items():
            already_marked = book_ids & set(self.ids_to_delete)
            new_candidates = book_ids & set(candidate_marks.keys())
            would_be_marked = already_marked | new_candidates
            surviving = book_ids - would_be_marked - self.ids_deleted

            if surviving:
                continue  # At least one book will remain unmarked

            # All books in this group would be deleted — un-mark the best one.
            # "Best": EPUB over AZW3, then smallest size.
            all_to_consider = would_be_marked - self.ids_deleted
            if not all_to_consider:
                continue

            def _quality(bid):
                bk = all_books.get(bid, {})
                fmt_score = 0 if bk.get('format', '').upper() == 'EPUB' else 1
                return (fmt_score, bk.get('size', 0))

            best_bid = min(all_to_consider, key=_quality)
            if best_bid in candidate_marks:
                del candidate_marks[best_bid]
            elif best_bid in self.ids_to_delete:
                self.ids_to_delete.remove(best_bid)
                self._marked_books_info.pop(best_bid, None)
            logger.info('[AUTO-MARK] Preserving book id=%s (group safety: %r)',
                        best_bid, group_key)

        # ── Step 4: apply remaining candidate marks ────────────────────────
        for book_id, book_info in candidate_marks.items():
            if book_id not in self.ids_to_delete:
                self.ids_to_delete.append(book_id)
                self._marked_books_info[book_id] = {
                    'id':     book_id,
                    'title':  book_info.get('title', '?'),
                    'format': book_info.get('format', '?'),
                }
                logger.info('[AUTO-MARK] Marked book id=%s (%s) at 100 %% similarity',
                            book_id, book_info.get('format', '?'))

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self):
        self.setWindowTitle('Revisión de duplicados')
        self.setMinimumWidth(780)
        self.setMinimumHeight(540)
        root = QVBoxLayout(self)
        root.setSpacing(8)

        # Navigation label
        self.nav_label = QLabel('')
        self.nav_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self.nav_label)

        # Title / authors
        self.title_label = QLabel('')
        self.title_label.setWordWrap(True)
        self.title_label.setAlignment(Qt.AlignCenter)
        font = self.title_label.font()
        font.setBold(True)
        self.title_label.setFont(font)
        root.addWidget(self.title_label)

        # Global similarity
        self.similarity_label = QLabel('')
        self.similarity_label.setAlignment(Qt.AlignCenter)
        font2 = self.similarity_label.font()
        font2.setPointSize(16)
        font2.setBold(True)
        self.similarity_label.setFont(font2)
        root.addWidget(self.similarity_label)

        # Book A / Book B info row
        info_frame = QFrame()
        info_frame.setFrameShape(QFrame.StyledPanel)
        info_layout = QHBoxLayout(info_frame)

        self.book_a_label = QLabel('')
        self.book_a_label.setWordWrap(True)
        self.book_a_label.setAlignment(Qt.AlignCenter)
        info_layout.addWidget(self.book_a_label, 1)

        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        info_layout.addWidget(sep)

        self.book_b_label = QLabel('')
        self.book_b_label.setWordWrap(True)
        self.book_b_label.setAlignment(Qt.AlignCenter)
        info_layout.addWidget(self.book_b_label, 1)

        root.addWidget(info_frame)

        # Unique chapters info
        self.unique_label = QLabel('')
        self.unique_label.setAlignment(Qt.AlignCenter)
        self.unique_label.setWordWrap(True)
        root.addWidget(self.unique_label)

        # Chapter table
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([
            'Capítulo (libro A)', 'Mejor coincidencia (libro B)', 'Similitud'
        ])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, _resize_mode(hh, 'Stretch'))
        hh.setSectionResizeMode(1, _resize_mode(hh, 'Stretch'))
        hh.setSectionResizeMode(2, _resize_mode(hh, 'ResizeToContents'))
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        root.addWidget(self.table)

        # Error label (hidden unless there is an error)
        self.error_label = QLabel('')
        self.error_label.setAlignment(Qt.AlignCenter)
        self.error_label.setStyleSheet('color: #c0392b;')
        self.error_label.setVisible(False)
        root.addWidget(self.error_label)

        # Button row
        btn_row = QHBoxLayout()

        self.prev_btn = QPushButton('← Anterior')
        self.prev_btn.clicked.connect(self._prev)
        btn_row.addWidget(self.prev_btn)

        self.next_btn = QPushButton('Siguiente →')
        self.next_btn.clicked.connect(self._next)
        btn_row.addWidget(self.next_btn)

        self.open_a_btn = QPushButton('✏  Editar libro A')
        self.open_a_btn.setToolTip('Abrir el libro A en el editor de calibre')
        self.open_a_btn.clicked.connect(lambda: self._open_book('a'))
        btn_row.addWidget(self.open_a_btn)

        self.open_b_btn = QPushButton('✏  Editar libro B')
        self.open_b_btn.setToolTip('Abrir el libro B en el editor de calibre')
        self.open_b_btn.clicked.connect(lambda: self._open_book('b'))
        btn_row.addWidget(self.open_b_btn)

        btn_row.addStretch(1)

        self.delete_a_btn = QPushButton('🗑  Marcar libro A')
        self.delete_a_btn.setToolTip('Marcar/desmarcar el libro A para borrado')
        self.delete_a_btn.clicked.connect(lambda: self._toggle_mark('a'))
        btn_row.addWidget(self.delete_a_btn)

        self.delete_b_btn = QPushButton('🗑  Marcar libro B')
        self.delete_b_btn.setToolTip('Marcar/desmarcar el libro B para borrado')
        self.delete_b_btn.clicked.connect(lambda: self._toggle_mark('b'))
        btn_row.addWidget(self.delete_b_btn)

        btn_row.addStretch(1)

        self.close_btn = QPushButton('Cerrar')
        self.close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.close_btn)

        root.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Navigation helpers
    # ------------------------------------------------------------------

    def _refresh_nav(self):
        """Update navigation label and button states without reloading content."""
        total = len(self.results)
        self.nav_label.setText('Par {} de {}'.format(self.index + 1, total))
        self.prev_btn.setEnabled(self.index > 0)
        self.next_btn.setEnabled(self.index < total - 1)

    def _load_pair(self):
        if not self.results:
            self._show_empty()
            return

        # Clamp index
        self.index = max(0, min(self.index, len(self.results) - 1))
        pair = self.results[self.index]

        self._refresh_nav()

        a = pair['book_a']
        b = pair['book_b']
        self.title_label.setText(
            '{} · {}'.format(a['title'], a['authors'])
        )

        similarity = pair.get('similarity', -1.0)
        has_error = 'error' in pair

        if has_error:
            self.similarity_label.setText('Error al comparar')
            self.similarity_label.setStyleSheet('color: #c0392b;')
            self.error_label.setText(pair['error'])
            self.error_label.setVisible(True)
            self.table.setRowCount(0)
            self.unique_label.setText('')
        else:
            color = _pct_color(similarity)
            self.similarity_label.setText(
                '<span style="color:{}">{:.1f}% similitud</span>'.format(
                    color, similarity))
            self.similarity_label.setStyleSheet('')
            self.error_label.setVisible(False)
            self._fill_chapter_table(pair)
            
        self.book_a_label.setText(
            '<b>Libro A (ID: {})</b><br>{}<br><small>{} · {}</small>'.format(
                a['id'], a['title'], a['format'], _human_size(a['size'])))

        self.book_b_label.setText(
            '<b>Libro B (ID: {})</b><br>{}<br><small>{} · {}</small>'.format(
                b['id'], b['title'], b['format'], _human_size(b['size'])))

        self._refresh_delete_btns(a['id'], b['id'])

    def _open_book(self, which):
        """Abre en el editor de calibre el libro A o B del par mostrado."""
        if not self.results:
            return
        pair = self.results[self.index]
        bk = pair['book_a'] if which == 'a' else pair['book_b']
        ok = _open_in_editor(self.gui, bk.get('id'), bk.get('format'), bk.get('path'))
        if not ok:
            error_dialog(self, 'No se pudo abrir',
                         'No se pudo abrir el libro {} en el editor.'.format(which.upper()),
                         show=True)

    def _refresh_delete_btns(self, id_a, id_b):
        """
        Actualiza el texto, color y estado de los botones de marcado/desmarcado
        según si cada libro está ya en la lista de pendientes de borrado.
        Se llama desde _load_pair cada vez que se muestra un par.
        """
        for btn, book_id, label in (
            (self.delete_a_btn, id_a, 'A'),
            (self.delete_b_btn, id_b, 'B'),
        ):
            if book_id in self.ids_to_delete:
                btn.setText('↩  Desmarcar libro {}'.format(label))
                btn.setToolTip('Quitar libro {} de la lista de borrado'.format(label))
                btn.setStyleSheet('background-color: #e74c3c; color: white; font-weight: bold;')
            else:
                btn.setText('🗑  Marcar libro {}'.format(label))
                btn.setToolTip('Marcar libro {} para borrado al cerrar'.format(label))
                btn.setStyleSheet('')
            btn.setEnabled(True)

    def _fill_chapter_table(self, pair):
        rows      = pair.get('chapter_map', [])
        ignored_a = pair.get('ignored_a', [])
        ignored_b = pair.get('ignored_b', [])

        total_rows = len(rows) + len(ignored_a) + len(ignored_b)
        self.table.setRowCount(total_rows)

        # ── Filas de comparación ──────────────────────────────────────────
        for i, row in enumerate(rows):
            raw_a  = row['chapter_a']
            raw_b  = row['best_match_b']
            name_a = raw_a.split('/')[-1] if raw_a else '—'
            name_b = raw_b.split('/')[-1] if raw_b else '—'
            score  = row['similarity']

            item_a = QTableWidgetItem(name_a)
            item_b = QTableWidgetItem(name_b)
            item_s = QTableWidgetItem('{:.1f}%'.format(score))
            item_s.setTextAlignment(Qt.AlignCenter)

            bg = QColor(_pct_color(score))
            bg.setAlpha(50)
            for item in (item_a, item_b, item_s):
                item.setBackground(bg)
                if row.get('is_unique'):
                    font = item.font()
                    font.setItalic(True)
                    item.setFont(font)

            self.table.setItem(i, 0, item_a)
            self.table.setItem(i, 1, item_b)
            self.table.setItem(i, 2, item_s)

        # ── Filas de archivos ignorados ───────────────────────────────────
        # Fondo gris neutro, texto en cursiva, columna de similitud con la razón.
        ig_bg = QColor('#888888')
        ig_bg.setAlpha(30)
        base_row = len(rows)

        for j, ig in enumerate(ignored_a):
            name  = ig['name'].split('/')[-1]
            razón = 'Ignorado ({})'.format(ig['reason'])
            item_a = QTableWidgetItem(name)
            item_b = QTableWidgetItem('—')
            item_s = QTableWidgetItem(razón)
            item_s.setTextAlignment(Qt.AlignCenter)
            for item in (item_a, item_b, item_s):
                item.setBackground(ig_bg)
                font = item.font()
                font.setItalic(True)
                item.setFont(font)
                item.setForeground(QColor('#888888'))
            self.table.setItem(base_row + j, 0, item_a)
            self.table.setItem(base_row + j, 1, item_b)
            self.table.setItem(base_row + j, 2, item_s)

        base_row += len(ignored_a)
        for j, ig in enumerate(ignored_b):
            name  = ig['name'].split('/')[-1]
            razón = 'Ignorado ({})'.format(ig['reason'])
            item_a = QTableWidgetItem('—')
            item_b = QTableWidgetItem(name)
            item_s = QTableWidgetItem(razón)
            item_s.setTextAlignment(Qt.AlignCenter)
            for item in (item_a, item_b, item_s):
                item.setBackground(ig_bg)
                font = item.font()
                font.setItalic(True)
                item.setFont(font)
                item.setForeground(QColor('#888888'))
            self.table.setItem(base_row + j, 0, item_a)
            self.table.setItem(base_row + j, 1, item_b)
            self.table.setItem(base_row + j, 2, item_s)

    def _show_empty(self):
        self.nav_label.setText('No quedan pares.')
        self.title_label.setText('')
        self.similarity_label.setText('')
        self.book_a_label.setText('')
        self.book_b_label.setText('')
        self.unique_label.setText('')
        self.table.setRowCount(0)
        for btn, label in ((self.delete_a_btn, 'A'), (self.delete_b_btn, 'B')):
            btn.setText('🗑  Marcar libro {}'.format(label))
            btn.setStyleSheet('')
            btn.setEnabled(False)
        self.prev_btn.setEnabled(False)
        self.next_btn.setEnabled(False)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _prev(self):
        self.index -= 1
        self._load_pair()

    def _next(self):
        self.index += 1
        self._load_pair()

    # ------------------------------------------------------------------
    # Deletion
    # ------------------------------------------------------------------

    def _toggle_mark(self, which):
        """
        Marca o desmarca un libro para borrado diferido.

        - Si el libro NO estaba marcado → se añade a ids_to_delete y el botón
          cambia a rojo «Desmarcar». El par sigue visible para que el usuario
          pueda cambiar de opinión navegando hacia atrás.
        - Si el libro YA estaba marcado → se elimina de ids_to_delete y el
          botón vuelve al estado normal.

        El borrado real ocurre solo al cerrar el diálogo (_perform_pending_deletions).
        """
        if not self.results:
            return
        pair   = self.results[self.index]
        book   = pair['book_a'] if which == 'a' else pair['book_b']
        book_id = book['id']

        if book_id in self.ids_to_delete:
            # Desmarcar
            self.ids_to_delete.remove(book_id)
            self._marked_books_info.pop(book_id, None)
            logger.info('[UI] _toggle_mark: desmarcado libro id=%s', book_id)
        else:
            # Marcar — guardar metadatos ahora, mientras el par está visible
            self.ids_to_delete.append(book_id)
            self._marked_books_info[book_id] = {
                'id':     book_id,
                'title':  book.get('title', '?'),
                'format': book.get('format', '?'),
            }
            logger.info('[UI] _toggle_mark: marcado libro id=%s', book_id)

        # Refrescar solo los botones del par actual (sin recargar toda la UI)
        a_id = pair['book_a']['id']
        b_id = pair['book_b']['id']
        self._refresh_delete_btns(a_id, b_id)
        # Actualizar también el nav_label por si el contador de pendientes
        # fuera visible en el futuro; por ahora es un no-op limpio.
        self._refresh_nav()

    def _perform_pending_deletions(self):
        """Perform all marked deletions and refresh view once."""
        if not self.ids_to_delete:
            return False

        # Construir lista de títulos desde _marked_books_info, que se actualiza
        # en el momento del marcado y no depende de que el par siga en self.results.
        title_lines = [
            '{} (ID {}, {})'.format(
                info['title'], info['id'], info['format'])
            for book_id in self.ids_to_delete
            for info in [self._marked_books_info.get(book_id, {'title': '?', 'id': book_id, 'format': '?'})]
        ]

        count = len(self.ids_to_delete)
        msg = ('<p>Vas a borrar definitivamente <b>{} libro{}</b>.</p>'
               '<p>Despliega los detalles para ver la lista completa.</p>'
               '<p><b>Esta acción no se puede deshacer.</b></p>').format(
            count, 's' if count > 1 else '')
        det_msg = '\n'.join(title_lines)

        if not question_dialog(self, 'Confirmar borrado', msg, det_msg=det_msg):
            return False

        try:
            db_del = getattr(self.current_db, 'db', self.current_db)
            if not hasattr(db_del, 'delete_book'):
                db_del = self.db
            if not hasattr(db_del, 'delete_book'):
                raise AttributeError(
                    'delete_book no disponible en el objeto de base de datos.')

            # Delete all marked books
            for book_id in self.ids_to_delete:
                db_del.delete_book(book_id)
                logger.info('Deleted book id=%s', book_id)
                # Mark as deleted to filter from future results
                self.ids_deleted.add(book_id)

            # Remove pairs containing deleted books from self.results
            self.results = [r for r in self.results
                           if r.get('book_a', {}).get('id') not in self.ids_to_delete and
                              r.get('book_b', {}).get('id') not in self.ids_to_delete]
            
            # Clear the pending list and cached metadata
            self.ids_to_delete.clear()
            self._marked_books_info.clear()

            # Refresh library view once
            try:
                model = self.gui.library_view.model()
                if hasattr(model, 'refresh'):
                    model.refresh()
                elif hasattr(model, 'beginResetModel'):
                    model.beginResetModel()
                    model.endResetModel()
            except Exception:
                pass

            # Reload current pair view (it may now be empty or pointing beyond bounds)
            self._load_pair()

            return True
        except Exception as e:
            error_dialog(self, 'Error al borrar libros', str(e), show=True)
            return False

    def accept(self):
        """Handle dialog close: offer to delete marked books before closing."""
        if self.ids_to_delete:
            deleted = self._perform_pending_deletions()
            if not deleted:
                return  # User cancelled or error — keep dialog open
        super().accept()


# ===========================================================================
# ComparisonDialog — manual 2-book comparison
# ===========================================================================

class ComparisonDialog(QDialog):

    def __init__(self, parent, db, book_ids, current_db=None):
        super().__init__(parent)
        self.gui = parent
        self.db = db
        self.current_db = current_db or db
        self.book_ids = book_ids
        self.worker = None
        self.book_paths = []
        self.book_formats = []
        self._setup_ui()

    @staticmethod
    def _header_resize_mode(mode_name):
        if hasattr(QHeaderView, mode_name):
            return getattr(QHeaderView, mode_name)
        return getattr(QHeaderView.ResizeMode, mode_name)

    def _setup_ui(self):
        self.setWindowTitle('Comparador de ebooks')
        self.setMinimumWidth(680)
        root = QVBoxLayout(self)
        root.setSpacing(8)

        titles = [self.db.field_for('title', bid) for bid in self.book_ids[:2]]
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        fl = QVBoxLayout(frame)
        fl.addWidget(QLabel('<b>Libro A (ID: {}):</b> {}'.format(self.book_ids[0], titles[0])))
        fl.addWidget(QLabel('<b>Libro B (ID: {}):</b> {}'.format(self.book_ids[1], titles[1])))
        root.addWidget(frame)


        method_row = QHBoxLayout()
        method_row.addWidget(QLabel('Método de comparación:'))
        self.method_combo = QComboBox()
        self.method_combo.addItems([
            'combined  — equilibrado (recomendado)',
            'tfidf     — mejor para reordenaciones',
        ])
        method_row.addWidget(self.method_combo)
        root.addLayout(method_row)

        control_row = QHBoxLayout()
        self.btn = QPushButton('▶  Comparar')
        self.btn.setFixedHeight(36)
        self.btn.clicked.connect(self._run)
        control_row.addWidget(self.btn)

        self.open_a_btn = QPushButton('✏  Editar A')
        self.open_a_btn.setToolTip('Abrir el libro A en el editor de calibre')
        self.open_a_btn.clicked.connect(partial(self._open_book_manual, 0))
        control_row.addWidget(self.open_a_btn)

        self.open_b_btn = QPushButton('✏  Editar B')
        self.open_b_btn.setToolTip('Abrir el libro B en el editor de calibre')
        self.open_b_btn.clicked.connect(partial(self._open_book_manual, 1))
        control_row.addWidget(self.open_b_btn)

        self.delete_a_btn = QPushButton('Borrar libro A')
        self.delete_a_btn.setEnabled(False)
        self.delete_a_btn.clicked.connect(partial(self._delete_book, 0))
        control_row.addWidget(self.delete_a_btn)

        self.delete_b_btn = QPushButton('Borrar libro B')
        self.delete_b_btn.setEnabled(False)
        self.delete_b_btn.clicked.connect(partial(self._delete_book, 1))
        control_row.addWidget(self.delete_b_btn)

        root.addLayout(control_row)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        
        # NUEVO: Etiqueta de estado para dar detalles al usuario
        self.status_label = QLabel("Preparando archivos...", self)
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setVisible(False)
        
        root.addWidget(self.status_label)
        root.addWidget(self.progress)

        self.global_label = QLabel('')
        self.global_label.setAlignment(Qt.AlignCenter)
        font = self.global_label.font()
        font.setPointSize(18)
        font.setBold(True)
        self.global_label.setFont(font)
        root.addWidget(self.global_label)

        self.file_info_label = QLabel('')
        self.file_info_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self.file_info_label)

        self.stats_label = QLabel('')
        self.stats_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self.stats_label)

        self.unique_label = QLabel('')
        self.unique_label.setAlignment(Qt.AlignCenter)
        self.unique_label.setWordWrap(True)
        root.addWidget(self.unique_label)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        root.addWidget(sep)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([
            'Capítulo (libro A)', 'Mejor coincidencia (libro B)', 'Similitud'
        ])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, self._header_resize_mode('Stretch'))
        hh.setSectionResizeMode(1, self._header_resize_mode('Stretch'))
        hh.setSectionResizeMode(2, self._header_resize_mode('ResizeToContents'))
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setVisible(False)
        root.addWidget(self.table)

    def _open_book_manual(self, idx):
        """Abre en el editor de calibre el libro A (idx=0) o B (idx=1)."""
        try:
            bid = self.book_ids[idx]
        except IndexError:
            return
        fmt = None
        fmts = [f.upper() for f in (self.db.formats(bid) or [])]
        for cand in ('EPUB', 'AZW3'):
            if cand in fmts:
                fmt = cand
                break
        path = self.db.format_abspath(bid, fmt) if fmt else None
        if not _open_in_editor(self.gui, bid, fmt, path):
            error_dialog(self, 'No se pudo abrir',
                         'No se pudo abrir el libro en el editor.', show=True)

    def _method_key(self):
        return self.method_combo.currentText().split()[0]

    def _run(self):
        self.book_paths = []
        self.book_formats = []
        for bid in self.book_ids[:2]:
            fmts = [fmt.upper() for fmt in (self.db.formats(bid) or [])]
            for fmt in ('EPUB', 'AZW3'):
                if fmt in fmts:
                    self.book_formats.append(fmt)
                    self.book_paths.append(self.db.format_abspath(bid, fmt))
                    break

        if len(self.book_paths) < 2:
            error_dialog(self, 'Formato no compatible',
                         'Ambos libros deben tener formato EPUB o AZW3.', show=True)
            return

        self.btn.setEnabled(False)
        self.global_label.setText('')
        self.stats_label.setText('')
        self.table.setVisible(False)
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.status_label.setVisible(True)

        self.worker = ComparisonWorker(
            self.book_paths[0], self.book_paths[1], self._method_key())
        self.worker.progress.connect(self.progress.setValue)
        self.worker.finished.connect(self._show_results)
        self.worker.error.connect(self._show_error)
        self.worker.start()

    def _show_results(self, result):
        self.btn.setEnabled(True)
        self.progress.setVisible(False)

        pct = result['global_similarity']
        color = _pct_color(pct)
        self.global_label.setText(
            '<span style="color:{}">{:.1f}% similitud global</span>'.format(color, pct))

        u_a = len(result['unique_to_a'])
        u_b = len(result['unique_to_b'])
        total_a = len(result['chapter_map'])
        self.stats_label.setText(
            'Capítulos: {}  ·  Únicos en A: {}  ·  Únicos en B: {}  ·  Método: {}'.format(
                total_a, u_a, u_b, result['method']))

        sizes = []
        for bid, fmt in zip(self.book_ids[:2], self.book_formats):
            size = 0
            try:
                size = self.db.format_db_size(bid, fmt)
            except Exception:
                pass
            if not size:
                try:
                    path = self.db.format_abspath(bid, fmt)
                    if path and os.path.exists(path):
                        size = os.path.getsize(path)
                except Exception:
                    pass
            sizes.append(_human_size(size))
        self.file_info_label.setText(
            'Tamaño A ({}): {}  ·  Tamaño B ({}): {}'.format(
                self.book_formats[0], sizes[0],
                self.book_formats[1], sizes[1]))

        self.delete_a_btn.setEnabled(True)
        self.delete_b_btn.setEnabled(True)

        rows      = result['chapter_map']
        ignored_a = result.get('ignored_a', [])
        ignored_b = result.get('ignored_b', [])

        total_rows = len(rows) + len(ignored_a) + len(ignored_b)
        self.table.setRowCount(total_rows)

        for i, row in enumerate(rows):
            raw_a  = row['chapter_a']
            raw_b  = row['best_match_b']
            name_a = raw_a.split('/')[-1] if raw_a else '—'
            name_b = raw_b.split('/')[-1] if raw_b else '—'
            score  = row['similarity']

            item_a = QTableWidgetItem(name_a)
            item_b = QTableWidgetItem(name_b)
            item_s = QTableWidgetItem('{:.1f}%'.format(score))
            item_s.setTextAlignment(Qt.AlignCenter)

            bg = QColor(_pct_color(score))
            bg.setAlpha(60)
            for item in (item_a, item_b, item_s):
                item.setBackground(bg)
            if row.get('is_unique'):
                for item in (item_a, item_b, item_s):
                    font = item.font()
                    font.setItalic(True)
                    item.setFont(font)

            self.table.setItem(i, 0, item_a)
            self.table.setItem(i, 1, item_b)
            self.table.setItem(i, 2, item_s)

        ig_bg = QColor('#888888')
        ig_bg.setAlpha(30)
        base_row = len(rows)

        for j, ig in enumerate(ignored_a):
            name  = ig['name'].split('/')[-1]
            razón = 'Ignorado ({})'.format(ig['reason'])
            item_a = QTableWidgetItem(name)
            item_b = QTableWidgetItem('—')
            item_s = QTableWidgetItem(razón)
            item_s.setTextAlignment(Qt.AlignCenter)
            for item in (item_a, item_b, item_s):
                item.setBackground(ig_bg)
                font = item.font(); font.setItalic(True); item.setFont(font)
                item.setForeground(QColor('#888888'))
            self.table.setItem(base_row + j, 0, item_a)
            self.table.setItem(base_row + j, 1, item_b)
            self.table.setItem(base_row + j, 2, item_s)

        base_row += len(ignored_a)
        for j, ig in enumerate(ignored_b):
            name  = ig['name'].split('/')[-1]
            razón = 'Ignorado ({})'.format(ig['reason'])
            item_a = QTableWidgetItem('—')
            item_b = QTableWidgetItem(name)
            item_s = QTableWidgetItem(razón)
            item_s.setTextAlignment(Qt.AlignCenter)
            for item in (item_a, item_b, item_s):
                item.setBackground(ig_bg)
                font = item.font(); font.setItalic(True); item.setFont(font)
                item.setForeground(QColor('#888888'))
            self.table.setItem(base_row + j, 0, item_a)
            self.table.setItem(base_row + j, 1, item_b)
            self.table.setItem(base_row + j, 2, item_s)

        self.table.setVisible(True)
        self.resize(self.width(), min(640, 320 + total_rows * 26))

    def _show_error(self, msg):
        self.btn.setEnabled(True)
        self.progress.setVisible(False)
        error_dialog(self, 'Error en la comparación', msg, show=True)

    def _delete_book(self, index):
        """
        Delete one of the two books from the library.
        After deletion the dialog is closed (there is nothing left to compare).
        """
        book_id = self.book_ids[index]
        title = self.db.field_for('title', book_id)
        if not question_dialog(
            self,
            'Confirmar borrado',
            '<p>¿Eliminar <b>{}</b>?</p><p>Esta acción no se puede deshacer.</p>'.format(title),
        ):
            return
        try:
            # Prefer the legacy db object that exposes delete_book()
            db_del = getattr(self.current_db, 'db', self.current_db)
            if not hasattr(db_del, 'delete_book'):
                db_del = self.db
            db_del.delete_book(book_id)

            # Disable all interactive controls
            self.btn.setEnabled(False)
            self.delete_a_btn.setEnabled(False)
            self.delete_b_btn.setEnabled(False)

            # Refresh the library view
            try:
                model = self.gui.library_view.model()
                if hasattr(model, 'refresh'):
                    model.refresh()
                elif hasattr(model, 'beginResetModel'):
                    model.beginResetModel()
                    model.endResetModel()
            except Exception:
                pass

            error_dialog(self, 'Libro borrado',
                         'El libro "{}" ha sido borrado.'.format(title), show=True)
            self.accept()   # Close the dialog cleanly
        except Exception as e:
            error_dialog(self, 'Error al borrar libro', str(e), show=True)
