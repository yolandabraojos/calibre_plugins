from __future__ import unicode_literals, division, absolute_import, print_function

__license__ = 'GPL v3'

import os
import logging

try:
    from qt.core import QAction, QMessageBox
except ImportError:
    from PyQt5.Qt import QAction, QMessageBox

from calibre.gui2 import Dispatcher
from calibre.gui2.actions import InterfaceAction
from calibre_plugins.all_libraries_stats.config import get_library_config, KEY_LIBRARIES_PATH, KEY_LIBRARY_FIELD, KEY_TOTAL_BOOKS_FIELD, KEY_DUPLICATE_TITLES_FIELD
from calibre_plugins.all_libraries_stats.jobs import run_unified_analysis_threaded

logger = logging.getLogger('all_libraries_stats.action')

def _(s): return s

# IMPORTANTE: Importamos la función inyectada por Calibre para extraer el icono
try:
    from calibre_plugins.all_libraries_stats import get_icons
except ImportError:
    get_icons = None


class AllLibrariesStatsAction(InterfaceAction):
    # Aquí ya tenías el icono en None correctamente, así que forzará la carga manual
    action_spec = (_('Libraries Stats'), None, _('Analyze author statistics across all configured libraries'), None)
    action_type = 'current'

    def genesis(self):
        print("[DEBUG-ALS] Inicializando Plugin y cargando interfaz...")

        # --- CARGA MANUAL DEL ICONO PRINCIPAL ---
        if get_icons:
            try:
                # OJO: Asegúrate de que el archivo se llame 'icon.png' y esté en la carpeta 'images'.
                # Si se llama distinto (ej. 'plugin.png'), cámbialo en la línea de abajo.
                icono = get_icons('images/icon.png')
                self.qaction.setIcon(icono)
                print("[DEBUG-ALS] Icono principal cargado correctamente.")
            except Exception as e:
                print(f"[DEBUG-ALS] ERROR: No se pudo cargar el icono principal - {e}")
        else:
            print("[DEBUG-ALS] ADVERTENCIA: No se pudo importar la función get_icons.")
        # ----------------------------------------

        self.qaction.triggered.connect(self.run_action)

    def load_config(self): pass
    def location_chosen(self, loc): pass

    def run_action(self, *args):
        print("[DEBUG-ALS] ------------- INICIANDO run_action -------------")
        try:
            db = self.gui.current_db
            prefs = get_library_config(db)
            
            paths_str = prefs.get(KEY_LIBRARIES_PATH, '')
            library_field = prefs.get(KEY_LIBRARY_FIELD, '')
            total_books_field = prefs.get(KEY_TOTAL_BOOKS_FIELD, '')
            duplicate_titles_field = prefs.get(KEY_DUPLICATE_TITLES_FIELD, '')

            if not paths_str:
                print("[DEBUG-ALS] Error: Rutas no configuradas.")
                QMessageBox.warning(self.gui, _('Configuración incompleta'), _('Por favor, configura las rutas de las bibliotecas primero.'))
                return

            cache = db.new_api
            available_cols = list(cache.field_metadata.keys())

            def clean_field(f):
                if not f or str(f).strip() == '': return None
                f = str(f).strip().lower()
                return f if f.startswith('#') else '#' + f

            self.l_f = clean_field(library_field)
            self.t_f = clean_field(total_books_field)
            self.d_f = clean_field(duplicate_titles_field)

            missing = []
            if self.l_f and self.l_f not in available_cols: missing.append(f"- Librería: {self.l_f}")
            if self.t_f and self.t_f not in available_cols: missing.append(f"- Total Libros: {self.t_f}")
            if self.d_f and self.d_f not in available_cols: missing.append(f"- Duplicados: {self.d_f}")

            if missing:
                print(f"[DEBUG-ALS] Faltan columnas: {missing}")
                QMessageBox.critical(self.gui, _('Columnas no encontradas'), 
                    _('Las siguientes columnas configuradas NO existen en tu Calibre:\n' + '\n'.join(missing)))
                return
            
            libraries_paths = paths_str if isinstance(paths_str, list) else [p.strip() for p in paths_str.replace('\n', ',').split(',') if p.strip()]
            
            # --- EXTRACCIÓN DE DATOS ---
            print("[DEBUG-ALS] Extrayendo metadatos base a memoria pura (Hilo Principal)...")
            all_book_ids = list(cache.all_book_ids()) 
            fm_lib = cache.field_metadata.get(self.l_f, {}) if self.l_f else {}
            fm_tot = cache.field_metadata.get(self.t_f, {}) if self.t_f else {}
            fm_dup = cache.field_metadata.get(self.d_f, {}) if self.d_f else {}

            field_meta = {
                'lib': {'is_multiple': bool(fm_lib.get('is_multiple', False))} if fm_lib else {},
                'tot': {'datatype': str(fm_tot.get('datatype', ''))} if fm_tot else {},
                'dup': {'is_multiple': bool(fm_dup.get('is_multiple', False))} if fm_dup else {}
            }
            
            books_data = {}
            for bid in all_book_ids:
                a_raw = cache.field_for('authors', bid)
                t_raw = cache.field_for('title', bid)
                books_data[bid] = {
                    'authors': [str(a) for a in a_raw] if a_raw else [],
                    'title': str(t_raw) if t_raw else ""
                }

            # DETECCIÓN DE LA LIBRERÍA ACTUAL
            current_library_name = os.path.basename(db.library_path)
            print(f"[DEBUG-ALS] Librería actual detectada: {current_library_name}")

            print("[DEBUG-ALS] Extracción completa. Lanzando Job en segundo plano...")
            self.gui.status_bar.show_message(_('Analizando librerías en segundo plano...'), 3000)
            
            run_unified_analysis_threaded(self.gui, libraries_paths, books_data, field_meta, all_book_ids, current_library_name, Dispatcher(self.on_job_complete))
            
        except Exception as e:
            print(f"[DEBUG-ALS] EXCEPCIÓN CRÍTICA en run_action: {e}")
            QMessageBox.critical(self.gui, _('Error'), f'Excepción crítica en preparación: {e}')

    def on_job_complete(self, job):
        print("[DEBUG-ALS] [CALLBACK] on_job_complete ejecutado de forma SEGURA en el Hilo Principal.")
        if job.failed or not job.result.get('success'): 
            err = job.exception if job.failed else job.result.get('error')
            print(f"[DEBUG-ALS] [CALLBACK] Error en el Job: {err}")
            QMessageBox.critical(self.gui, _('Error en el proceso'), _(f'Fallo durante el análisis:\n{err}'))
            return
        
        res = job.result
        cache = self.gui.current_db.new_api

        try:
            print("[DEBUG-ALS] [CALLBACK] Inyectando datos en Calibre...")
            if self.l_f and res.get('lib_updates'): cache.set_field(self.l_f, res['lib_updates'])
            if self.t_f and res.get('total_updates'): cache.set_field(self.t_f, res['total_updates'])
            if self.d_f and res.get('dup_updates'): cache.set_field(self.d_f, res['dup_updates'])
            print("[DEBUG-ALS] [CALLBACK] Inyección completada con éxito.")
        except Exception as e:
            print(f"[DEBUG-ALS] [CALLBACK] Error al inyectar en BD: {e}")
            QMessageBox.critical(self.gui, _('Error Crítico'), _(f'Fallo al escribir en la base de datos:\n{e}'))
            return

        self.gui.library_view.model().refresh_ids(list(cache.all_book_ids()))
        
        message = _('Análisis y actualización completados.\n\nLibrerías encontradas: {}\nAutores analizados: {}\nLibros actualizados: {} de {}').format(
            res['lib_count'], res['auth_count'], res['processed'], res['total']
        )
        QMessageBox.information(self.gui, _('Éxito'), message)