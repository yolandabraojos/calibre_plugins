from __future__ import unicode_literals, division, absolute_import, print_function

__license__ = 'GPL v3'

import logging
from calibre.gui2.threaded_jobs import ThreadedJob
from calibre_plugins.all_libraries_stats.analyzer import LibraryAnalyzer

logger = logging.getLogger('all_libraries_stats.jobs')

def _(s): return s

def run_unified_analysis_threaded(gui, libraries_paths, books_data, field_meta, all_book_ids, current_library_name, callback):
    print("[DEBUG-ALS] Configurando Unified ThreadedJob...")
    
    def run_task(libs_paths, b_data, f_meta, b_ids, curr_lib, log=None, abort=None, notifications=None):
        def dual_log(msg):
            if log: log(msg)
            logger.info(msg)
            
        dual_log("[DEBUG-ALS] [JOB] --- INICIANDO HILO SECUNDARIO ---")
        try:
            # === FASE 1: LECTURA EXTERNA ===
            all_libraries = []
            for lib_path in libs_paths:
                if abort and abort.is_set(): return {'success': False, 'error': 'Cancelado'}
                dual_log(f"[DEBUG-ALS] [JOB] Buscando bibliotecas en: {lib_path}")
                found = LibraryAnalyzer.find_libraries(lib_path)
                all_libraries.extend(found)

            if not all_libraries: 
                dual_log("[DEBUG-ALS] [JOB] No se encontraron bibliotecas.")
                return {'success': False, 'error': 'No se encontraron bibliotecas válidas.'}
            
            if notifications: notifications.put((0.1, _('Recopilando estadísticas de autores...')))
            author_stats = LibraryAnalyzer.collect_author_stats(all_libraries, dual_log)
            
            if notifications: notifications.put((0.3, _('Recopilando estadísticas de títulos...')))
            title_stats = LibraryAnalyzer.collect_title_stats(all_libraries, dual_log)
            
            # === FASE 2: CÁLCULO INTERNO ===
            dual_log("[DEBUG-ALS] [JOB] Pasando a la Fase de Cálculo Interno...")
            total_books = len(b_ids)
            processed_count = 0
            all_lib_updates, all_total_updates, all_dup_updates = {}, {}, {}

            if total_books > 0:
                for book_batch in LibraryAnalyzer.batch_iterator(b_ids, 100):
                    if abort and abort.is_set(): return {'success': False, 'error': 'Cancelado por el usuario'}
                    
                    lib_up, tot_up, dup_up = LibraryAnalyzer.calculate_metadata_updates(
                        b_data, f_meta, author_stats, title_stats, book_batch, curr_lib
                    )
                    
                    all_lib_updates.update(lib_up)
                    all_total_updates.update(tot_up)
                    all_dup_updates.update(dup_up)
                    processed_count += len(book_batch)
                    
                    progreso = 0.4 + (0.6 * (processed_count / total_books))
                    if notifications: notifications.put((progreso, _('Calculando {} de {} libros').format(processed_count, total_books)))
                    
            dual_log(f"[DEBUG-ALS] [JOB] --- TAREA FINALIZADA CON ÉXITO ({processed_count} libros) ---")
            return {
                'success': True,
                'lib_updates': all_lib_updates,
                'total_updates': all_total_updates,
                'dup_updates': all_dup_updates,
                'lib_count': len(all_libraries),
                'auth_count': len(author_stats),
                'processed': processed_count,
                'total': total_books
            }
            
        except Exception as e:
            dual_log(f"[DEBUG-ALS] [JOB] ERROR CRÍTICO: {e}")
            return {'success': False, 'error': str(e)}

    job = ThreadedJob('all_libs_unified_job', _('Analizando y Calculando Metadatos'), run_task, 
                      (libraries_paths, books_data, field_meta, all_book_ids, current_library_name), {}, callback)
    gui.job_manager.run_threaded_job(job)
    print("[DEBUG-ALS] Unified ThreadedJob enviado al Gestor de Tareas.")