#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Smart Metadata - InterfaceAction.
# Reutiliza la descarga masiva (bulk_download) y el dialogo de revision
# (metadata.diff.CompareMany) de Calibre, con una fase de clasificacion:
# los candidatos "seguros" (titulo/autor/idioma coherentes) se aplican solos;
# solo los "dudosos" van a CompareMany.
#
# Pipeline con solape: la bomba de DESCARGA baja las rondas una tras otra en
# segundo plano sin esperar a la revision; la bomba de REVISION abre CompareMany
# grupo a grupo.
#
# Aplicacion PROGRESIVA: los libros se escriben en la biblioteca sin esperar a
# terminarlo todo. Los seguros aterrizan en cuanto hay un momento sin revision
# abierta; los dudosos se cosechan al cerrar la ventana de revision.
# Nunca se aplica mientras hay un CompareMany modal abierto ni mientras hay otra
# aplicacion en curso: esas dos operaciones se serializan para no solapar GUIs.
#
# Cierre de la ventana de revision (segun como cierra Calibre):
#   - "Aceptar todos" / terminar la lista / "Rechazar todos los restantes"
#     -> cierran con codigo Accepted y accepted_map cubre TODOS los del grupo
#     (los rechazados como (False, None)). Se aplica/descarta lo indicado.
#   - Cerrar la ventana (X / Cancelar) -> cierra con codigo Rejected y
#     accepted_map solo trae lo que se reviso. Lo revisado se aplica; lo que
#     quedo SIN revisar NO se pierde: se reencola y, tras aplicar lo confirmado,
#     la revision se REABRE con esos pendientes para poder continuar. Para
#     descartar el resto sin revisarlo, "Rechazar todos los restantes".
#
# Fallback: los libros que no encuentran nada con su titulo de biblioteca se
# reintentan (solo entonces) usando el titulo de un campo alternativo
# (por defecto la columna #title_opf), reusando el mismo worker de Calibre.
from __future__ import unicode_literals, division, absolute_import, print_function

import os
import copy
import shutil
import traceback

try:
    from qt.core import QDialog, QTimer
except ImportError:
    from PyQt5.Qt import QDialog, QTimer

from calibre.gui2 import Dispatcher, error_dialog, info_dialog
from calibre.gui2.actions import InterfaceAction
from calibre.ebooks.metadata.book.base import Metadata
from calibre.ebooks.metadata.opf2 import OPF, metadata_to_opf
from calibre.ebooks.metadata.sources.prefs import msprefs

from calibre_plugins.smart_metadata.config import prefs
from calibre_plugins.smart_metadata.matching import classify

__license__ = 'GPL v3'
__copyright__ = '2026, Yolanda Braojos'


# --- descarga de fallback -------------------------------------------------
# Copia reducida de calibre.gui2.metadata.bulk_download.download que SUSTITUYE
# el titulo de cada libro por el del campo alternativo antes de mandarlo al
# worker de identificacion de Calibre. Se ejecuta en el hilo del Job (igual que
# la descarga normal) y delega la identificacion al worker de siempre.
def fallback_download(all_ids, title_overrides, tf, db, do_identify, covers,
                      ensure_fields, log=None, abort=None, notifications=None):
    from calibre.ebooks.metadata.opf2 import metadata_to_opf as _to_opf
    from calibre.ptempfile import PersistentTemporaryDirectory
    from calibre.utils.ipc.simple_worker import WorkerError, fork_job

    ids = list(all_ids)
    batch_size = 5
    batches = [ids[i:i + batch_size] for i in range(0, len(ids), batch_size)]
    tdir = PersistentTemporaryDirectory('_smeta_fallback')

    failed_ids = set()
    failed_covers = set()
    title_map = {}
    lm_map = {}
    ans = set()
    all_failed = True
    aborted = False

    for bids in batches:
        if abort is not None and abort.is_set():
            break
        metadata = {}
        for i in bids:
            mi = db.get_metadata(i, index_is_id=True, get_user_categories=False)
            ov = title_overrides.get(i)
            if ov:
                mi.title = ov
            title_map[i] = mi.title
            lm_map[i] = mi.last_modified
            metadata[i] = _to_opf(mi, default_lang='und')
        try:
            ret = fork_job('calibre.ebooks.metadata.sources.worker', 'main',
                           (do_identify, covers, metadata, ensure_fields, tdir),
                           abort=abort, no_output=True)
        except WorkerError as e:
            if getattr(e, 'orig_tb', None):
                raise Exception('Fallback metadata download failed:\n\n' + e.orig_tb)
            raise
        fids, fcovs, allf = ret['result']
        if not allf:
            all_failed = False
        failed_ids |= set(fids)
        failed_covers |= set(fcovs)
        ans |= (set(bids) - set(fids))

    if abort is not None and abort.is_set():
        aborted = True
    if log is not None:
        try:
            log('Fallback download complete, %d failures' % len(failed_ids))
        except Exception:
            pass
    return (aborted, ans, tdir, tf, failed_ids, failed_covers, title_map,
            lm_map, all_failed)


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
        # Guarda de reentrada: no permitir arrancar un segundo pipeline encima
        # de otro vivo (compartirian el estado de instancia y se mezclarian).
        if getattr(self, '_pipeline_active', False):
            return error_dialog(self.gui, 'Smart Metadata',
                'Ya hay una descarga inteligente en marcha. Espera a que '
                'termine antes de lanzar otra.', show=True)
        ids = list(self.gui.library_view.get_selected_ids())
        if not ids:
            return error_dialog(self.gui, 'Smart Metadata',
                'No hay libros seleccionados.', show=True)
        try:
            from calibre.ebooks.metadata.sources.update import update_sources
            update_sources()
        except Exception:
            pass

        try:
            batch = int(prefs['batch_size'])
        except Exception:
            batch = 0

        if batch and batch > 0 and len(ids) > batch:
            chunks = [ids[i:i + batch] for i in range(0, len(ids), batch)]
        else:
            chunks = [ids]
        self._start_pipeline(ids, chunks)

    # --- arranque del pipeline --------------------------------------------
    def _start_pipeline(self, ids, chunks):
        from calibre.gui2.metadata.bulk_download import ConfirmDialog
        d = ConfirmDialog(ids, self.gui)
        if d.exec() != QDialog.DialogCode.Accepted:
            return
        self._identify, self._covers = d.identify, d.covers

        # Estado del pipeline.
        self._pipeline_active = True
        self._chunks = chunks
        self._nchunks = len(chunks)
        self._total_books = len(ids)
        self._dl_idx = 0
        self._dl_done = False
        self._pending_ids = []       # dudosos aun no mostrados (lista plana)
        self._review_dialog = None   # CompareMany abierto ahora mismo, o None
        self._review_paused = False  # cierre a medias: rompe el pump para aplicar antes de reabrir
        self._can_inject = False     # el dialogo abierto admite anadir items en caliente
        self._dialog_ids = set()     # ids que han entrado en el dialogo abierto
        self._book_paths = {}        # book_id -> (opf, cov)
        self._active_tdirs = []      # se limpian todos al final
        self._to_apply = {}          # book_id -> (opf, cov) pendientes de ESCRIBIR ya
        self._apply_in_flight = False  # hay un apply_metadata_changes en curso
        self._finalized = False
        self._failed_ids = set()     # fallos de METADATOS (no de portada); se descuentan al rescatar
        self._agg = {'auto': 0, 'review': 0, 'rejected': 0, 'applied': 0,
                     'unreviewed': 0}

        # Umbrales.
        self._title_thr = int(prefs['title_threshold']) / 100.0
        self._author_thr = int(prefs['author_threshold']) / 100.0
        self._require_author = bool(prefs['require_author'])

        # Fallback.
        self._use_fallback = bool(prefs['use_fallback'])
        self._fb_field = str(prefs['fallback_field'] or '').strip()
        self._fallback_started = False
        self._fb_chunks = []
        self._fb_idx = 0
        self._fb_titles = {}         # book_id -> titulo del campo alternativo

        self._dl_start_next()

    # --- bomba de descarga -------------------------------------------------
    def _dl_start_next(self):
        # Fase principal: rondas con el titulo de la biblioteca.
        if self._dl_idx < self._nchunks:
            chunk = self._chunks[self._dl_idx]
            self._dl_idx += 1
            self._start_download_job(chunk, main=True)
            return
        # Transicion a la fase de fallback (se construye una sola vez).
        if not self._fallback_started:
            self._fallback_started = True
            self._build_fallback_chunks()
        if self._fb_idx < len(self._fb_chunks):
            chunk = self._fb_chunks[self._fb_idx]
            self._fb_idx += 1
            self._start_download_job(chunk, main=False)
            return
        # No queda nada por descargar.
        self._dl_done = True

    def _start_download_job(self, chunk, main):
        from calibre.gui2.metadata.bulk_download import Job
        from calibre.ptempfile import PersistentTemporaryFile
        db = self.gui.current_db
        tf = PersistentTemporaryFile('_metadata_bulk.log')
        tf.close()
        if main:
            from calibre.gui2.metadata.bulk_download import download
            func = download
            args = (chunk, tf.name, db, self._identify, self._covers, None)
            if self._nchunks > 1:
                label = ('Descarga inteligente: ronda %d/%d (%d libros)'
                         % (self._dl_idx, self._nchunks, len(chunk)))
            else:
                label = 'Descarga inteligente (%d libros)' % len(chunk)
        else:
            func = fallback_download
            args = (chunk, self._fb_titles, tf.name, db, self._identify,
                    self._covers, None)
            label = ('Descarga inteligente (fallback por %s): %d libros'
                     % (self._fb_field or 'campo alternativo', len(chunk)))
        job = Job('metadata bulk download', label, func, args, {},
                  Dispatcher(self._dl_finished))
        job.metadata_and_covers = (self._identify, self._covers)
        job.download_debug_log = tf.name
        self.gui.job_manager.run_threaded_job(job)
        self.gui.status_bar.show_message(label, 3000)

    def _dl_finished(self, job):
        if job.failed:
            self.gui.job_exception(
                job, dialog_title='Fallo al descargar metadatos (ronda)')
            self._dl_done = True
        else:
            aborted = False
            try:
                aborted = self._classify_round(job)
            except Exception:
                error_dialog(self.gui, 'Smart Metadata',
                    'Error procesando una ronda descargada.',
                    det_msg=traceback.format_exc(), show=True)
            if aborted:
                self._dl_done = True   # el usuario paro el job: no lanzar mas
            else:
                self._dl_start_next()
        # Fin de ronda: es un punto natural para reabrir la revision si estaba
        # en pausa por un cierre a medias. Ahora que hay resultados nuevos (o se
        # acabo la descarga), dejamos que el pump vuelva a mostrar lo pendiente.
        self._review_paused = False
        self._kick()

    def _classify_round(self, job):
        """Clasifica los resultados de una ronda (principal o de fallback).
        Devuelve True si el job fue abortado por el usuario."""
        from calibre.gui2.metadata.bulk_download import get_job_details
        (aborted, good_ids, tdir, log_file, failed_ids, failed_covers,
            all_failed, det_msg, lm_map) = get_job_details(job)

        # Fallos de metadatos (no de portada). Set: no se cuentan dos veces.
        self._failed_ids |= set(failed_ids)
        if tdir:
            self._active_tdirs.append(tdir)

        db = self.gui.current_db
        review_ids = []
        for book_id in good_ids:
            opf = os.path.join(tdir, '%d.mi' % book_id)
            opf = opf if os.path.exists(opf) else None
            cov = os.path.join(tdir, '%d.cover' % book_id)
            cov = cov if os.path.exists(cov) else None
            self._book_paths[book_id] = (opf, cov)
            # Ha producido resultado: ya no es un fallo (rescatado si lo era).
            self._failed_ids.discard(book_id)
            if opf is None:
                review_ids.append(book_id)
                continue
            try:
                oldmi = db.get_metadata(book_id, index_is_id=True)
                # Para los libros de fallback, comparamos contra el titulo del
                # campo alternativo (con el que se busco), no contra el titulo
                # sucio de la biblioteca: asi un match limpio puede auto-aplicarse.
                if book_id in self._fb_titles:
                    oldmi.title = self._fb_titles[book_id]
                with open(opf, 'rb') as f:
                    newmi = OPF(f, basedir=os.path.dirname(opf),
                                populate_spine=False).to_book_metadata()
                seguro, _ts, _as = classify(
                    oldmi, newmi, self._title_thr, self._author_thr,
                    self._require_author)
            except Exception:
                review_ids.append(book_id)
                continue
            if seguro:
                # Seguro: a la cola de aplicacion inmediata (se escribira en el
                # proximo momento sin revision abierta).
                self._to_apply[book_id] = (opf, cov)
                self._agg['auto'] += 1
            else:
                review_ids.append(book_id)

        if review_ids:
            self._agg['review'] += len(review_ids)
            self._pending_ids.extend(review_ids)
        return bool(aborted)

    # --- fallback ----------------------------------------------------------
    def _read_fb_title(self, db, book_id):
        api = getattr(db, 'new_api', None)
        if api is None or not self._fb_field:
            return None
        f = self._fb_field
        names = [f]
        names.append(f[1:] if f.startswith('#') else '#' + f)
        for name in names:
            try:
                v = api.field_for(name, book_id)
            except Exception:
                v = None
            if isinstance(v, str) and v.strip():
                return v.strip()
        return None

    def _build_fallback_chunks(self):
        self._fb_chunks = []
        self._fb_idx = 0
        self._fb_titles = {}
        if not self._use_fallback or not self._fb_field or not self._failed_ids:
            return
        db = self.gui.current_db
        ids = []
        for book_id in list(self._failed_ids):
            t = self._read_fb_title(db, book_id)
            if not t:
                continue
            try:
                libt = db.get_metadata(book_id, index_is_id=True).title or ''
            except Exception:
                libt = ''
            # Solo si aporta algo distinto al titulo que ya fallo.
            if t.strip().lower() != libt.strip().lower():
                self._fb_titles[book_id] = t
                ids.append(book_id)
        if not ids:
            return
        try:
            batch = int(prefs['batch_size'])
        except Exception:
            batch = 0
        if batch and batch > 0:
            self._fb_chunks = [ids[i:i + batch] for i in range(0, len(ids), batch)]
        else:
            self._fb_chunks = [ids]

    # --- bomba de revision -------------------------------------------------
    def _kick(self):
        QTimer.singleShot(0, self._pump)

    def _pump(self):
        # Dialogo abierto: anadir los dudosos nuevos EN CALIENTE (si el dialogo
        # lo admite). Todo ocurre en el hilo de la GUI, asi que mutar d.ids es
        # seguro. Si no admite inyeccion, se quedan pendientes para un dialogo
        # nuevo cuando este se cierre.
        if self._review_dialog is not None:
            if self._can_inject and self._pending_ids:
                d = self._review_dialog
                new = self._pending_ids
                self._pending_ids = []
                try:
                    d.ids.extend(new)
                    d.total += len(new)
                    self._dialog_ids |= set(new)
                except Exception:
                    self._pending_ids = new + self._pending_ids
            return
        # No solapar GUIs: si hay una aplicacion en curso, esperamos a que
        # termine. Su callback (_on_applied) vuelve a llamar al pump.
        if self._apply_in_flight:
            return
        # Sin dialogo abierto: abrir con todo lo pendiente; repetir si llega mas
        # mientras se cerraba (asi ninguno se pierde). Si esta en pausa (cierre
        # a medias), NO reabrimos: esperamos al fin de la proxima ronda.
        while self._pending_ids and not self._review_paused:
            group = self._pending_ids
            self._pending_ids = []
            self._open_review(group)
        # Momento seguro (sin revision abierta): escribe lo acumulado.
        self._flush_apply()
        # Si un cierre a medias reencolo dudosos y no habia nada que aplicar
        # (o ya se aplico de forma sincrona), levantamos la pausa y reabrimos
        # la revision con lo reencolado.
        if self._review_paused and not self._apply_in_flight:
            self._review_paused = False
            if self._pending_ids:
                self._kick()
        self._maybe_finalize()

    def _get_metadata(self, book_id):
        db = self.gui.current_db
        oldmi = db.get_metadata(book_id, index_is_id=True,
                                get_cover=True, cover_as_data=True)
        opf, cov = self._book_paths.get(book_id, (None, None))
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

    def _open_review(self, group_ids):
        from calibre.gui2.metadata.diff import CompareMany
        db = self.gui.current_db
        d = CompareMany(
            set(group_ids), self._get_metadata, db.field_metadata,
            parent=self.gui,
            window_title='Revisar metadatos dudosos',
            reject_button_tooltip='Descartar los metadatos descargados de este libro',
            accept_all_tooltip='Usar los metadatos descargados para todos los restantes',
            reject_all_tooltip='Descartar los metadatos descargados de todos los restantes',
            revert_tooltip='Descartar el valor descargado de: %s',
            intro_msg=('Estos son los DUDOSOS (los seguros se van aplicando '
                       'aparte). A la izquierda lo descargado, a la derecha lo '
                       'original. Si un valor descargado esta vacio, se conserva '
                       'el original. Si llegan mas dudosos mientras revisas, se '
                       'van anadiendo a esta misma ventana. Lo que revises se '
                       'aplica al cerrar. Si cierras la ventana (Cancelar) sin '
                       'terminar, lo que quede sin revisar NO se pierde: se '
                       'aplica lo confirmado y la revision se reabre con el '
                       'resto para continuar. Para descartarlos, usa "Rechazar '
                       'todos los restantes".'),
            action_button=('&Ver libro', 'view.png',
                           self.gui.iactions['View'].view_historical),
            db=db)
        self._review_dialog = d
        self._dialog_ids = set(group_ids)
        # Se puede inyectar en caliente solo si el dialogo expone ids/total Y
        # arranco en modo multiple (con 1 solo item Calibre no crea los botones
        # de navegacion, asi que ese caso preferimos abrir dialogo nuevo).
        self._can_inject = (hasattr(d, 'ids') and hasattr(d, 'total')
                            and getattr(d, 'total', 0) > 1)
        try:
            # Accepted: termino la lista, "aceptar todos" o "rechazar todos los
            # restantes" (en los tres, accepted_map cubre TODO el grupo).
            # Rejected: cerro la ventana (X / Cancelar) -> solo trae lo revisado.
            accepted = (d.exec() == QDialog.DialogCode.Accepted)
        finally:
            self._review_dialog = None
            self._can_inject = False
        # Cosecha lo YA revisado, se cierre como se cierre. 'accepted_map'
        # (calibre reciente) vs 'accepted' (calibre 9.x).
        acc = getattr(d, 'accepted_map', None)
        if acc is None:
            acc = getattr(d, 'accepted', None)
        acc = acc or {}
        reviewed = set()
        for book_id, val in acc.items():
            reviewed.add(book_id)
            try:
                changed, mi = val
            except Exception:
                continue
            if mi is None:  # descartado por el usuario
                self._agg['rejected'] += 1
                continue
            opf, cov = self._book_paths.get(book_id, (None, None))
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
            self._to_apply[book_id] = (opf, cov)
        # Los que estaban en el dialogo pero NO se revisaron (ventana cerrada
        # a medias con Cancelar).
        not_reviewed = self._dialog_ids - reviewed
        self._dialog_ids = set()
        if not_reviewed:
            if not accepted:
                # Cierre a medias (Cancelar): lo no revisado NO se pierde. Se
                # reencola (al frente) y se pausa el pump para aplicar antes lo
                # confirmado; despues la revision se REABRE con lo reencolado
                # (la reabre _on_applied, o el propio pump si no habia nada que
                # aplicar). Para descartar el resto, "Rechazar todos los
                # restantes" (cierra como Accepted, no pasa por aqui).
                self._pending_ids = list(not_reviewed) + self._pending_ids
                self._review_paused = True
            else:
                # Cierre Accepted que no cubre a todos (no deberia pasar:
                # aceptar/rechazar todos cubren el grupo). Por seguridad, sin
                # revisar.
                self._agg['unreviewed'] += len(not_reviewed)

    # --- aplicacion progresiva ---------------------------------------------
    def _flush_apply(self):
        """Escribe en la biblioteca lo acumulado hasta ahora. Solo en momentos
        seguros: sin dialogo de revision abierto y sin otra aplicacion en curso
        (el pump garantiza ambas cosas antes de llamar aqui)."""
        if self._apply_in_flight or self._review_dialog is not None:
            return
        if not self._to_apply:
            return
        batch = self._to_apply
        self._to_apply = {}
        self._apply_in_flight = True
        self._agg['applied'] += len(batch)
        em = self.gui.iactions['Edit Metadata']
        em.apply_metadata_changes(
            batch, merge_comments=msprefs['append_comments'],
            icon='download-metadata.png', callback=self._on_applied)

    def _on_applied(self, applied_ids):
        self._apply_in_flight = False
        # Ya se aplico lo confirmado. Si un cierre a medias dejo dudosos
        # reencolados, se levanta la pausa para reabrir la revision con ellos.
        self._review_paused = False
        self._kick()

    # --- cierre ------------------------------------------------------------
    def _maybe_finalize(self):
        if self._finalized:
            return
        if self._review_dialog is not None or self._pending_ids:
            return
        if not self._dl_done:
            return
        if self._apply_in_flight:
            return
        if self._to_apply:
            # Aun queda algo por escribir: aplicarlo; _on_applied volvera aqui.
            self._flush_apply()
            return
        self._finalized = True
        self._finish()

    def _finish(self):
        self._pipeline_active = False
        self._cleanup_all()
        info_dialog(self.gui, 'Smart Metadata completado',
                    self._summary(), show=True)

    # --- utilidades --------------------------------------------------------
    def _summary(self):
        head = ''
        if self._nchunks > 1:
            head = ('Procesados %d libros en %d rondas.\n\n'
                    % (self._total_books, self._nchunks))
        rescued = len(self._fb_titles) - len(
            [b for b in self._fb_titles if b in self._failed_ids])
        return head + (
            'Aplicados automaticamente (seguros): %d\n'
            'Enviados a revision (dudosos): %d\n'
            'Rechazados en revision: %d\n'
            'Sin revisar (revision cerrada a medias): %d\n'
            'Total aplicado a la biblioteca: %d\n'
            'Rescatados por el campo de fallback: %d\n'
            'Sin resultado (metadatos): %d'
            % (self._agg['auto'], self._agg['review'], self._agg['rejected'],
               self._agg['unreviewed'], self._agg['applied'], rescued,
               len(self._failed_ids)))

    def _cleanup_all(self):
        for t in self._active_tdirs:
            try:
                shutil.rmtree(t, ignore_errors=True)
            except Exception:
                pass
        self._active_tdirs = []
