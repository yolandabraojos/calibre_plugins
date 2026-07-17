#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Smart Metadata - InterfaceAction.
# Reutiliza la descarga masiva (bulk_download.start_download) y el dialogo de
# revision (metadata.diff.CompareMany) de Calibre. Anade una fase de
# clasificacion entre medias: los candidatos "seguros" (titulo/autor identicos
# o muy similares) se aplican solos; solo los "dudosos" van a CompareMany.
from __future__ import unicode_literals, division, absolute_import, print_function

import os
import copy
import shutil
import traceback
from functools import partial

try:
    from qt.core import QDialog, QIcon
except ImportError:
    from PyQt5.Qt import QDialog, QIcon

from calibre.gui2 import Dispatcher, error_dialog, info_dialog
from calibre.gui2.actions import InterfaceAction
from calibre.ebooks.metadata.book.base import Metadata
from calibre.ebooks.metadata.opf2 import OPF, metadata_to_opf
from calibre.ebooks.metadata.sources.prefs import msprefs

from calibre_plugins.smart_metadata.config import prefs
from calibre_plugins.smart_metadata.matching import classify

__license__ = 'GPL v3'
__copyright__ = '2026, Yolanda Braojos'


class SmartMetadataAction(InterfaceAction):

    name = 'Smart Metadata'
    action_spec = (
        'Descarga inteligente',
        'download-metadata.png',
        'Descarga metadatos: aplica los seguros y revisa solo los dudosos',
        None,
    )
    action_type = 'current'

    def genesis(self):
        self.qaction.triggered.connect(self.run)

    def location_selected(self, loc):
        self.qaction.setEnabled(loc == 'library')

    # --- disparo -----------------------------------------------------------
    def run(self, *args):
        if self.gui.current_view() is not self.gui.library_view:
            return error_dialog(self.gui, 'Smart Metadata',
                'Esto solo funciona sobre la biblioteca de calibre.', show=True)
        ids = list(self.gui.library_view.get_selected_ids())
        if not ids:
            return error_dialog(self.gui, 'Smart Metadata',
                'No hay libros seleccionados.', show=True)
        try:
            from calibre.ebooks.metadata.sources.update import update_sources
            update_sources()
        except Exception:
            pass
        from calibre.gui2.metadata.bulk_download import start_download
        start_download(self.gui, ids, Dispatcher(self.downloaded), ensure_fields=None)

    # --- fin de la descarga ------------------------------------------------
    def downloaded(self, job):
        if job.failed:
            return self.gui.job_exception(
                job, dialog_title='Fallo al descargar metadatos')
        try:
            self._process(job)
        except Exception:
            error_dialog(self.gui, 'Smart Metadata',
                'Error procesando los metadatos descargados.',
                det_msg=traceback.format_exc(), show=True)

    def _process(self, job):
        from calibre.gui2.metadata.bulk_download import get_job_details
        (aborted, good_ids, tdir, log_file, failed_ids, failed_covers,
            all_failed, det_msg, lm_map) = get_job_details(job)

        if aborted:
            return self._cleanup(tdir)
        if all_failed:
            num = len(failed_ids | failed_covers)
            self._cleanup(tdir)
            return error_dialog(self.gui, 'Descarga fallida',
                'No se pudo descargar metadatos ni portada de ninguno de '
                'los %d libros.' % num, det_msg=det_msg, show=True)

        db = self.gui.current_db

        title_thr = int(prefs['title_threshold']) / 100.0
        author_thr = int(prefs['author_threshold']) / 100.0
        require_author = bool(prefs['require_author'])

        def paths(book_id):
            opf = os.path.join(tdir, '%d.mi' % book_id)
            opf = opf if os.path.exists(opf) else None
            cov = os.path.join(tdir, '%d.cover' % book_id)
            cov = cov if os.path.exists(cov) else None
            return opf, cov

        def load_new(opf, oldmi):
            with open(opf, 'rb') as f:
                newmi = OPF(f, basedir=os.path.dirname(opf),
                            populate_spine=False).to_book_metadata()
            return newmi

        # Clasificar: seguros (auto) vs dudosos (revision).
        auto_ids, review_ids = [], []
        for book_id in good_ids:
            opf, cov = paths(book_id)
            if opf is None:
                # Solo portada, sin metadatos que juzgar: a revision.
                review_ids.append(book_id)
                continue
            try:
                oldmi = db.get_metadata(book_id, index_is_id=True)
                newmi = load_new(opf, oldmi)
                seguro, _ts, _as = classify(
                    oldmi, newmi, title_thr, author_thr, require_author)
            except Exception:
                review_ids.append(book_id)
                continue
            (auto_ids if seguro else review_ids).append(book_id)

        # Cierre que CompareMany usa para pintar izquierda/derecha.
        def get_metadata(book_id):
            oldmi = db.get_metadata(book_id, index_is_id=True,
                                    get_cover=True, cover_as_data=True)
            opf, cov = paths(book_id)
            if opf is None:
                newmi = Metadata(oldmi.title, authors=tuple(oldmi.authors))
            else:
                with open(opf, 'rb') as f:
                    newmi = OPF(f, basedir=os.path.dirname(opf),
                                populate_spine=False).to_book_metadata()
                newmi.cover, newmi.cover_data = None, (None, None)
                for x in ('title', 'authors'):
                    if newmi.is_null(x):
                        newmi.set(x, copy.copy(oldmi.get(x)))
            if cov:
                with open(cov, 'rb') as f:
                    newmi.cover_data = ('jpg', f.read())
            return oldmi, newmi

        final_map = {book_id: paths(book_id) for book_id in auto_ids}
        rejected = 0

        # Revision manual solo de los dudosos.
        if review_ids:
            from calibre.gui2.metadata.diff import CompareMany
            d = CompareMany(
                set(review_ids), get_metadata, db.field_metadata,
                parent=self.gui,
                window_title='Revisar metadatos dudosos',
                reject_button_tooltip='Descartar los metadatos descargados de este libro',
                accept_all_tooltip='Usar los metadatos descargados para todos los restantes',
                reject_all_tooltip='Descartar los metadatos descargados de todos los restantes',
                revert_tooltip='Descartar el valor descargado de: %s',
                intro_msg=('Estos son los DUDOSOS (los seguros ya se aplicaran '
                           'automaticamente). A la izquierda lo descargado, a la '
                           'derecha lo original. Si un valor descargado esta '
                           'vacio, se conserva el original.'),
                action_button=('&Ver libro', 'view.png',
                               self.gui.iactions['View'].view_historical),
                db=db)
            if d.exec() == QDialog.DialogCode.Accepted:
                for book_id, (changed, mi) in d.accepted_map.items():
                    if mi is None:  # descartado por el usuario
                        rejected += 1
                        continue
                    opf, cov = paths(book_id)
                    if changed:
                        cfile = mi.cover
                        mi.cover, mi.cover_data = None, (None, None)
                        if opf is not None:
                            with open(opf, 'wb') as f:
                                f.write(metadata_to_opf(mi))
                        if cfile and cov:
                            shutil.copyfile(cfile, cov)
                            try:
                                os.remove(cfile)
                            except Exception:
                                pass
                    final_map[book_id] = paths(book_id)
            else:
                # Revision cancelada: los seguros SI se aplican igualmente.
                rejected += len(review_ids)

        stats = {
            'auto': len(auto_ids),
            'review': len(review_ids),
            'rejected': rejected,
            'applied': len(final_map),
            'failed': len(failed_ids | failed_covers),
        }

        if not final_map:
            self._cleanup(tdir)
            return info_dialog(self.gui, 'Smart Metadata',
                'No se aplico ningun metadato.\n\n' + self._summary(stats),
                show=True)

        em = self.gui.iactions['Edit Metadata']
        em.apply_metadata_changes(
            final_map, merge_comments=msprefs['append_comments'],
            icon='download-metadata.png',
            callback=partial(self._finish, tdir, stats))

    # --- cierre ------------------------------------------------------------
    def _finish(self, tdir, stats, applied_ids):
        self._cleanup(tdir)
        info_dialog(self.gui, 'Smart Metadata completado',
                    self._summary(stats), show=True)

    @staticmethod
    def _summary(stats):
        return (
            'Aplicados automaticamente (seguros): %(auto)d\n'
            'Enviados a revision (dudosos): %(review)d\n'
            'Rechazados en revision: %(rejected)d\n'
            'Total aplicado a la biblioteca: %(applied)d\n'
            'Fallidos en la descarga: %(failed)d' % stats)

    @staticmethod
    def _cleanup(tdir):
        try:
            shutil.rmtree(tdir, ignore_errors=True)
        except Exception:
            pass
