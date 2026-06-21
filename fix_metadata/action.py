from __future__ import unicode_literals, division, absolute_import, print_function

__license__   = 'GPL v3'
__copyright__ = '2026, Fix Metadata Plugin'

import logging

logger = logging.getLogger('FIX_METADATA_PLUGIN')

try:
    from PyQt5.Qt import (QMenu, QToolButton, QProgressDialog, Qt, QApplication,
                          QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                          QPushButton, QTableWidget, QTableWidgetItem,
                          QHeaderView, QAbstractItemView, QSize)
    from calibre.gui2 import error_dialog, info_dialog, Dispatcher
    from calibre.gui2.actions import InterfaceAction
    from calibre.gui2.dialogs.message_box import ErrorNotification
    from calibre_plugins.fix_metadata.jobs import start_extract_threaded, get_job_details
except Exception as e:
    logger.error(f"Error loading dependencies in action.py: {e}")

try:
    from calibre_plugins.fix_metadata import get_icons
except ImportError:
    get_icons = None

try:
    from calibre_plugins.fix_metadata.fix_title import (
        clean_title, find_series_in_title, find_language_in_title,
        find_subtitle_in_title, make_clean_title)
    from calibre_plugins.fix_metadata.fix_author import fix_author
    from calibre_plugins.fix_metadata.fix_identifiers import fix_identifiers
    from calibre_plugins.fix_metadata.fix_world import (
        load_world_map, world_for_series)
except Exception as e:
    logger.error(f"Error importing fix modules: {e}")

PLUGIN_ICONS = ['images/icon.png']


class SeriesReviewDialog(QDialog):
    """
    Review proposed SERIES changes (series + index + language; no subtitle).

    Columns: [check] Original Title | New Title | Series | # | Old Series | Old #
    Tuple:   (book_id, orig, clean, series, index, old_series, old_index, save_opf, lang)
    """
    COL_ORIG = 0
    COL_CLEAN = 1
    COL_SERIES = 2
    COL_INDEX = 3
    COL_OLD_SERIES = 4
    COL_OLD_INDEX = 5

    def __init__(self, parent, changes):
        super().__init__(parent)
        self.changes = changes
        self.setWindowTitle('Fix Series - Review Changes')
        self.setWindowModality(Qt.WindowModal)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        lbl = QLabel(
            f'<b>{len(self.changes)}</b> title(s) with a detected series.<br>'
            'Check the rows you want to apply, then click <b>Apply</b>.')
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        self.table = QTableWidget(len(self.changes), 6, self)
        self.table.setHorizontalHeaderLabels(
            ['Original Title', 'New Title', 'Series', '#', 'Old Series', 'Old #'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)

        self.table.blockSignals(True)
        for row, (book_id, orig, clean, series, index,
                  old_series, old_index, _save_opf, _lang) in enumerate(self.changes):
            item = QTableWidgetItem(orig)
            item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled
                          | Qt.ItemIsSelectable)
            item.setCheckState(Qt.Checked)
            item.setData(Qt.UserRole, book_id)
            self.table.setItem(row, self.COL_ORIG, item)
            self.table.setItem(row, self.COL_CLEAN, QTableWidgetItem(clean))
            self.table.setItem(row, self.COL_SERIES, QTableWidgetItem(series or ''))
            if index is not None:
                idx_str = str(int(index)) if index == int(index) else str(index)
            else:
                idx_str = ''
            idx_item = QTableWidgetItem(idx_str)
            idx_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, self.COL_INDEX, idx_item)
            self.table.setItem(row, self.COL_OLD_SERIES, QTableWidgetItem(old_series or ''))
            if old_index is not None:
                old_idx_str = str(int(old_index)) if old_index == int(old_index) else str(old_index)
            else:
                old_idx_str = ''
            old_idx_item = QTableWidgetItem(old_idx_str)
            old_idx_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, self.COL_OLD_INDEX, old_idx_item)
        self.table.blockSignals(False)
        self.table.resizeColumnsToContents()
        self.table.setSortingEnabled(True)
        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table)

        btn_bar = QHBoxLayout()
        b1 = QPushButton('Select All')
        b1.clicked.connect(self._select_all)
        btn_bar.addWidget(b1)
        b2 = QPushButton('Deselect All')
        b2.clicked.connect(self._deselect_all)
        btn_bar.addWidget(b2)
        btn_bar.addStretch()
        self.apply_btn = QPushButton()
        self.apply_btn.setDefault(True)
        self.apply_btn.clicked.connect(self.accept)
        btn_bar.addWidget(self.apply_btn)
        cancel_btn = QPushButton('Cancel')
        cancel_btn.clicked.connect(self.reject)
        btn_bar.addWidget(cancel_btn)
        layout.addLayout(btn_bar)
        self._refresh_apply_label()
        self.resize(QSize(950, 520))

    def _on_item_changed(self, item):
        if item.column() == self.COL_ORIG:
            self._refresh_apply_label()

    def _refresh_apply_label(self):
        n = self._count_checked()
        self.apply_btn.setText(f'Apply ({n})')
        self.apply_btn.setEnabled(n > 0)

    def _count_checked(self):
        return sum(1 for row in range(self.table.rowCount())
                   if self.table.item(row, self.COL_ORIG).checkState() == Qt.Checked)

    def _set_all(self, state):
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            self.table.item(row, self.COL_ORIG).setCheckState(state)
        self.table.blockSignals(False)
        self._refresh_apply_label()

    def _select_all(self):
        self._set_all(Qt.Checked)

    def _deselect_all(self):
        self._set_all(Qt.Unchecked)

    def get_selected_changes(self):
        result = []
        for row in range(self.table.rowCount()):
            if self.table.item(row, self.COL_ORIG).checkState() == Qt.Checked:
                book_id = self.table.item(row, self.COL_ORIG).data(Qt.UserRole)
                for change in self.changes:
                    if change[0] == book_id:
                        result.append(change)
                        break
        return result


class SubtitleReviewDialog(QDialog):
    """
    Review proposed SUBTITLE extraction ("Main: Subtitle" -> #subtitle).

    Columns: [check] Original Title | New Title | Subtitle
    Tuple:   (book_id, orig, clean, subtitle, save_opf)
    """
    COL_ORIG = 0
    COL_CLEAN = 1
    COL_SUBTITLE = 2

    def __init__(self, parent, changes):
        super().__init__(parent)
        self.changes = changes
        self.setWindowTitle('Fix Subtitle - Review Changes')
        self.setWindowModality(Qt.WindowModal)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        lbl = QLabel(
            f'<b>{len(self.changes)}</b> title(s) with a "Main: Subtitle" split.<br>'
            'The subtitle moves to #subtitle and the title keeps only the main part.<br>'
            'Check the rows you want to apply, then click <b>Apply</b>.')
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        self.table = QTableWidget(len(self.changes), 3, self)
        self.table.setHorizontalHeaderLabels(['Original Title', 'New Title', 'Subtitle'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)

        self.table.blockSignals(True)
        for row, (book_id, orig, clean, subtitle, _save_opf) in enumerate(self.changes):
            item = QTableWidgetItem(orig)
            item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled
                          | Qt.ItemIsSelectable)
            item.setCheckState(Qt.Checked)
            item.setData(Qt.UserRole, book_id)
            self.table.setItem(row, self.COL_ORIG, item)
            self.table.setItem(row, self.COL_CLEAN, QTableWidgetItem(clean))
            self.table.setItem(row, self.COL_SUBTITLE, QTableWidgetItem(subtitle or ''))
        self.table.blockSignals(False)
        self.table.resizeColumnsToContents()
        self.table.setSortingEnabled(True)
        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table)

        btn_bar = QHBoxLayout()
        b1 = QPushButton('Select All')
        b1.clicked.connect(self._select_all)
        btn_bar.addWidget(b1)
        b2 = QPushButton('Deselect All')
        b2.clicked.connect(self._deselect_all)
        btn_bar.addWidget(b2)
        btn_bar.addStretch()
        self.apply_btn = QPushButton()
        self.apply_btn.setDefault(True)
        self.apply_btn.clicked.connect(self.accept)
        btn_bar.addWidget(self.apply_btn)
        cancel_btn = QPushButton('Cancel')
        cancel_btn.clicked.connect(self.reject)
        btn_bar.addWidget(cancel_btn)
        layout.addLayout(btn_bar)
        self._refresh_apply_label()
        self.resize(QSize(900, 500))

    def _on_item_changed(self, item):
        if item.column() == self.COL_ORIG:
            self._refresh_apply_label()

    def _refresh_apply_label(self):
        n = self._count_checked()
        self.apply_btn.setText(f'Apply ({n})')
        self.apply_btn.setEnabled(n > 0)

    def _count_checked(self):
        return sum(1 for row in range(self.table.rowCount())
                   if self.table.item(row, self.COL_ORIG).checkState() == Qt.Checked)

    def _set_all(self, state):
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            self.table.item(row, self.COL_ORIG).setCheckState(state)
        self.table.blockSignals(False)
        self._refresh_apply_label()

    def _select_all(self):
        self._set_all(Qt.Checked)

    def _deselect_all(self):
        self._set_all(Qt.Unchecked)

    def get_selected_changes(self):
        result = []
        for row in range(self.table.rowCount()):
            if self.table.item(row, self.COL_ORIG).checkState() == Qt.Checked:
                book_id = self.table.item(row, self.COL_ORIG).data(Qt.UserRole)
                for change in self.changes:
                    if change[0] == book_id:
                        result.append(change)
                        break
        return result


class WorldReviewDialog(QDialog):
    """Review which #world values to write (one row per proposed change)."""

    COL_TITLE  = 0
    COL_SERIES = 1
    COL_WORLD  = 2

    def __init__(self, parent, changes):
        super().__init__(parent)
        self.changes = changes   # [(book_id, title, series, world)]
        self.setWindowTitle('Fix Universe – Review Changes')
        self.setWindowModality(Qt.WindowModal)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        lbl = QLabel(
            f'<b>{len(self.changes)}</b> book(s) will receive a #world value.<br>'
            'Check the rows you want to apply, then click <b>Apply</b>.')
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        self.table = QTableWidget(len(self.changes), 3, self)
        self.table.setHorizontalHeaderLabels(['Title', 'Series', '#world'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)

        self.table.blockSignals(True)
        for row, (book_id, title, series, world) in enumerate(self.changes):
            item = QTableWidgetItem(title)
            item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled
                          | Qt.ItemIsSelectable)
            item.setCheckState(Qt.Checked)
            item.setData(Qt.UserRole, book_id)
            self.table.setItem(row, self.COL_TITLE, item)
            self.table.setItem(row, self.COL_SERIES, QTableWidgetItem(series or ''))
            self.table.setItem(row, self.COL_WORLD, QTableWidgetItem(world or ''))
        self.table.blockSignals(False)
        self.table.resizeColumnsToContents()
        self.table.setSortingEnabled(True)
        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table)

        bar = QHBoxLayout()
        b1 = QPushButton('Select All')
        b1.clicked.connect(lambda: self._set_all(Qt.Checked))
        bar.addWidget(b1)
        b2 = QPushButton('Deselect All')
        b2.clicked.connect(lambda: self._set_all(Qt.Unchecked))
        bar.addWidget(b2)
        bar.addStretch()
        self.apply_btn = QPushButton()
        self.apply_btn.setDefault(True)
        self.apply_btn.clicked.connect(self.accept)
        bar.addWidget(self.apply_btn)
        cancel = QPushButton('Cancel')
        cancel.clicked.connect(self.reject)
        bar.addWidget(cancel)
        layout.addLayout(bar)

        self._refresh()
        self.resize(QSize(820, 480))

    def _on_item_changed(self, item):
        if item.column() == self.COL_TITLE:
            self._refresh()

    def _count(self):
        return sum(1 for r in range(self.table.rowCount())
                   if self.table.item(r, self.COL_TITLE).checkState() == Qt.Checked)

    def _set_all(self, state):
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            self.table.item(r, self.COL_TITLE).setCheckState(state)
        self.table.blockSignals(False)
        self._refresh()

    def _refresh(self):
        n = self._count()
        self.apply_btn.setText(f'Apply ({n})')
        self.apply_btn.setEnabled(n > 0)

    def get_selected_changes(self):
        result = []
        for r in range(self.table.rowCount()):
            if self.table.item(r, self.COL_TITLE).checkState() == Qt.Checked:
                book_id = self.table.item(r, self.COL_TITLE).data(Qt.UserRole)
                for ch in self.changes:
                    if ch[0] == book_id:
                        result.append(ch)
                        break
        return result


class FixMetadataAction(InterfaceAction):

    name        = 'Fix Metadata'
    action_spec = ('Fix Metadata', None, 'Fix and extract metadata from books', None)
    popup_type  = QToolButton.InstantPopup
    action_type = 'current'

    # ------------------------------------------------------------------ #
    #  Initialisation                                                      #
    # ------------------------------------------------------------------ #

    def genesis(self):
        logger.info("Initialising plugin: Fix Metadata")

        if get_icons:
            try:
                self.qaction.setIcon(get_icons('images/icon.png'))
            except Exception as e:
                logger.warning(f"Could not load icon: {e}")

        self.menu = QMenu(self.gui)
        self.qaction.setMenu(self.menu)

        # ---- Extract metadata submenu ----
        extract_menu = self.menu.addMenu('Extract metadata from file')
        ac = extract_menu.addAction('Selected books')
        ac.setToolTip('Extract generator, producer, title and subjects from the '
                      'selected books (EPUB/AZW3) into custom columns')
        ac.triggered.connect(lambda: self.extract_metadatas(scope='selected'))

        ac = extract_menu.addAction('Entire library')
        ac.setToolTip('Extract metadata from every book in the library')
        ac.triggered.connect(lambda: self.extract_metadatas(scope='all'))

        self.menu.addSeparator()

        # ---- Fix series submenu ----
        series_menu = self.menu.addMenu('Fix series  (from title)')
        ac = series_menu.addAction('Selected books')
        ac.setToolTip('Detect series + index (and language) embedded in titles '
                      'and review changes before saving')
        ac.triggered.connect(lambda: self.fix_series_action(scope='selected'))
        ac = series_menu.addAction('Entire library')
        ac.setToolTip('Detect series in every book title in the library')
        ac.triggered.connect(lambda: self.fix_series_action(scope='all'))

        # ---- Fix subtitle submenu ----
        subtitle_menu = self.menu.addMenu('Fix subtitle  (Title: Subtitle -> #subtitle)')
        ac = subtitle_menu.addAction('Selected books')
        ac.setToolTip('Move "Main: Subtitle" into the #subtitle column and trim the title')
        ac.triggered.connect(lambda: self.fix_subtitle_action(scope='selected'))
        ac = subtitle_menu.addAction('Entire library')
        ac.setToolTip('Extract subtitles for every book in the library')
        ac.triggered.connect(lambda: self.fix_subtitle_action(scope='all'))

        # ---- Fix author submenu ----
        author_menu = self.menu.addMenu('Fix author  (Last, First → First Last + initials)')
        ac = author_menu.addAction('Selected books')
        ac.setToolTip('Reverse "Apellido, Nombre" order and fix missing dots/spaces '
                      'in initials for the selected books')
        ac.triggered.connect(lambda: self.fix_authors(scope='selected'))

        ac = author_menu.addAction('Entire library')
        ac.setToolTip('Fix author names for every book in the library')
        ac.triggered.connect(lambda: self.fix_authors(scope='all'))

        # ---- Fix identifiers submenu ----
        ids_menu = self.menu.addMenu('Fix identifiers  (amazon, isbn, UUIDs)')
        ac = ids_menu.addAction('Selected books')
        ac.setToolTip('Normalise identifiers: merge asin/mobi-asin into amazon, '
                      'remove UUIDs, fix key==value entries, merge regional amazon codes')
        ac.triggered.connect(lambda: self.fix_identifiers_action(scope='selected'))

        ac = ids_menu.addAction('Entire library')
        ac.setToolTip('Normalise identifiers for every book in the library')
        ac.triggered.connect(lambda: self.fix_identifiers_action(scope='all'))

        # ---- Fix universe submenu ----
        world_menu = self.menu.addMenu('Fix universe  (#world from series)')
        ac = world_menu.addAction('Selected books')
        ac.setToolTip('Fill #world from the book series using the curated '
                      'series->universe map (only when #world is empty)')
        ac.triggered.connect(lambda: self.fix_world_action(scope='selected'))
        ac = world_menu.addAction('Entire library')
        ac.setToolTip('Fill #world from series for every book in the library')
        ac.triggered.connect(lambda: self.fix_world_action(scope='all'))

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _get_book_ids(self, scope):
        """Return the list of book IDs to process for the given scope."""
        if scope == 'all':
            db = self.gui.current_db
            return db.all_ids()
        else:
            rows = self.gui.library_view.selectionModel().selectedRows()
            if not rows:
                error_dialog(self.gui, 'No selection',
                             'Select one or more books first.', show=True)
                return None
            return self.gui.library_view.get_selected_ids()

    def _check_custom_fields(self, db):
        missing = [f'#{lbl}' for lbl in ('generator', 'book_producer', 'title_opf', 'subjects')
                   if f'#{lbl}' not in db.custom_field_keys()]
        if missing:
            error_dialog(self.gui, 'Missing custom columns',
                         f"These custom columns are missing: {', '.join(missing)}\n\n"
                         "Please create them before using this action.",
                         show=True)
            return False
        return True

    # ------------------------------------------------------------------ #
    #  Action: Extract metadata                                            #
    # ------------------------------------------------------------------ #

    def extract_metadatas(self, scope='selected'):
        logger.info(f"Action triggered: Extract metadata ({scope})")

        book_ids = self._get_book_ids(scope)
        if book_ids is None:
            return

        db = self.gui.library_view.model().db
        if not self._check_custom_fields(db):
            return

        logger.info(f"Extracting metadata for {len(book_ids)} book(s)")
        start_extract_threaded(self.gui, book_ids, Dispatcher(self._extraction_complete))

    def _extraction_complete(self, job):
        if job.failed:
            self.gui.job_exception(job, dialog_title='Extraction batch error')
            return

        extracted_ids, failed_ids, no_metadata_ids, det_msg = get_job_details(job)
        db = self.gui.current_db
        has_subtitle = '#subtitle' in db.custom_field_keys()

        for book_id, title, generator, book_producer, title_opf, subjects, subtitle \
                in extracted_ids:
            try:
                if generator:
                    db.set_custom(book_id, generator,     label='generator',     commit=False)
                if book_producer:
                    db.set_custom(book_id, book_producer, label='book_producer', commit=False)
                if title_opf:
                    db.set_custom(book_id, title_opf,     label='title_opf',     commit=False)
                if subtitle and has_subtitle:
                    db.set_custom(book_id, subtitle,      label='subtitle',      commit=False)
                if subjects:
                    val = ', '.join(subjects) if isinstance(subjects, list) else subjects
                    db.set_custom(book_id, val,            label='subjects',      commit=False)
                db.commit_dirty_cache()
            except Exception as e:
                logger.error(f"Error updating fields for book {book_id}: {e}")
                error_dialog(self.gui, 'Error updating fields',
                             f'Failed to update custom fields for "{title}": {e}',
                             show=True)

        all_ids = [item[0] for item in extracted_ids + failed_ids + no_metadata_ids]
        if all_ids:
            self.gui.library_view.model().refresh_ids(all_ids)

        self.gui.status_bar.show_message(
            f'Extraction done: {len(extracted_ids)} updated', 3000)

        if failed_ids:
            self._show_extraction_results(extracted_ids, failed_ids, no_metadata_ids, det_msg)

    def _show_extraction_results(self, extracted_ids, failed_ids, no_metadata_ids, det_msg):
        msg  = 'Metadata Extraction Results\n' + '=' * 40 + '\n\n'
        msg += f'Successfully extracted: {len(extracted_ids)}\n'
        if no_metadata_ids:
            msg += f'No metadata found: {len(no_metadata_ids)}\n'
        if failed_ids:
            msg += f'Failed: {len(failed_ids)}\n'
        msg += f'\nProcessed {len(extracted_ids)+len(no_metadata_ids)+len(failed_ids)} books'

        if failed_ids or no_metadata_ids:
            ErrorNotification(det_msg, 'Extraction Details', 'Extraction complete', msg,
                              det_msg=det_msg, show_copy_button=True,
                              parent=self.gui).show()
        else:
            info_dialog(self.gui, 'Extraction Complete', msg, show=True)

    # ------------------------------------------------------------------ #
    #  Action: Clean titles                                                #
    # ------------------------------------------------------------------ #

    def clean_titles(self, scope='selected'):
        logger.info(f"Action triggered: Clean titles ({scope})")

        book_ids = self._get_book_ids(scope)
        if book_ids is None:
            return

        db      = self.gui.current_db
        changed = []
        unchanged_count = 0

        for book_id in book_ids:
            mi           = db.get_metadata(book_id, index_is_id=True)
            title        = mi.title or ''
            series       = getattr(mi, 'series',       None)
            series_index = getattr(mi, 'series_index', None)
            language     = getattr(mi, 'language',     None)

            new_title = clean_title(title,
                                    series=series,
                                    series_index=series_index,
                                    language=language)
            if new_title != title:
                mi.title = new_title
                db.set_metadata(book_id, mi, commit=False)
                changed.append((title, new_title))
            else:
                unchanged_count += 1

        db.commit()

        if changed:
            self.gui.library_view.model().refresh_ids(book_ids)
            self.gui.status_bar.show_message(
                f'Titles cleaned: {len(changed)} modified', 3000)

        details = ''
        if changed:
            details += 'Titles modified:\n'
            for old, new in changed:
                details += f'  "{old}"\n  \u2192 "{new}"\n\n'
        if unchanged_count:
            details += f'{unchanged_count} title(s) did not match the pattern and were left unchanged.\n'

        info_dialog(self.gui, 'Fix Titles',
                    f'{len(changed)} title(s) updated, {unchanged_count} unchanged.',
                    det_msg=details, show=True)

    # ------------------------------------------------------------------ #
    #  Action: Fix author names                                            #
    # ------------------------------------------------------------------ #

    def fix_authors(self, scope='selected'):
        logger.info(f"Action triggered: Fix author names ({scope})")

        book_ids = self._get_book_ids(scope)
        if book_ids is None:
            return

        db              = self.gui.current_db
        changed_books   = 0
        changed_authors = []
        unchanged_books = 0

        for book_id in book_ids:
            mi          = db.get_metadata(book_id, index_is_id=True)
            old_authors = list(mi.authors or [])
            new_authors = [fix_author(a) for a in old_authors]

            if new_authors != old_authors:
                mi.authors = new_authors
                db.set_metadata(book_id, mi, commit=False)
                changed_books += 1
                for old, new in zip(old_authors, new_authors):
                    if old != new:
                        changed_authors.append((old, new))
            else:
                unchanged_books += 1

        db.commit()

        if changed_books:
            self.gui.library_view.model().refresh_ids(book_ids)
            self.gui.status_bar.show_message(
                f'Authors fixed: {changed_books} book(s) updated', 3000)

        details = ''
        if changed_authors:
            details += 'Authors modified:\n'
            for old, new in changed_authors:
                details += f'  "{old}"\n  \u2192 "{new}"\n\n'
        if unchanged_books:
            details += f'{unchanged_books} book(s) had no author changes.\n'

        info_dialog(self.gui, 'Fix Author Names',
                    f'{changed_books} book(s) updated, {unchanged_books} unchanged.',
                    det_msg=details, show=True)

    # ------------------------------------------------------------------ #
    #  Action: Fix identifiers                                             #
    # ------------------------------------------------------------------ #

    def fix_identifiers_action(self, scope='selected'):
        logger.info(f"Action triggered: Fix identifiers ({scope})")

        book_ids = self._get_book_ids(scope)
        if book_ids is None:
            return

        new_api = self.gui.current_db.new_api
        total   = len(book_ids)

        # ── Progress dialog ──────────────────────────────────────────────
        progress = QProgressDialog(self.gui)
        progress.setWindowTitle('Fix Identifiers')
        progress.setCancelButtonText('Cancel')
        progress.setRange(0, total)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)

        # ── Phase 1: one bulk read – all identifiers in a single DB query ─
        progress.setLabelText(f'Loading identifiers for {total} books…')
        progress.setValue(0)
        QApplication.processEvents()

        all_identifiers = new_api.all_field_for('identifiers', book_ids)

        if progress.wasCanceled():
            return

        # ── Phase 2: pure in-memory analysis (no I/O) ───────────────────
        updates     = {}   # {book_id: new_ids_dict}
        all_changes = []   # [(book_id, [change_str, …])]
        BATCH       = 1000 # update the progress bar every N books

        progress.setLabelText(f'Analysing {total} books…')
        QApplication.processEvents()

        for i, book_id in enumerate(book_ids):
            if progress.wasCanceled():
                break

            orig    = dict(all_identifiers.get(book_id) or {})
            new_ids, changes = fix_identifiers(orig)

            if changes:
                updates[book_id] = new_ids
                all_changes.append((book_id, changes))

            if i % BATCH == 0:
                progress.setLabelText(
                    f'Analysing [{i + 1} / {total}]…  '
                    f'({len(updates)} to update so far)')
                progress.setValue(i)
                QApplication.processEvents()

        if progress.wasCanceled() or not updates:
            progress.close()
        else:
            # ── Phase 3: one bulk write – all changes in a single transaction
            changed_books   = len(updates)
            unchanged_books = total - changed_books

            progress.setLabelText(f'Saving {changed_books} changes…')
            progress.setValue(total - 1)
            QApplication.processEvents()

            # new_api.set_field fully replaces identifiers for each book
            # (no need to delete keys manually)
            new_api.set_field('identifiers', updates)

            progress.setValue(total)
            progress.close()

            self.gui.library_view.model().refresh_ids(list(updates.keys()))
            self.gui.status_bar.show_message(
                f'Identifiers fixed: {changed_books} book(s) updated', 3000)

            # Fetch titles only for books that changed (one extra bulk read)
            titles  = new_api.all_field_for('title',
                                            [bid for bid, _ in all_changes])
            details = ''
            for book_id, changes in all_changes:
                title = titles.get(book_id) or f'Book {book_id}'
                details += f'"{title}":\n'
                for c in changes:
                    details += f'  • {c}\n'
                details += '\n'
            if unchanged_books:
                details += f'{unchanged_books} book(s) needed no changes.\n'

            info_dialog(self.gui, 'Fix Identifiers',
                        f'{changed_books} book(s) updated, {unchanged_books} unchanged.',
                        det_msg=details, show=True)

    # ------------------------------------------------------------------ #
    #  Action: Extract series from title                                   #
    # ------------------------------------------------------------------ #

    def fix_world_action(self, scope='selected'):
        """Fill #world from the book series using the curated map.

        Only books whose series is in the map AND whose #world is currently
        empty are proposed; nothing is ever overwritten.
        """
        logger.info(f"Action triggered: Fix universe ({scope})")

        book_ids = self._get_book_ids(scope)
        if book_ids is None:
            return

        db = self.gui.current_db
        if '#world' not in db.custom_field_keys():
            error_dialog(self.gui, 'Missing custom column',
                         "The custom column #world does not exist.\n\n"
                         "Create a Text column with lookup name 'world' first.",
                         show=True)
            return

        rev = load_world_map()
        if not rev:
            error_dialog(self.gui, 'Empty universe map',
                         "world_map.json was not found or is empty.",
                         show=True)
            return

        pending = []   # (book_id, title, series, world)
        for book_id in book_ids:
            mi = db.get_metadata(book_id, index_is_id=True,
                                 get_user_categories=False)
            series = getattr(mi, 'series', None)
            if not series:
                continue
            world = world_for_series(series, rev)
            if not world:
                continue
            existing = db.get_custom(book_id, label='world', index_is_id=True) or ''
            if str(existing).strip():
                continue   # never overwrite an existing #world
            pending.append((book_id, mi.title or '', series, world))

        if not pending:
            info_dialog(self.gui, 'Fix Universe',
                        'No books needed a #world value '
                        '(none matched the map, or #world already set).',
                        show=True)
            return

        dlg = WorldReviewDialog(self.gui, pending)
        if dlg.exec_() != QDialog.Accepted:
            return
        confirmed = dlg.get_selected_changes()
        if not confirmed:
            return

        for book_id, title, series, world in confirmed:
            db.set_custom(book_id, world, label='world', commit=False)
        db.commit()

        updated = [c[0] for c in confirmed]
        self.gui.library_view.model().refresh_ids(updated)
        self.gui.status_bar.show_message(
            f'#world set on {len(updated)} book(s)', 3000)

        details = ''
        for book_id, title, series, world in confirmed:
            details += f'"{title}"  →  #world: {world}  (series: {series})\n'
        info_dialog(self.gui, 'Fix Universe',
                    f'{len(updated)} book(s) updated.',
                    det_msg=details, show=True)

    def fix_series_action(self, scope='selected'):
        """Detect series + index (+ language) embedded in titles and review."""
        logger.info(f"Action triggered: Fix series ({scope})")

        book_ids = self._get_book_ids(scope)
        if book_ids is None:
            return

        db = self.gui.current_db
        total = len(book_ids)
        has_title_opf = '#title_opf' in db.custom_field_keys()

        progress = QProgressDialog(self.gui)
        progress.setWindowTitle('Fix Series')
        progress.setCancelButtonText('Cancel')
        progress.setRange(0, total)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)

        pending = []   # (book_id, orig, clean, series, index, old_series, old_index, save_opf, lang)
        BATCH = 50
        progress.setLabelText(f'Scanning {total} books...')
        progress.setValue(0)
        QApplication.processEvents()

        for i, book_id in enumerate(book_ids):
            if progress.wasCanceled():
                break
            mi = db.get_metadata(book_id, index_is_id=True, get_user_categories=False)
            orig_title = mi.title or ''
            book_author = (mi.authors[0] if mi.authors else '') or None
            book_asort = (mi.author_sort or '') or None

            found_lang = find_language_in_title(orig_title)
            anchor_lang = (mi.language or found_lang or '').lower().strip() or None
            found_series, found_index, _sub = find_series_in_title(
                orig_title, language=anchor_lang,
                author=book_author, author_sort=book_asort)

            # Clean title (series + language + author hygiene). Subtitle is handled
            # by the separate "Fix subtitle" pass, so subtitle is NOT touched here.
            clean = make_clean_title(
                orig_title, series=found_series, index=found_index,
                language=found_lang, author=book_author, author_sort=book_asort,
                subtitle=None)

            series_to_write = found_series if (found_series and not mi.series) else None
            index_to_write = found_index if (found_index is not None and not mi.series) else None
            lang_to_write = found_lang if (found_lang and not mi.language) else None
            title_changed = clean.strip() != orig_title.strip()

            if title_changed or series_to_write or index_to_write or lang_to_write:
                old_series = mi.series or ''
                old_index = mi.series_index if mi.series else None
                save_opf = False
                if has_title_opf:
                    opf_val = (db.get_custom(book_id, label='title_opf', index_is_id=True) or '')
                    save_opf = not str(opf_val).strip()
                pending.append((book_id, orig_title, clean, series_to_write,
                                index_to_write, old_series, old_index, save_opf, lang_to_write))

            if i % BATCH == 0:
                progress.setLabelText(f'Scanning [{i + 1} / {total}]...  ({len(pending)} found)')
                progress.setValue(i)
                QApplication.processEvents()

        progress.setValue(total)
        progress.close()

        if not pending:
            info_dialog(self.gui, 'Fix Series',
                        'No titles matched a known series pattern.', show=True)
            return

        dlg = SeriesReviewDialog(self.gui, pending)
        if dlg.exec_() != QDialog.Accepted:
            return
        confirmed = dlg.get_selected_changes()

        # Mark the rejected (unchecked) books with a temporary Calibre marker so
        # the user can review them manually later (search: marks:revisar_serie).
        confirmed_ids = {c[0] for c in confirmed}
        rejected_ids = [t[0] for t in pending if t[0] not in confirmed_ids]
        if rejected_ids:
            try:
                marked = dict(getattr(db.data, 'marked_ids', {}) or {})
            except Exception:
                marked = {}
            for bid in rejected_ids:
                marked[bid] = 'revisar_serie'
            try:
                db.set_marked_ids(marked)
                self.gui.library_view.model().refresh_ids(list(rejected_ids))
                logger.info(
                    f"Marked {len(rejected_ids)} rejected book(s) as 'revisar_serie'")
            except Exception as e:
                logger.error(f'Could not set marked ids: {e}')

        if not confirmed:
            if rejected_ids:
                info_dialog(self.gui, 'Fix Series',
                            f'No changes applied. {len(rejected_ids)} book(s) marked '
                            f'for review (search: marks:revisar_serie).', show=True)
            return

        updated_ids = []
        for book_id, orig_title, clean, series, index, old_series, old_index, save_opf, lang in confirmed:
            mi = db.get_metadata(book_id, index_is_id=True)
            mi.title = clean
            if series is not None:
                mi.series = series
                mi.series_index = index
            elif index is not None:
                mi.series_index = index
            if lang is not None:
                mi.language = lang
            db.set_metadata(book_id, mi, commit=False)
            if save_opf and has_title_opf:
                db.set_custom(book_id, orig_title, label='title_opf', commit=False)
            updated_ids.append(book_id)
        db.commit()

        self.gui.library_view.model().refresh_ids(updated_ids)
        self.gui.status_bar.show_message(
            f'Series fixed: {len(updated_ids)} book(s) updated', 3000)

        details = ''
        for book_id, orig, clean, series, index, old_series, old_index, save_opf, lang in confirmed:
            details += f'"{orig}"\n  -> Title:  {clean}\n'
            if series is not None:
                idx_str = int(index) if index == int(index) else index
                details += f'  -> Series: {series} #{idx_str}'
                if old_series and old_series != series:
                    details += f'  (was: {old_series})'
                details += '\n'
            elif index is not None:
                idx_str = int(index) if index == int(index) else index
                details += f'  -> Series index: #{idx_str}  (no series name)\n'
            if lang is not None:
                details += f'  -> Language: {lang}\n'
            if save_opf:
                details += '  -> #title_opf saved\n'
            details += '\n'
        msg = f'{len(updated_ids)} book(s) updated.'
        if rejected_ids:
            msg += (f'\n{len(rejected_ids)} book(s) marked for review '
                    f'(search: marks:revisar_serie).')
        info_dialog(self.gui, 'Fix Series',
                    msg, det_msg=details, show=True)

    def fix_subtitle_action(self, scope='selected'):
        """Move a "Main: Subtitle" split into #subtitle, trimming the title."""
        logger.info(f"Action triggered: Fix subtitle ({scope})")

        book_ids = self._get_book_ids(scope)
        if book_ids is None:
            return

        db = self.gui.current_db
        if '#subtitle' not in db.custom_field_keys():
            error_dialog(self.gui, 'Missing custom column',
                         "The custom column #subtitle does not exist.\n\n"
                         "Create a Text column with lookup name 'subtitle' first.",
                         show=True)
            return

        total = len(book_ids)
        has_title_opf = '#title_opf' in db.custom_field_keys()

        progress = QProgressDialog(self.gui)
        progress.setWindowTitle('Fix Subtitle')
        progress.setCancelButtonText('Cancel')
        progress.setRange(0, total)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)

        pending = []   # (book_id, orig, clean, subtitle, save_opf)
        BATCH = 50
        progress.setLabelText(f'Scanning {total} books...')
        progress.setValue(0)
        QApplication.processEvents()

        for i, book_id in enumerate(book_ids):
            if progress.wasCanceled():
                break
            mi = db.get_metadata(book_id, index_is_id=True, get_user_categories=False)
            orig_title = mi.title or ''
            sub = find_subtitle_in_title(orig_title)
            if sub:
                # Defer to the "Fix series" pass: if the colon belongs to a
                # series pattern, do not treat the tail as a subtitle.
                _au = (mi.authors[0] if mi.authors else None)
                _fs, _fi, _fsub = find_series_in_title(
                    orig_title, author=_au, author_sort=(mi.author_sort or None))
                if _fs:
                    sub = None
            if sub:
                existing = (db.get_custom(book_id, label='subtitle', index_is_id=True) or '')
                if not str(existing).strip():
                    main = orig_title.partition(': ')[0].strip()
                    if main and main != orig_title.strip():
                        save_opf = False
                        if has_title_opf:
                            opf_val = (db.get_custom(book_id, label='title_opf', index_is_id=True) or '')
                            save_opf = not str(opf_val).strip()
                        pending.append((book_id, orig_title, main, sub, save_opf))

            if i % BATCH == 0:
                progress.setLabelText(f'Scanning [{i + 1} / {total}]...  ({len(pending)} found)')
                progress.setValue(i)
                QApplication.processEvents()

        progress.setValue(total)
        progress.close()

        if not pending:
            info_dialog(self.gui, 'Fix Subtitle',
                        'No "Main: Subtitle" titles found (or #subtitle already set).',
                        show=True)
            return

        dlg = SubtitleReviewDialog(self.gui, pending)
        if dlg.exec_() != QDialog.Accepted:
            return
        confirmed = dlg.get_selected_changes()
        if not confirmed:
            return

        updated_ids = []
        for book_id, orig_title, clean, subtitle, save_opf in confirmed:
            mi = db.get_metadata(book_id, index_is_id=True)
            mi.title = clean
            db.set_metadata(book_id, mi, commit=False)
            db.set_custom(book_id, subtitle, label='subtitle', commit=False)
            if save_opf and has_title_opf:
                db.set_custom(book_id, orig_title, label='title_opf', commit=False)
            updated_ids.append(book_id)
        db.commit()

        self.gui.library_view.model().refresh_ids(updated_ids)
        self.gui.status_bar.show_message(
            f'Subtitle fixed: {len(updated_ids)} book(s) updated', 3000)

        details = ''
        for book_id, orig, clean, subtitle, save_opf in confirmed:
            details += f'"{orig}"\n  -> Title:    {clean}\n  -> Subtitle: {subtitle}\n'
            if save_opf:
                details += '  -> #title_opf saved\n'
            details += '\n'
        info_dialog(self.gui, 'Fix Subtitle',
                    f'{len(updated_ids)} book(s) updated.', det_msg=details, show=True)
