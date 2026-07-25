from __future__ import unicode_literals, division, absolute_import, print_function

__license__   = 'GPL v3'
__copyright__ = '2026, Fix Metadata Plugin'

import logging
import re

logger = logging.getLogger('FIX_METADATA_PLUGIN')

try:
    from PyQt5.Qt import (QMenu, QToolButton, QProgressDialog, Qt, QApplication,
                          QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                          QPushButton, QTableWidget, QTableWidgetItem,
                          QHeaderView, QAbstractItemView, QSize)
    from calibre.gui2 import error_dialog, info_dialog, warning_dialog, Dispatcher
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
        find_subtitle_in_title, make_clean_title, strip_known_author_suffix,
        find_generic_series_in_title, strip_generic_series_paren,
        find_dash_genre_subtitle_in_title, find_paren_genre_subtitle_in_title,
        whole_title_is_genre_blurb)
    from calibre_plugins.fix_metadata.fix_author import fix_author
    from calibre_plugins.fix_metadata.fix_identifiers import fix_identifiers
    from calibre_plugins.fix_metadata.fix_world import (
        load_world_map, world_for_series)
    from calibre_plugins.fix_metadata.fix_comments import (
        analyze_comment, ISSUE_LABELS)
    from calibre_plugins.fix_metadata.fix_tags import (
        load_tags_map, clean_tags)
    from calibre_plugins.fix_metadata.compare_review import review_changes
    from calibre_plugins.fix_metadata.opf_compare import (
        read_file_metadata, compare as opf_compare, COMPARE_FIELDS)
except Exception as e:
    logger.error(f"Error importing fix modules: {e}")

PLUGIN_ICONS = ['images/icon.png']


class TagsReviewDialog(QDialog):
    """Review tag canonicalisation (old tags -> new tags) per book.

    changes: [(book_id, title, old_str, new_str, new_list, unknown_list)]
    """
    COL_TITLE = 0
    COL_OLD = 1
    COL_NEW = 2

    def __init__(self, parent, changes):
        super().__init__(parent)
        self.changes = changes
        self.setWindowTitle('Fix Tags - Review Changes')
        self.setWindowModality(Qt.WindowModal)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        n_unknown = sum(1 for c in self.changes if c[5])
        lbl = QLabel(
            '<b>{}</b> book(s) with tag changes.<br>'
            'Tags are mapped onto the controlled vocabulary '
            '(Grupo \u00b7 Valor). Rows with unrecognised tags are kept as-is '
            'and marked for review (<b>{}</b> such book(s)).<br>'
            'Check the rows to apply, then click <b>Apply</b>.'.format(
                len(self.changes), n_unknown))
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        self.table = QTableWidget(len(self.changes), 3, self)
        self.table.setHorizontalHeaderLabels(['Title', 'Current tags', 'New tags'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)

        self.table.blockSignals(True)
        for row, (book_id, title, old_str, new_str, _new_list, unknown) in enumerate(self.changes):
            item = QTableWidgetItem(title)
            item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            item.setCheckState(Qt.Checked)
            item.setData(Qt.UserRole, book_id)
            self.table.setItem(row, self.COL_TITLE, item)
            self.table.setItem(row, self.COL_OLD, QTableWidgetItem(old_str))
            new_item = QTableWidgetItem(new_str)
            if unknown:
                new_item.setToolTip('Sin mapear (se conservan): ' + ', '.join(unknown))
            self.table.setItem(row, self.COL_NEW, new_item)
        self.table.blockSignals(False)
        self.table.resizeColumnsToContents()
        self.table.setSortingEnabled(True)
        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table)

        bar = QHBoxLayout()
        b1 = QPushButton('Select All'); b1.clicked.connect(lambda: self._set_all(Qt.Checked)); bar.addWidget(b1)
        b2 = QPushButton('Deselect All'); b2.clicked.connect(lambda: self._set_all(Qt.Unchecked)); bar.addWidget(b2)
        bar.addStretch()
        self.apply_btn = QPushButton(); self.apply_btn.setDefault(True)
        self.apply_btn.clicked.connect(self.accept); bar.addWidget(self.apply_btn)
        cancel = QPushButton('Cancel'); cancel.clicked.connect(self.reject); bar.addWidget(cancel)
        layout.addLayout(bar)
        self._refresh()
        self.resize(QSize(1000, 560))

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
        self.apply_btn.setText('Apply ({})'.format(n))
        self.apply_btn.setEnabled(n > 0)

    def get_selected_changes(self):
        result = []
        for r in range(self.table.rowCount()):
            if self.table.item(r, self.COL_TITLE).checkState() == Qt.Checked:
                book_id = self.table.item(r, self.COL_TITLE).data(Qt.UserRole)
                for ch in self.changes:
                    if ch[0] == book_id:
                        result.append(ch); break
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

        # ---- Fix all submenu (title/series/language/subtitle + #world) ----
        fixall_menu = self.menu.addMenu('Fix all  (series, language, subtitle, universe from title)')
        ac = fixall_menu.addAction('Selected books')
        ac.setToolTip('Detect series + index, language and "Main: Subtitle" split '
                      'embedded in titles, review them together, and fill #world '
                      'from series automatically (never overwrites)')
        ac.triggered.connect(lambda: self.fix_all_action(scope='selected'))
        ac = fixall_menu.addAction('Entire library')
        ac.setToolTip('Run Fix all on every book in the library')
        ac.triggered.connect(lambda: self.fix_all_action(scope='all'))

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

        self.menu.addSeparator()

        # ---- Check comments submenu ----
        comments_menu = self.menu.addMenu('Check comments  (flag bad synopses)')
        ac = comments_menu.addAction('Selected books')
        ac.setToolTip('Flag comments that are empty, too short, too long, have '
                      'internal repetition, or are junk/boilerplate (including '
                      'appended About the Author/Praise/Reviews/Excerpt '
                      'sections); mark them for review')
        ac.triggered.connect(lambda: self.check_comments_action(scope='selected'))
        ac = comments_menu.addAction('Entire library')
        ac.setToolTip('Check comments for every book in the library')
        ac.triggered.connect(lambda: self.check_comments_action(scope='all'))

        self.menu.addSeparator()

        # ---- Fix tags submenu ----
        tags_menu = self.menu.addMenu('Fix tags  (canonicalise to Grupo \u00b7 Valor)')
        ac = tags_menu.addAction('Selected books')
        ac.setToolTip('Map messy/bilingual tags onto the controlled Spanish '
                      'vocabulary (Grupo \u00b7 Valor); review before saving')
        ac.triggered.connect(lambda: self.fix_tags_action(scope='selected'))
        ac = tags_menu.addAction('Entire library')
        ac.setToolTip('Canonicalise tags for every book in the library')
        ac.triggered.connect(lambda: self.fix_tags_action(scope='all'))

        self.menu.addSeparator()

        # ---- Compare with file metadata (OPF) submenu ----
        opf_menu = self.menu.addMenu('Compare with file metadata  (OPF vs calibre)')
        ac = opf_menu.addAction('Selected books')
        ac.setToolTip('Read title/author/series/language embedded in each book '
                      'file (the EPUB OPF) and review the differences against '
                      'calibre in the CompareMany dialog')
        ac.triggered.connect(lambda: self.compare_opf_action(scope='selected'))
        ac = opf_menu.addAction('Entire library')
        ac.setToolTip('Compare file metadata against calibre for every book')
        ac.triggered.connect(lambda: self.compare_opf_action(scope='all'))

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
    #  Action: Fix all (series, language, subtitle from title; #world     #
    #  automatically from series/title_opf)                                #
    # ------------------------------------------------------------------ #

    def fix_all_action(self, scope='selected'):
        """Detect series + index, language and subtitle embedded in titles,
        and a #world universe from the series, and review all of it together
        in one CompareMany pass.

        Replaces the old separate "Fix series", "Fix subtitle" and "Fix
        universe" actions (each had its own dialog before). #world IS shown
        as a normal column in the same dialog, editable/revertible/
        rejectable like title/series/languages/#subtitle: since there is no
        longer a standalone "Fix universe" menu entry, that dialog is the
        only place left to see and correct it before it's written, and
        because every selected book is already sent to review regardless of
        whether a change was detected (see below), adding the column costs
        no extra clicks. Identifiers stay out and keep their own "Fix
        identifiers" action -- unlike #world, there is nothing to show or
        revert per book (it's a bulk find/replace over the identifiers
        dict, not a single proposed value).

        #world still never overwrites an existing value, and still uses
        whatever series signal is available: the one already saved on the
        book, the one just found in the title this pass, or (last resort)
        one parsed out of #title_opf, the untouched original title kept by
        "Extract metadata" -- so a series that was never saved to the
        `series` field can still resolve a universe.

        Every selected book is sent to review, whether or not any change
        was detected, so the whole selection can be reviewed/edited/
        rejected in one dialog.
        """
        logger.info(f"Action triggered: Fix all ({scope})")

        book_ids = self._get_book_ids(scope)
        if book_ids is None:
            return

        db = self.gui.current_db
        has_title_opf = '#title_opf' in db.custom_field_keys()
        has_subtitle = '#subtitle' in db.custom_field_keys()
        has_world = '#world' in db.custom_field_keys()
        has_serie_gen = '#serie_gen' in db.custom_field_keys()

        if has_subtitle:
            sub_dt = db.field_metadata['#subtitle']['datatype']
            if sub_dt != 'text':
                warning_dialog(self.gui, 'Wrong column type for #subtitle',
                                f"The #subtitle column is a '{sub_dt}' column (probably "
                                "created as 'Long text, like comments'). The review dialog "
                                "will show it as a big rich-text editor instead of a simple "
                                "text box.\n\n"
                                "For a compact review, delete the column and recreate it as "
                                "'Text, column shown in the Tag browser' (Preferences \u2192 "
                                "Add your own columns) with lookup name 'subtitle'. Existing "
                                "values would need to be re-entered.\n\n"
                                "Continuing anyway.",
                                show=True)

        if has_serie_gen:
            sg_dt = db.field_metadata['#serie_gen']['datatype']
            if sg_dt != 'text':
                warning_dialog(self.gui, 'Wrong column type for #serie_gen',
                                f"The #serie_gen column is a '{sg_dt}' column (probably "
                                "created as 'Long text, like comments'). The review dialog "
                                "will show it as a big rich-text editor instead of a simple "
                                "text box.\n\n"
                                "For a compact review, delete the column and recreate it as "
                                "'Text, column shown in the Tag browser' (Preferences \u2192 "
                                "Add your own columns) with lookup name 'serie_gen'. Existing "
                                "values would need to be re-entered.\n\n"
                                "Continuing anyway.",
                                show=True)

        world_rev = load_world_map() if has_world else {}

        total = len(book_ids)

        progress = QProgressDialog(self.gui)
        progress.setWindowTitle('Fix All')
        progress.setCancelButtonText('Cancel')
        progress.setRange(0, total)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)

        from collections import OrderedDict
        proposals = OrderedDict()
        meta = {}   # book_id -> (orig_title, save_opf)

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

            # Most series/index patterns anchor to the END of the string, so a
            # trailing " - Author" (very common: "03 The Raging Storm - Ann
            # Cleeves", "Jackman & Evans - 09 Solace House - JOY ELLIS")
            # defeats every one of them unless it's stripped first. Detection
            # runs on this pre-stripped copy; make_clean_title() below still
            # strips the author suffix from the ORIGINAL title itself.
            title_for_detection = strip_known_author_suffix(
                orig_title, author=book_author, author_sort=book_asort)

            # Serie_Gen: a trailing "(...)" that names a universe/imprint/
            # sub-series tag WITHOUT a number (e.g. "(Elginvale High)",
            # "(American Haunts)") -- separate from the numbered `series`
            # field. Detected and stripped from the working copy BEFORE
            # language/series/subtitle detection run, so it can't be
            # mistaken for one of those (a numbered series paren always
            # contains a digit and is therefore never claimed here -- see
            # find_generic_series_in_title).
            found_serie_gen = find_generic_series_in_title(title_for_detection)
            if found_serie_gen:
                title_for_detection = strip_generic_series_paren(
                    title_for_detection, found_serie_gen)

            found_lang = find_language_in_title(title_for_detection)
            anchor_lang = (mi.language or found_lang or '').lower().strip() or None
            found_series, found_index, sub_g = find_series_in_title(
                title_for_detection, language=anchor_lang,
                author=book_author, author_sort=book_asort)

            # Series/language/author/G-style "(subtitle)"/Serie_Gen cleanup
            # (old Fix Series). serie_gen is passed so it is stripped from
            # the ORIGINAL title too, in case it sits somewhere make_clean_title's
            # other rules wouldn't otherwise reach.
            clean = make_clean_title(
                orig_title, series=found_series, index=found_index,
                language=found_lang, author=book_author, author_sort=book_asort,
                subtitle=sub_g, serie_gen=found_serie_gen)

            # Colon-style "Main: Subtitle" / dash-style "Main - A Blurb" /
            # paren-style "Main (A Blurb)" subtitle detection.
            #
            # This USED to be gated on "no series pattern claimed the title"
            # (if not found_series), on the theory that a series prefix/suffix
            # regex would already have eaten the colon. In practice series and
            # subtitle very commonly come from the SAME title at the SAME
            # time -- "Tormented: A Dark High School Bully Romance (Elginvale
            # High Book 1)" has series "Elginvale High" AND subtitle "A Dark
            # High School Bully Romance" both -- so gating on found_series
            # silently dropped the subtitle in the majority of these cases.
            # The real thing to guard against is double-detecting a subtitle
            # find_series_in_title already returned as sub_g (its own
            # G-style trailing-paren form), so the gate is now "no subtitle
            # found yet", not "no series found".
            #
            # Uses rpartition (LAST ": " / " - ") to match find_subtitle_in_
            # title's own split point -- with 2+ colons the interior one(s)
            # belong to the title, e.g. "Istoria Online: Square One: A LitRPG
            # Adventure" -> title "Istoria Online: Square One", subtitle
            # "A LitRPG Adventure".
            sub_colon = None
            if not sub_g:
                sub_colon = find_subtitle_in_title(clean)
                if sub_colon:
                    main = clean.rpartition(': ')[0].strip()
                    if main and main != clean:
                        clean = main
                else:
                    sub_colon = find_dash_genre_subtitle_in_title(clean)
                    if sub_colon:
                        main = clean.rpartition(' - ')[0].strip()
                        if main and main != clean:
                            clean = main
                    else:
                        sub_colon = find_paren_genre_subtitle_in_title(clean)
                        if sub_colon:
                            main = re.sub(
                                r'\s*\(' + re.escape(sub_colon) + r'\)\s*$',
                                '', clean, flags=re.IGNORECASE).strip()
                            if main and main != clean:
                                clean = main
            subtitle = sub_g or sub_colon

            # Fallback: title = "Series N" when stripping series/subtitle/
            # serie_gen left nothing usable as a per-book title -- either the
            # string is now empty, or what's left is itself just a generic
            # marketing blurb repeated across the whole series (e.g.
            # "Futanarium 3: An Erotic Short Story Bundle" -> series
            # "Futanarium" index 3, and "An Erotic Short Story Bundle" is
            # boilerplate, not this book's real title). Only triggers when a
            # series WAS found -- with no series there is nothing sane to
            # fall back to, so the original (untouched) title wins instead,
            # same as make_clean_title's own empty-string safety net.
            #
            # ALSO requires "not subtitle": if the cascade just above already
            # split off a real subtitle, `clean` is what's left AFTER that
            # split, not the untouched remainder -- re-checking it for
            # blurb-shape here is a category error, not a safety net. E.g.
            # "A Novel Way to Die: a reverse harem murder mystery (Nevermore
            # Bookshop Mysteries Book 6)": once the cascade correctly splits
            # this into title "A Novel Way to Die" / subtitle "a reverse
            # harem murder mystery", the leftover title "A Novel Way to Die"
            # ITSELF happens to match the genre-blurb shape (starts with "A"
            # + contains "Novel") -- so without this guard the real title
            # gets wrongly replaced with "Nevermore Bookshop Mysteries 6".
            if found_series and clean and not subtitle and whole_title_is_genre_blurb(clean):
                subtitle = clean
                idx_txt = ('%g' % found_index) if found_index is not None else ''
                clean = (found_series + (' ' + idx_txt if idx_txt else '')).strip()
            elif found_series and not clean:
                idx_txt = ('%g' % found_index) if found_index is not None else ''
                clean = (found_series + (' ' + idx_txt if idx_txt else '')).strip()

            # Series/index/language/subtitle: always propose whatever was
            # detected, even when a (possibly different) value is already
            # saved. This used to be gated on "only if currently empty" to
            # protect against the series regex cascade's false positives
            # (e.g. "X-Men 3: The Last Stand" -> detects series "X-Men" when
            # the book is really filed under "X-Men Novelizations") -- but
            # since every proposal now goes through the interactive
            # CompareMany review, the human reviewing it is a better filter
            # than a blanket "never touch" rule: accept, edit or revert each
            # field per book. Only #world keeps the automatic never-overwrite
            # rule (see below) since it's not derived from THIS title at all.
            series_to_write = found_series if found_series else None
            index_to_write = found_index if found_index is not None else None
            lang_to_write = found_lang if found_lang else None

            subtitle_to_write = subtitle if subtitle else None

            # #world: use whatever series signal is available -- the one already
            # saved on the book, the one just found in the title this pass, or
            # (as a last resort) one parsed out of #title_opf, the untouched
            # original title kept by "Extract metadata" -- so a series that was
            # never saved to the `series` field can still resolve a universe.
            # Proposed like any other field below; never overwrites a value
            # #world already has.
            world_to_write = None
            if has_world and world_rev:
                existing_world = (db.get_custom(book_id, label='world', index_is_id=True) or '')
                if not str(existing_world).strip():
                    series_for_world = mi.series or found_series
                    if not series_for_world and has_title_opf:
                        opf_title = (db.get_custom(book_id, label='title_opf', index_is_id=True) or '')
                        if opf_title and opf_title.strip() != orig_title.strip():
                            opf_series, _oi, _os = find_series_in_title(
                                opf_title, author=book_author, author_sort=book_asort)
                            series_for_world = opf_series
                    world_to_write = world_for_series(series_for_world, world_rev) if series_for_world else None

            save_opf = False
            if has_title_opf:
                opf_val = (db.get_custom(book_id, label='title_opf', index_is_id=True) or '')
                save_opf = not str(opf_val).strip()

            newmi = mi.deepcopy_metadata()
            newmi.title = clean
            if series_to_write is not None:
                newmi.series = series_to_write
                newmi.series_index = index_to_write
            elif index_to_write is not None:
                newmi.series_index = index_to_write
            if lang_to_write is not None:
                newmi.languages = [lang_to_write]
            if subtitle_to_write is not None:
                newmi.set('#subtitle', subtitle_to_write)
            if world_to_write is not None:
                newmi.set('#world', world_to_write)
            serie_gen_to_write = found_serie_gen if found_serie_gen else None
            if serie_gen_to_write is not None:
                newmi.set('#serie_gen', serie_gen_to_write)

            # Only send the book to review if something actually differs --
            # comparing the built proposal against the current record (not
            # just "was a value detected") so a detected value that happens
            # to match what's already saved doesn't generate an empty row.
            has_change = (
                (newmi.title or '').strip() != (mi.title or '').strip()
                or (newmi.series or '') != (mi.series or '')
                or ((newmi.series_index if newmi.series else None)
                    != (mi.series_index if mi.series else None))
                or list(newmi.languages or []) != list(mi.languages or [])
                or (has_subtitle and (newmi.get('#subtitle') or '') != (mi.get('#subtitle') or ''))
                or (has_world and (newmi.get('#world') or '') != (mi.get('#world') or ''))
                or (has_serie_gen and (newmi.get('#serie_gen') or '') != (mi.get('#serie_gen') or ''))
            )
            if has_change:
                proposals[book_id] = newmi
                meta[book_id] = (orig_title, save_opf)

            if i % BATCH == 0:
                progress.setLabelText(f'Scanning [{i + 1} / {total}]...')
                progress.setValue(i)
                QApplication.processEvents()

        progress.setValue(total)
        progress.close()

        if not proposals:
            info_dialog(self.gui, 'Fix All',
                        'No changes detected in the selected books.', show=True)
            return

        fields = ('title', 'series', 'languages')
        if has_subtitle:
            fields = fields + ('#subtitle',)
        if has_serie_gen:
            fields = fields + ('#serie_gen',)
        if has_world:
            fields = fields + ('#world',)

        accepted, rejected = review_changes(
            self.gui, db, proposals, fields=fields,
            window_title='Fix All - Review changes',
            intro_msg=('Left: proposed values (series/index/language/subtitle/'
                       'serie_gen/universe extracted from the title or the '
                       'series map).  Right: current values.  Edit, revert or '
                       'reject any book before applying.  #world never '
                       'overwrites an existing value.'))
        if accepted is None:      # dialog cancelled: nothing written
            return

        pending_ids = set(proposals.keys())
        rejected_ids = [bid for bid in rejected if bid in pending_ids]
        if rejected_ids:
            try:
                marked = dict(getattr(db.data, 'marked_ids', {}) or {})
            except Exception:
                marked = {}
            for bid in rejected_ids:
                marked[bid] = 'revisar_metadata'
            try:
                db.set_marked_ids(marked)
                self.gui.library_view.model().refresh_ids(list(rejected_ids))
                logger.info(f"Marked {len(rejected_ids)} rejected book(s) as 'revisar_metadata'")
            except Exception as e:
                logger.error(f'Could not set marked ids: {e}')

        updated_ids = []
        for book_id, mi in accepted.items():
            db.set_metadata(book_id, mi, commit=False)
            if has_subtitle:
                db.set_custom(book_id, mi.get('#subtitle'), label='subtitle', commit=False)
            if has_serie_gen:
                db.set_custom(book_id, mi.get('#serie_gen'), label='serie_gen', commit=False)
            if has_world:
                db.set_custom(book_id, mi.get('#world'), label='world', commit=False)
            orig_title, save_opf = meta[book_id]
            if save_opf and has_title_opf:
                db.set_custom(book_id, orig_title, label='title_opf', commit=False)
            updated_ids.append(book_id)

        db.commit()

        if updated_ids:
            self.gui.library_view.model().refresh_ids(updated_ids)
        self.gui.status_bar.show_message(
            f'Fix All: {len(updated_ids)} book(s) updated', 3000)

        msg = f'{len(updated_ids)} book(s) updated.'
        if rejected_ids:
            msg += (f'\n{len(rejected_ids)} book(s) marked for review '
                    f'(search: marks:revisar_metadata).')
        info_dialog(self.gui, 'Fix All', msg, show=True)


    def check_comments_action(self, scope='selected'):
        """Flag comments (synopsis) that look wrong and mark books for review.

        Detects, per book: empty / too short / too long / internal repetition /
        junk-boilerplate (including appended front-back matter such as About
        the Author, Praise, Reviews or an Excerpt -- that is not a synopsis
        and counts as junk; HTML markup itself is never treated as junk).
        Cross-book duplicate synopses are NOT flagged -- duplicate books in
        the library are normal and expected.  Nothing is modified: affected
        books are marked so they can be filtered with
        ``marks:revisar_comentario`` (or a specific reason, e.g.
        ``marks:comentario_corto``).
        """
        logger.info(f"Action triggered: Check comments ({scope})")

        book_ids = self._get_book_ids(scope)
        if book_ids is None:
            return

        db      = self.gui.current_db
        new_api = db.new_api
        total   = len(book_ids)

        progress = QProgressDialog(self.gui)
        progress.setWindowTitle('Check Comments')
        progress.setCancelButtonText('Cancel')
        progress.setRange(0, total)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)

        # ── Phase 1: bulk read of all comments ──────────────────────────
        progress.setLabelText(f'Loading comments for {total} books…')
        progress.setValue(0)
        QApplication.processEvents()
        comments = new_api.all_field_for('comments', book_ids)
        if progress.wasCanceled():
            return

        # ── Phase 2: per-book analysis ───────────────────────────────────
        per_book = {}   # book_id -> set(issue codes)
        BATCH    = 500
        progress.setLabelText(f'Analysing {total} comments…')
        QApplication.processEvents()

        for i, book_id in enumerate(book_ids):
            if progress.wasCanceled():
                return
            html   = comments.get(book_id) or ''
            issues = set(analyze_comment(html))
            if issues:
                per_book[book_id] = issues
            if i % BATCH == 0:
                progress.setLabelText(
                    f'Analysing [{i + 1} / {total}]…  ({len(per_book)} flagged)')
                progress.setValue(i)
                QApplication.processEvents()

        progress.setValue(total)
        progress.close()

        if not per_book:
            info_dialog(self.gui, 'Check Comments',
                        'No se detectaron comentarios problemáticos '
                        f'({total} libros revisados).', show=True)
            return

        # ── Phase 3: mark the affected books (merge with existing marks) ─
        try:
            marked = dict(getattr(db.data, 'marked_ids', {}) or {})
        except Exception:
            marked = {}
        for book_id, issues in per_book.items():
            tokens = ['revisar_comentario']
            tokens += [f'comentario_{c}' for c in sorted(issues)]
            marked[book_id] = ' '.join(tokens)
        try:
            db.set_marked_ids(marked)
            self.gui.library_view.model().refresh_ids(list(per_book.keys()))
            logger.info(f"Marked {len(per_book)} book(s) as 'revisar_comentario'")
        except Exception as e:
            logger.error(f'Could not set marked ids: {e}')

        self.gui.status_bar.show_message(
            f'Comments checked: {len(per_book)} book(s) marked for review', 3000)

        # ── Phase 4: summary + details ──────────────────────────────────
        counts = {}
        for issues in per_book.values():
            for c in issues:
                counts[c] = counts.get(c, 0) + 1

        code_order = ['vacio', 'corto', 'largo', 'repetido', 'basura']
        msg  = f'{len(per_book)} de {total} libros marcados para revisar.\n\n'
        msg += 'Por tipo (un libro puede tener varios):\n'
        for c in code_order:
            if counts.get(c):
                msg += f'  • {ISSUE_LABELS.get(c, c)}: {counts[c]}\n'
        msg += ('\nBuscar en Calibre:  marks:revisar_comentario\n'
                'Por tipo:  marks:comentario_corto, comentario_largo,\n'
                '           comentario_repetido, comentario_basura,\n'
                '           comentario_vacio')

        titles = new_api.all_field_for('title', list(per_book.keys()))
        details = 'Libros marcados:\n\n'
        for book_id, issues in sorted(
                per_book.items(),
                key=lambda kv: titles.get(kv[0]) or ''):
            title = titles.get(book_id) or f'Book {book_id}'
            labels = ', '.join(ISSUE_LABELS.get(c, c)
                               for c in code_order if c in issues)
            details += f'"{title}"\n    → {labels}\n'

        info_dialog(self.gui, 'Check Comments', msg,
                    det_msg=details, show=True)

    # ------------------------------------------------------------------ #
    #  Action: Fix tags (canonicalise to "Grupo · Valor")                  #
    # ------------------------------------------------------------------ #

    def compare_opf_action(self, scope='selected'):
        """Compare the metadata embedded in each book\'s file (the EPUB OPF)
        against the current calibre metadata and review the differences in
        calibre\'s native CompareMany dialog.

        The "same vs different" decision reuses Smart Metadata\'s comparison
        method (fuzzy title/author similarity + language-conflict check) plus a
        normalised series/index compare.  Books whose file and calibre metadata
        already agree are skipped.  For every accepted book the file value is
        written back into calibre (OPF overwrites calibre)."""
        logger.info(f"Action triggered: Compare file OPF ({scope})")

        book_ids = self._get_book_ids(scope)
        if book_ids is None:
            return

        db = self.gui.current_db
        total = len(book_ids)

        # Umbrales de similitud (mismos valores por defecto que Smart Metadata).
        TITLE_THR, AUTHOR_THR, REQUIRE_AUTHOR = 90, 80, True

        progress = QProgressDialog(self.gui)
        progress.setWindowTitle('Compare file metadata (OPF)')
        progress.setCancelButtonText('Cancel')
        progress.setRange(0, total)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setLabelText(f'Reading file metadata for {total} book(s)...')
        progress.setValue(0)
        QApplication.processEvents()

        from collections import OrderedDict
        proposals = OrderedDict()
        no_file = 0
        BATCH = 20
        for i, book_id in enumerate(book_ids):
            if progress.wasCanceled():
                break
            oldmi = db.get_metadata(book_id, index_is_id=True,
                                    get_user_categories=False)
            filemi, fmt = read_file_metadata(db, book_id)
            if filemi is None:
                no_file += 1
            else:
                try:
                    changed, newmi = opf_compare(
                        oldmi, filemi, TITLE_THR, AUTHOR_THR, REQUIRE_AUTHOR)
                except Exception as e:
                    logger.warning(f'Compare failed for id={book_id}: {e}')
                    changed = None
                if changed:
                    proposals[book_id] = newmi
            if i % BATCH == 0:
                progress.setLabelText(
                    f'Reading [{i + 1} / {total}]...  ({len(proposals)} differ)')
                progress.setValue(i)
                QApplication.processEvents()

        progress.setValue(total)
        progress.close()

        if not proposals:
            msg = 'All checked books already match their file metadata.'
            if no_file:
                msg += f'\n({no_file} book(s) had no readable EPUB/AZW3 file.)'
            info_dialog(self.gui, 'Compare file metadata (OPF)', msg, show=True)
            return

        accepted, rejected = review_changes(
            self.gui, db, proposals, fields=COMPARE_FIELDS,
            window_title='Compare file metadata (OPF) - Review changes',
            intro_msg=('Left: values read from the book file (the EPUB OPF).  '
                       'Right: current calibre values.  Accept to overwrite '
                       'calibre with the file value; reject to keep calibre.'))
        if accepted is None:      # dialog cancelled
            return

        if not accepted:
            info_dialog(self.gui, 'Compare file metadata (OPF)',
                        'No changes applied.', show=True)
            return

        updated_ids = []
        for book_id, mi in accepted.items():
            db.set_metadata(book_id, mi, commit=False)
            updated_ids.append(book_id)
        db.commit()

        self.gui.library_view.model().refresh_ids(updated_ids)
        self.gui.status_bar.show_message(
            f'File metadata compared: {len(updated_ids)} book(s) updated', 3000)

        msg = f'{len(updated_ids)} book(s) updated from their file metadata.'
        if no_file:
            msg += f'\n{no_file} book(s) had no readable file.'
        info_dialog(self.gui, 'Compare file metadata (OPF)', msg, show=True)

    def fix_tags_action(self, scope='selected'):
        """Consolidate tags from ``tags`` + ``#subjects`` + ``#clasificacion``
        onto the controlled Spanish vocabulary and store everything in ``tags``.

        Recognised values become their canonical ``Grupo · Valor`` form, junk is
        removed, and unrecognised tags are kept (no data loss); their books are
        marked ``revisar_tags``.  ``#subjects`` is emptied after consolidation;
        ``#clasificacion`` is left untouched (owned by the classifier).
        """
        logger.info(f"Action triggered: Fix tags ({scope})")

        book_ids = self._get_book_ids(scope)
        if book_ids is None:
            return

        rules, drop, drop_res = load_tags_map()
        if not rules:
            error_dialog(self.gui, 'Missing tag map',
                         "tags_map.json was not found or is empty.", show=True)
            return

        db      = self.gui.current_db
        new_api = db.new_api
        total   = len(book_ids)

        keys = db.custom_field_keys()
        has_subjects = '#subjects' in keys
        has_clasif   = '#clasificacion' in keys

        def _tolist(v):
            if v is None:
                return []
            if isinstance(v, (list, tuple)):
                return [str(x).strip() for x in v if str(x).strip()]
            txt = str(v).strip()
            return [p.strip() for p in txt.split(',') if p.strip()] if txt else []

        progress = QProgressDialog(self.gui)
        progress.setWindowTitle('Fix Tags')
        progress.setCancelButtonText('Cancel')
        progress.setRange(0, total)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)

        progress.setLabelText(f'Loading tags for {total} books…')
        progress.setValue(0)
        QApplication.processEvents()
        all_tags   = new_api.all_field_for('tags', book_ids)
        all_subj   = new_api.all_field_for('#subjects', book_ids) if has_subjects else {}
        all_clasif = new_api.all_field_for('#clasificacion', book_ids) if has_clasif else {}
        if progress.wasCanceled():
            return

        # (book_id, title, old_str, new_str, new_list, unknown_list)
        pending = []
        subj_clear = {}   # book_id -> True when its #subjects must be emptied
        BATCH = 500
        progress.setLabelText(f'Analysing {total} books…')
        QApplication.processEvents()

        for i, book_id in enumerate(book_ids):
            if progress.wasCanceled():
                return
            cur_tags = _tolist(all_tags.get(book_id))
            subj     = _tolist(all_subj.get(book_id))
            clasif   = _tolist(all_clasif.get(book_id))
            union    = cur_tags + clasif + subj
            new_list, info = clean_tags(union, rules, drop, drop_res)

            tags_changed = new_list != cur_tags
            need_clear   = has_subjects and bool(subj)
            if tags_changed or need_clear:
                if need_clear:
                    subj_clear[book_id] = True
                pending.append((book_id, None,
                                ', '.join(cur_tags), ', '.join(new_list),
                                new_list, info['unknown']))
            if i % BATCH == 0:
                progress.setLabelText(
                    f'Analysing [{i + 1} / {total}]…  ({len(pending)} to change)')
                progress.setValue(i)
                QApplication.processEvents()

        progress.setValue(total)
        progress.close()

        if not pending:
            info_dialog(self.gui, 'Fix Tags',
                        f'No tag changes needed ({total} books checked).', show=True)
            return

        # Apply directly (no review dialog): every detected change is written.
        titles = new_api.all_field_for('title', [p[0] for p in pending])
        confirmed = [(bid, titles.get(bid) or f'Book {bid}', o, n, nl, unk)
                     for (bid, _t, o, n, nl, unk) in pending]

        confirmed_ids = {bid for (bid, _t, _o, _n, _nl, _u) in confirmed}
        updates = {bid: nl for (bid, _t, _o, _n, nl, _u) in confirmed}
        new_api.set_field('tags', updates)

        # empty #subjects for the confirmed books that had content there
        cleared = 0
        if has_subjects:
            subj_updates = {bid: None for bid in confirmed_ids if subj_clear.get(bid)}
            if subj_updates:
                new_api.set_field('#subjects', subj_updates)
                cleared = len(subj_updates)

        # mark books that still contain unrecognised tags
        review_ids = [bid for (bid, _t, _o, _n, _nl, unk) in confirmed if unk]
        if review_ids:
            try:
                marked = dict(getattr(db.data, 'marked_ids', {}) or {})
            except Exception:
                marked = {}
            for bid in review_ids:
                marked[bid] = 'revisar_tags'
            try:
                db.set_marked_ids(marked)
            except Exception as e:
                logger.error(f'Could not set marked ids: {e}')

        refreshed = set(updates) | set(confirmed_ids)
        self.gui.library_view.model().refresh_ids(list(refreshed))
        self.gui.status_bar.show_message(
            f'Tags fixed: {len(updates)} book(s) updated', 3000)

        details = ''
        for bid, title, old_str, new_str, _nl, unk in confirmed:
            details += f'"{title}"\n    antes: {old_str}\n    ahora: {new_str}\n'
            if unk:
                details += '    sin mapear (conservados): ' + ', '.join(unk) + '\n'
            details += '\n'
        msg = f'{len(updates)} book(s) updated.'
        if cleared:
            msg += f'\n#subjects vaciado en {cleared} libro(s).'
        if review_ids:
            msg += (f'\n{len(review_ids)} book(s) con tags sin mapear '
                    f'(buscar: marks:revisar_tags).')
        info_dialog(self.gui, 'Fix Tags', msg, det_msg=details, show=True)
