# -*- coding: utf-8 -*-
from __future__ import unicode_literals, division, absolute_import, print_function

__license__ = 'GPL v3'

import pkgutil
import traceback
from calibre.gui2.actions import InterfaceAction
from calibre.gui2 import Dispatcher, error_dialog, question_dialog
from qt.core import QIcon, QMenu, QAction, QPixmap, Qt

from calibre_plugins.book_classifier.config import (
    prefs, list_profiles, get_active_profile_name, apply_profile)
from calibre_plugins.book_classifier.ml_jobs import (
    plan_classify_chunks, run_classify_chunk_task, run_author_fallback_task,
    apply_ml_writes)
from calibre.gui2.threaded_jobs import ThreadedJob
from calibre_plugins.book_classifier.llm_jobs import (
    select_rescue_candidates, plan_rescue_chunks, run_rescue_batch_task,
    build_donor_index, resolve_from_index)

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

        act_coher = QAction('Revisar coherencia entre copias...', self.gui)
        act_coher.triggered.connect(self._method_coherence)
        menu.addAction(act_coher)

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

        # Cambia el perfil de IA (proveedor/clave/modelo/URL) activo sin
        # abrir el dialogo de configuracion. El submenu se reconstruye cada
        # vez que se abre para reflejar altas/bajas/cambios hechos en el
        # dialogo desde la ultima vez.
        self.sub_llm_profiles = QMenu('Perfil de IA activo', self.gui)
        menu.addMenu(self.sub_llm_profiles)
        menu.aboutToShow.connect(self._refresh_llm_profile_menu)

        menu.addSeparator()

        act_config = QAction('Configurar plugin...', self.gui)
        act_config.triggered.connect(self.show_config)
        menu.addAction(act_config)

        self.qaction.triggered.connect(lambda: self._method_ml(all_books=False))
        print("DEBUG: Plugin Book Classifier (IA) listo.")

    # ─── Perfiles de IA ──────────────────────────────────────────────────────

    def _refresh_llm_profile_menu(self):
        self.sub_llm_profiles.clear()
        try:
            profiles = list_profiles()
            active = get_active_profile_name()
        except Exception:
            profiles, active = [], ''
        if not profiles:
            act = QAction('(sin perfiles guardados)', self.gui)
            act.setEnabled(False)
            self.sub_llm_profiles.addAction(act)
            return
        for p in profiles:
            pname = p.get('name', '')
            label = pname
            if p.get('model'):
                label = '{}  [{}]'.format(pname, p['model'])
            act = QAction(label, self.gui)
            act.setCheckable(True)
            act.setChecked(pname == active)
            act.triggered.connect(lambda checked, n=pname: self._switch_llm_profile(n))
            self.sub_llm_profiles.addAction(act)

    def _switch_llm_profile(self, name):
        if apply_profile(name):
            self.gui.status_bar.show_message(
                'Perfil de IA activo: {}'.format(name), 4000)

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
                # Nivel de promocion: lee (nunca escribe) el campo dedicado de
                # la IA en la nube; si su confianza es muy alta, se usa como
                # clasificacion (ver ml_jobs.run_classify_chunk_task).
                'llm_library_field':   prefs.get('llm_library_field', '#libreria_ia'),
                'llm_library_prefix':  prefs.get('llm_library_prefix', 'Biblioteca IA: '),
                'llm_conf_field':      prefs.get('llm_conf_field', '#confianza_ia'),
                'llm_promote_enabled':   prefs.get('llm_promote_enabled', True),
                'llm_promote_threshold': prefs.get('llm_promote_threshold', 0.90),
                # Promocion del OTRO eje: los temas de la IA sustituyen a los
                # del motor local (solo se LEE su campo, nunca se escribe).
                'llm_temas_field':   prefs.get('llm_temas_field', '#temas_ia'),
                'llm_temas_prefix':  prefs.get('llm_temas_prefix', 'Tema IA: '),
                'llm_promote_temas_enabled': prefs.get('llm_promote_temas_enabled', True),
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
                'temas_promovidos': 0,
                'promocion_nombre_invalido': 0, 'promocion_nombres': {},
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
        if settings.get('llm_promote_enabled'):
            checks.append((settings.get('llm_library_field'), 'libreria IA (promocion)'))
            checks.append((settings.get('llm_conf_field'), 'confianza IA (promocion)'))
        if settings.get('llm_promote_temas_enabled'):
            checks.append((settings.get('llm_temas_field'), 'temas IA (promocion)'))
            checks.append((settings.get('llm_conf_field'), 'confianza IA (promocion)'))
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
                    run['temas_promovidos'] = run.get('temas_promovidos', 0) \
                        + result.get('temas_promovidos', 0)
                    run['promocion_nombre_invalido'] = \
                        run.get('promocion_nombre_invalido', 0) \
                        + result.get('promocion_nombre_invalido', 0)
                    for k, v in (result.get('promocion_nombres') or {}).items():
                        run['promocion_nombres'][k] = \
                            run['promocion_nombres'].get(k, 0) + v
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
            ]
            if stats.get('temas_promovidos'):
                lines.append(
                    'Temas tomados de la IA: {} (sustituyen a los detectados por '
                    'regex en esos libros)'.format(stats['temas_promovidos']))
            if stats.get('promocion_nombre_invalido'):
                malos = stats.get('promocion_nombres') or {}
                top = sorted(malos, key=lambda k: -malos[k])[:4]
                lines.append(
                    'Promociones rechazadas: {} (la libreria guardada por la IA ya '
                    'no esta en el catalogo{}). Vuelve a pasar el rescate con IA '
                    'por esos libros.'.format(
                        stats['promocion_nombre_invalido'],
                        ': ' + ', '.join('"{}" x{}'.format(n, malos[n]) for n in top)
                        if top else ''))
            lines += [
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
        # Campo DEDICADO de la libreria IA (destino real del rescate, ver
        # llm_jobs.run_rescue_batch_task): hace falta su valor previo para que
        # el merge no pierda datos si overwrite=False.
        llm_lib_field = settings.get('llm_library_field') or ''
        # Campo PROPIO de los temas de la IA (3.9.0): tambien hace falta su
        # valor previo para que el merge no pierda datos.
        llm_temas_field = (settings.get('llm_temas_field') or '').strip()
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
            if llm_lib_field:
                prev[llm_lib_field] = _fval(llm_lib_field)
            if llm_temas_field and llm_temas_field not in prev:
                prev[llm_temas_field] = _fval(llm_temas_field)
            idioma = ','.join(sorted(str(x) for x in languages))
            books.append({'id': bid, 'title': title, 'authors': authors,
                          'comments': comments, 'tags': tags, 'idioma': idioma,
                          'lib_value': lib_value, 'prev': prev})
        return books

    def _prefetch_donor_index(self, settings):
        """Indice de donantes a partir de las filas de la biblioteca."""
        return build_donor_index(self._prefetch_library_rows(settings))

    def _prefetch_library_rows(self, settings):
        """Lee TODA la biblioteca -en el hilo de la GUI, como _prefetch_books-
        para saber que titulo+autor YA tiene libreria y no volver a
        preguntarselo al LLM. Las mismas filas alimentan el informe de
        coherencia entre copias (coherence.py).

        Lectura EN LOTE con `all_field_for` (un diccionario por campo), no
        libro a libro: con `field_for` por libro esto tardaria mas que el
        propio rescate. Si la API no lo soporta, se cae a field_for.

        Donantes de dos origenes, con distinta consecuencia:
          - `llm_library_field`: es la respuesta previa de la IA; se copia con
            su % de confianza, su motivo y su serie.
          - `library_field` (clasificador local): tambien vale como respuesta,
            pero se copia SIN confianza a proposito. El nivel de promocion de
            ml_jobs solo asciende un valor de la IA si su confianza supera el
            umbral, asi que sin confianza no puede cerrarse el bucle
            local -> campo IA -> promocion al campo local.
        """
        db = self.gui.current_db.new_api
        lib_field   = settings.get('library_field', 'tags')
        mood_field  = settings.get('mood_field', 'tags')
        lib_prefix  = settings.get('library_prefix', 'Biblioteca: ')
        mood_prefix = settings.get('mood_prefix', 'Tema: ')
        llm_field   = (settings.get('llm_library_field') or '').strip()
        llm_prefix  = settings.get('llm_library_prefix', 'Biblioteca IA: ')
        conf_field  = ((settings.get('llm_conf_field') or '').strip()
                       if settings.get('llm_write_conf', True) else '')
        serie_field = ((settings.get('llm_serie_field') or '').strip()
                       if settings.get('llm_write_serie', True) else '')
        reason_field = ((settings.get('llm_reason_field') or '').strip()
                        if settings.get('llm_write_reason', True) else '')
        try:
            valid = set(db.field_metadata.all_field_keys())
            ids = list(db.all_book_ids())
        except Exception:
            traceback.print_exc()
            return {}
        if not ids:
            return {}

        cache = {}

        def bulk(field):
            if not field or field not in valid:
                return {}
            if field in cache:
                return cache[field]
            try:
                vals = dict(db.all_field_for(field, ids))
            except Exception:
                vals = {}
                for bid in ids:
                    try:
                        vals[bid] = db.field_for(field, bid)
                    except Exception:
                        pass
            cache[field] = vals
            return vals

        titles  = bulk('title')
        authors = bulk('authors')
        langs   = bulk('languages')
        v_llm   = bulk(llm_field) if llm_field else {}
        v_ml    = bulk(lib_field)
        v_mood  = bulk(mood_field)
        v_conf  = bulk(conf_field) if conf_field else {}
        v_serie = bulk(serie_field) if serie_field else {}
        v_reason = bulk(reason_field) if reason_field else {}

        def one(vals, field, prefix, bid):
            """Valor SIN prefijo (el que se vuelve a escribir lo re-anade)."""
            v = vals.get(bid)
            if field != 'tags' and not prefix and isinstance(v, (list, tuple)):
                # Columna PROPIA multivalor: sin prefijo porque todo lo que hay
                # es del plugin. Buscar una marca aqui devolvia None y el
                # indice de donantes se quedaba sin el dato.
                return next((str(t).strip() for t in (v or []) if str(t).strip()), None)
            if field == 'tags' or isinstance(v, (list, tuple)):
                for t in (v or []):
                    t = str(t)
                    if prefix and t.startswith(prefix):
                        return t[len(prefix):].strip()
                return None
            if v is None:
                return None
            v = str(v).strip()
            return v or None

        def many(vals, field, prefix, bid):
            v = vals.get(bid)
            if field != 'tags' and not prefix and isinstance(v, (list, tuple)):
                # Idem que en one(): columna propia -> valen todos los valores.
                # Devolver [] dejaba SIN TEMAS a las copias resueltas por el
                # indice cuando el campo de temas no es 'tags'.
                return [str(t).strip() for t in (v or []) if str(t).strip()]
            if field == 'tags' or isinstance(v, (list, tuple)):
                if not prefix:
                    return []
                return [str(t)[len(prefix):].strip() for t in (v or [])
                        if str(t).startswith(prefix)]
            return [str(v).strip()] if v else []

        llm_prefix_eff  = llm_prefix if llm_field == 'tags' else ''
        lib_prefix_eff  = lib_prefix if lib_field == 'tags' else ''
        mood_prefix_eff = mood_prefix if mood_field == 'tags' else ''

        rows = []
        for bid in ids:
            de_ia = True
            lib = one(v_llm, llm_field, llm_prefix_eff, bid) if llm_field else None
            if not lib:
                de_ia = False
                lib = one(v_ml, lib_field, lib_prefix_eff, bid)
            temas = many(v_mood, mood_field, mood_prefix_eff, bid)
            if not lib and not temas:
                continue
            conf = None
            if de_ia and conf_field:
                try:
                    raw = v_conf.get(bid)
                    conf = int(raw) if raw is not None else None
                except (TypeError, ValueError):
                    conf = None
            langv = langs.get(bid) or []
            rows.append({
                'id': bid,
                'title': titles.get(bid) or '',
                'authors': list(authors.get(bid) or []),
                'idioma': ','.join(sorted(str(x) for x in langv)),
                'libreria': lib,
                'temas': temas,
                'origen': 'ia' if (lib and de_ia) else 'local',
                'conf_pct': conf,
                'serie': (one(v_serie, serie_field, '', bid)
                          if (de_ia and serie_field) else None),
                # El razonamiento original solo tiene sentido si el donante
                # viene de la IA: el clasificador local no escribe motivo.
                # resolve_from_index lo copia junto con la clasificacion
                # cuando otra copia se resuelve por este indice.
                'motivo': (one(v_reason, reason_field, '', bid)
                           if (de_ia and reason_field) else None),
            })
        return rows

    # --- Coherencia entre copias -----------------------------------------

    def _method_coherence(self):
        """Informe de copias del mismo titulo+autor con clasificaciones que se
        contradicen. Solo LEE: nada se escribe salvo que se pulse el boton de
        unificar temas."""
        from calibre_plugins.book_classifier import coherence
        try:
            settings = {
                'library_field':  prefs.get('ml_library_field', 'tags'),
                'mood_field':     prefs.get('ml_mood_field', 'tags'),
                'library_prefix': prefs.get('ml_library_prefix', 'Biblioteca: '),
                'mood_prefix':    prefs.get('ml_mood_prefix', 'Tema: '),
                'llm_library_field':  prefs.get('llm_library_field', '#libreria_ia'),
                'llm_library_prefix': prefs.get('llm_library_prefix', 'Biblioteca IA: '),
                'llm_conf_field':  prefs.get('llm_conf_field', '#confianza_ia'),
                'llm_serie_field': prefs.get('llm_serie_field', '#serie_ia'),
                'llm_write_conf':  prefs.get('llm_write_conf', True),
                'llm_write_serie': prefs.get('llm_write_serie', True),
            }
            rows = self._prefetch_library_rows(settings)
            if not rows:
                error_dialog(self.gui, 'Nada que revisar',
                             'No hay ningun libro con libreria o temas del '
                             'plugin en esta biblioteca.', show=True)
                return
            rep = coherence.analyze(rows)
            try:
                lib_name = self.gui.current_db.library_path
            except Exception:
                lib_name = ''
            html = coherence.render_html(rep, biblioteca=lib_name)
            self._show_coherence_results(rep, html, settings)
        except Exception:
            print("DEBUG ERROR en _method_coherence:")
            traceback.print_exc()
            error_dialog(self.gui, 'Error',
                         'No se pudo generar el informe de coherencia. Mira la '
                         'consola de calibre para el detalle.', show=True)

    def _show_coherence_results(self, rep, html, settings):
        from qt.core import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QDialogButtonBox, Qt)
        from calibre_plugins.book_classifier import coherence

        dialog = QDialog(self.gui)
        dialog.setWindowTitle('Coherencia entre copias')
        layout = QVBoxLayout(dialog)
        n_uni = len(coherence.unify_moods_writes(rep['mood_incomplete']))
        lbl = QLabel(
            'Libros analizados:            {}\n'
            'Titulos con mas de una copia: {}\n\n'
            'Contradicciones de libreria:  {}   (una de las copias esta mal)\n'
            'Contradicciones de temas:     {}   (conjuntos incompatibles)\n'
            'Grupos con temas incompletos: {}   ({} copias se pueden unificar)\n'
            'Clasificados sin ningun tema: {}'.format(
                rep['total_books'], rep['total_groups'],
                len(rep['lib_conflicts']), len(rep['mood_conflicts']),
                len(rep['mood_incomplete']), n_uni, rep['no_moods_total']))
        lbl.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(lbl)

        nota = QLabel(
            'Las contradicciones hay que resolverlas a mano: el informe trae '
            'una busqueda "id:..." por grupo para verlas en calibre. Los temas '
            'incompletos no requieren decidir nada -unos son subconjunto de '
            'otros-, asi que se pueden unificar con la union de golpe.')
        nota.setWordWrap(True)
        layout.addWidget(nota)

        row = QHBoxLayout()
        btn_html = QPushButton('Ver informe completo')
        btn_html.clicked.connect(lambda: self._open_coherence_report(html))
        row.addWidget(btn_html)
        btn_uni = QPushButton('Unificar temas incompletos ({})'.format(n_uni))
        btn_uni.setEnabled(bool(n_uni))
        btn_uni.clicked.connect(
            lambda: self._unify_moods(rep['mood_incomplete'], settings, btn_uni))
        row.addWidget(btn_uni)
        layout.addLayout(row)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(dialog.reject)
        btns.accepted.connect(dialog.accept)
        layout.addWidget(btns)
        dialog.resize(600, 330)
        dialog.exec()

    def _open_coherence_report(self, html):
        try:
            from calibre.ptempfile import PersistentTemporaryFile
            from calibre.gui2 import open_local_file
            tf = PersistentTemporaryFile('_coherencia.html')
            tf.write(html.encode('utf-8'))
            tf.close()
            open_local_file(tf.name)
        except Exception:
            print("DEBUG ERROR al abrir el informe de coherencia:")
            traceback.print_exc()

    def _unify_moods(self, entries, settings, button=None):
        """Aplica la UNION de temas a los grupos incompletos. Solo toca los
        casos en que unos temas son subconjunto de otros: no decide nada."""
        from calibre_plugins.book_classifier import coherence
        from calibre_plugins.book_classifier.ml_jobs import _merge_prefixed
        try:
            pend = coherence.unify_moods_writes(entries)
            if not pend:
                return
            if not question_dialog(
                    self.gui, 'Confirmar',
                    'Se van a unificar los temas de {} libros con la union de '
                    'los temas de sus copias. Los demas campos no se tocan. '
                    '¿Continuar?'.format(len(pend))):
                return
            db = self.gui.current_db.new_api
            mood_field = settings.get('mood_field', 'tags')
            mood_prefix = settings.get('mood_prefix', 'Tema: ')
            pref_eff = mood_prefix if mood_field == 'tags' else ''
            writes = {}
            for bid, temas in pend.items():
                try:
                    prev = db.field_for(mood_field, bid)
                except Exception:
                    prev = None
                writes[bid] = _merge_prefixed(
                    [pref_eff + t for t in temas], prev, mood_field,
                    [pref_eff], True)
            apply_ml_writes(self.gui, {mood_field: writes})
            if button is not None:
                button.setEnabled(False)
                button.setText('Unificados {}'.format(len(writes)))
        except Exception:
            print("DEBUG ERROR en _unify_moods:")
            traceback.print_exc()

    def _apply_llm_writes(self, result, settings):
        """Aplica a la BD las escrituras de un resultado de rescate -venga del
        job del LLM o de la resolucion por indice-."""
        if result.get('writes_by_field'):
            apply_ml_writes(self.gui, result['writes_by_field'])
        reason_field = (settings.get('llm_reason_field')
                        if settings.get('llm_write_reason', True) else None)
        if result.get('reason_writes') and reason_field:
            self._apply_reason_writes(reason_field, result['reason_writes'])
        serie_field = (settings.get('llm_serie_field')
                       if settings.get('llm_write_serie', True) else None)
        if result.get('serie_writes') and serie_field:
            self._apply_custom_writes(serie_field, result['serie_writes'],
                                      'la serie detectada por la IA', 'texto')
        conf_field = (settings.get('llm_conf_field')
                      if settings.get('llm_write_conf', True) else None)
        if result.get('conf_writes') and conf_field:
            self._apply_custom_writes(conf_field, result['conf_writes'],
                                      'el % de confianza de la IA',
                                      'entero (numero)')

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
                'llm_base_url':   prefs.get('llm_base_url', ''),
                'llm_batch':      prefs.get('llm_batch', 20),
                'llm_batch_tolerancia': prefs.get('llm_batch_tolerancia', 0.25),
                'llm_min_conf':   prefs.get('llm_min_conf', 0.55),
                'llm_write_temas': prefs.get('llm_write_temas', True),
                'llm_write_reason': prefs.get('llm_write_reason', True),
                'llm_reason_field': prefs.get('llm_reason_field', '#motivo_ia'),
                'llm_write_serie': prefs.get('llm_write_serie', True),
                'llm_serie_field': prefs.get('llm_serie_field', '#serie_ia'),
                'llm_write_conf':  prefs.get('llm_write_conf', True),
                'llm_conf_field':  prefs.get('llm_conf_field', '#confianza_ia'),
                # Campo DEDICADO de la IA: el rescate escribe AQUI (nunca en
                # 'library_field', el campo principal de la clasificacion local).
                'llm_library_field':  prefs.get('llm_library_field', '#libreria_ia'),
                'llm_library_prefix': prefs.get('llm_library_prefix', 'Biblioteca IA: '),
                # Idem para los TEMAS: columna propia, separada de la del motor
                # local ('mood_field'). Vacia = comportamiento anterior.
                'llm_temas_field':  prefs.get('llm_temas_field', '#temas_ia'),
                'llm_temas_prefix': prefs.get('llm_temas_prefix', 'Tema IA: '),
                'force_all':       force,
            }

            # Columnas PROPIAS del rescate: deben existir ANTES de gastar
            # llamadas a la IA, o el resultado se perderia al escribir.
            a_comprobar = [(settings.get('llm_library_field'),
                            'la libreria detectada por la IA')]
            if settings.get('llm_write_temas', True):
                a_comprobar.append((settings.get('llm_temas_field'),
                                    'los temas detectados por la IA'))
            try:
                valid = set(self.gui.current_db.new_api.field_metadata.all_field_keys())
            except Exception:
                valid = None
            for campo, uso in a_comprobar:
                campo = (campo or '').strip()
                if not campo or campo == 'tags' or valid is None:
                    continue
                if campo not in valid:
                    error_dialog(
                        self.gui, 'Columna no encontrada',
                        'La columna configurada para {} ({}) no existe en esta '
                        'biblioteca.\n\nCreala (Preferencias -> Anadir columnas '
                        'personalizadas) o corrige la configuracion del plugin '
                        'antes de rescatar.'.format(uso, campo), show=True)
                    return

            books = self._prefetch_books(book_ids, settings)

            # Filtra los candidatos ANTES de lanzar nada (rapido, sin red) y
            # reparte el rescate en VARIOS jobs (en vez de uno solo con todos
            # los libros): cada job es UNA llamada a la IA y aplica sus
            # cambios en cuanto termina, sin esperar a que acabe el resto.
            cand, diag = select_rescue_candidates(books, settings)

            # Antes de gastar una sola llamada: los candidatos cuyo titulo y
            # autor YA estan clasificados en esta biblioteca -otra copia del
            # mismo libro- se resuelven copiando esa respuesta. El indice solo
            # se construye si queda algo que preguntar.
            donors = self._prefetch_donor_index(settings) if cand else {}
            cand, idx_res = resolve_from_index(cand, donors, settings)
            from_index = idx_res.get('from_index', 0)
            if from_index:
                self._apply_llm_writes(idx_res, settings)

            if not cand:
                self._show_llm_results({
                    'candidates': from_index, 'total': len(books),
                    'cancelled': False,
                    'lib_field': settings.get('library_field', 'tags'),
                    'with_value': diag['with_value'], 'sample': diag['sample'],
                    'already_llm': diag.get('already_llm', 0),
                    'temas_sin_libreria': idx_res.get('temas_sin_libreria', 0),
                    'from_index': from_index,
                    'from_index_loose': idx_res.get('from_index_loose', 0),
                    'rescued': idx_res.get('rescued', 0),
                    'dist': dict(idx_res.get('dist', {})),
                    'book_details': list(idx_res.get('book_details', [])),
                    'provider': provider,
                    'model_used': '(no hizo falta llamar al modelo)',
                    'base_used': '-',
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
                'total': len(books), 'candidates': len(cand) + from_index,
                'rescued': idx_res.get('rescued', 0), 'errors': 0,
                'dist': dict(idx_res.get('dist', {})),
                'book_details': list(idx_res.get('book_details', []))[:400],
                'from_index': from_index,
                'from_index_loose': idx_res.get('from_index_loose', 0),
                'already_llm': diag.get('already_llm', 0),
                'temas_sin_libreria': idx_res.get('temas_sin_libreria', 0),
                'revisar_causes': {}, 'unknown_names': {},
                'tokens': {'in': 0, 'out': 0, 'cache': 0, 'llamadas': 0},
                'min_conf': settings.get('llm_min_conf', 0.55),
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
                         if diag.get('duplicates_saved') else '')
                        + (' ({} resueltos sin preguntar, ya clasificados en la '
                           'biblioteca)'.format(from_index) if from_index else '')
                        ), 6000)
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
                    self._apply_llm_writes(result, run['settings'])
                    run['rescued'] += result.get('rescued', 0)
                    run['errors']  += result.get('errors', 0)
                    run['temas_sin_libreria'] = run.get('temas_sin_libreria', 0) \
                        + result.get('temas_sin_libreria', 0)
                    for k, v in result.get('dist', {}).items():
                        run['dist'][k] = run['dist'].get(k, 0) + v
                    for clave in ('revisar_causes', 'unknown_names'):
                        for k, v in result.get(clave, {}).items():
                            run[clave][k] = run[clave].get(k, 0) + v
                    for k, v in (result.get('tokens') or {}).items():
                        run['tokens'][k] = run['tokens'].get(k, 0) + v
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
            if (candidates == 0 and not stats.get('from_index')
                    and not stats.get('cancelled')):
                dialog.resize(470, 210)
                msg = QLabel(
                    'No se encontraron libros sin clasificar entre los {} '
                    'revisados.\n\nEl rescate con IA solo actua sobre los libros '
                    'marcados como "[REVISAR]" o "(sin datos)". Clasifica primero '
                    'en local; el rescate se ocupa despues de los dudosos.'
                    .format(stats.get('total', 0))
                    + ('\n\n{} de ellos ya los habia clasificado la IA en una '
                       'pasada anterior (tienen valor en su campo dedicado), asi '
                       'que no se vuelven a enviar. Usa la reevaluacion forzada '
                       'si quieres repetirlos.'.format(stats.get('already_llm', 0))
                       if stats.get('already_llm') else ''))
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
            if stats.get('from_index'):
                lines.append(
                    'De ellos, sin preguntar: {} (otra copia del mismo titulo y '
                    'autor ya estaba clasificada{})'.format(
                        stats['from_index'],
                        '; {} por titulo sin subtitulo'.format(
                            stats['from_index_loose'])
                        if stats.get('from_index_loose') else ''))
            if stats.get('already_llm'):
                lines.append(
                    'Omitidos por ya rescatados: {} (reevaluacion forzada para '
                    'repetirlos)'.format(stats['already_llm']))
            if stats.get('temas_sin_libreria'):
                lines.append(
                    'Temas guardados sin libreria: {} (la IA no resolvio la '
                    'libreria, pero sus temas SI se guardan porque van a una '
                    'columna propia)'.format(stats['temas_sin_libreria']))
            causas = stats.get('revisar_causes', {})
            if causas:
                mc = stats.get('min_conf', 0.55)
                etiquetas = [
                    ('umbral', 'confianza por debajo del umbral ({:.0%})'.format(mc)),
                    ('declarado', 'la IA dice que no tiene base para decidir'),
                    ('nombre', 'nombre de libreria fuera del catalogo'),
                    ('sin_libreria', 'respuesta sin el campo libreria'),
                    ('sin_respuesta', 'el modelo no devolvio ese libro'),
                    ('otro', 'sin clasificar (causa desconocida)'),
                ]
                lines += ['', 'Sin resolver ({}), por que:'.format(
                    sum(causas.values()))]
                for clave, texto in etiquetas:
                    if causas.get(clave):
                        lines.append('   {:<4} {}'.format(causas[clave], texto))
                desconocidos = stats.get('unknown_names', {})
                if desconocidos:
                    top = sorted(desconocidos, key=lambda k: -desconocidos[k])[:6]
                    lines.append('        nombres no reconocidos: {}'.format(
                        ', '.join('"{}" x{}'.format(n, desconocidos[n]) for n in top)))
            tk = stats.get('tokens') or {}
            if tk.get('llamadas'):
                ent, cache = tk.get('in', 0), tk.get('cache', 0)
                pct = (100.0 * cache / ent) if ent else 0.0
                lines += ['', 'Consumo del modelo ({} llamada{}):'.format(
                    tk['llamadas'], '' if tk['llamadas'] == 1 else 's')]
                lines.append('   entrada {:,} tokens, de los que {:,} ({:.0f}%) '
                             'vinieron de la cache'.format(ent, cache, pct)
                             .replace(',', '.'))
                lines.append('   salida  {:,} tokens'.format(
                    tk.get('out', 0)).replace(',', '.'))
                if ent and pct < 5:
                    lines.append('   (la parte fija del prompt no se esta '
                                 'cacheando: se paga entera en cada lote)')
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