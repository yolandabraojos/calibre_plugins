from __future__ import unicode_literals, division, absolute_import, print_function

__license__   = 'GPL v3'
__copyright__ = '2026, Fix Metadata Plugin'

import logging

logger = logging.getLogger('FIX_METADATA_PLUGIN')

try:
    from PyQt5.Qt import QMenu, QToolButton
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
    from calibre_plugins.fix_metadata.fix_title import clean_title
    from calibre_plugins.fix_metadata.fix_author import fix_author
except Exception as e:
    logger.error(f"Error importing fix modules: {e}")

PLUGIN_ICONS = ['images/icon.png']


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

        # ---- Fix title submenu ----
        title_menu = self.menu.addMenu('Fix title  (remove series prefix & language)')
        ac = title_menu.addAction('Selected books')
        ac.setToolTip('Strip  SeriesName [N] -  prefix and  (spa/eng)  suffix '
                      'from the selected books')
        ac.triggered.connect(lambda: self.clean_titles(scope='selected'))

        ac = title_menu.addAction('Entire library')
        ac.setToolTip('Strip series prefix and language suffix from every book in the library')
        ac.triggered.connect(lambda: self.clean_titles(scope='all'))

        # ---- Fix author submenu ----
        author_menu = self.menu.addMenu('Fix author  (Last, First → First Last + initials)')
        ac = author_menu.addAction('Selected books')
        ac.setToolTip('Reverse "Apellido, Nombre" order and fix missing dots/spaces '
                      'in initials for the selected books')
        ac.triggered.connect(lambda: self.fix_authors(scope='selected'))

        ac = author_menu.addAction('Entire library')
        ac.setToolTip('Fix author names for every book in the library')
        ac.triggered.connect(lambda: self.fix_authors(scope='all'))

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

        for book_id, title, generator, book_producer, title_opf, subjects in extracted_ids:
            try:
                if generator:
                    db.set_custom(book_id, generator,     label='generator',     commit=False)
                if book_producer:
                    db.set_custom(book_id, book_producer, label='book_producer', commit=False)
                if title_opf:
                    db.set_custom(book_id, title_opf,     label='title_opf',     commit=False)
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
