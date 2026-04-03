from __future__ import unicode_literals, division, absolute_import, print_function

__license__   = 'GPL v3'
__copyright__ = '2026, Extract Metadata Plugin'

import logging

# Configuramos el logger para que use el mismo canal que el extractor
logger = logging.getLogger('EXTRACTOR_PLUGIN')

try:
    from calibre.gui2 import error_dialog, question_dialog, info_dialog, Dispatcher
    from calibre.gui2.actions import InterfaceAction
    from calibre.gui2.dialogs.message_box import ErrorNotification
    from calibre_plugins.extract_metadata.jobs import start_extract_threaded, get_job_details
    logger.debug("Imports de Calibre y módulos internos cargados correctamente en action.py")
except Exception as e:
    logger.error(f"Error cargando dependencias en action.py: {str(e)}")

# IMPORTANTE: Importamos la función inyectada por Calibre para extraer el icono
try:
    from calibre_plugins.extract_metadata import get_icons
except ImportError:
    get_icons = None

PLUGIN_ICONS = ['images/icon.png']

class ExtractMetadataAction(InterfaceAction):

    name = 'Extract Metadata'
    
    # CORRECCIÓN: Ponemos el icono en None para forzar la carga manual
    action_spec = ('Extract Metadata', None, 'Extract metadata from the selected book format', ())
    action_type = 'current'

    def genesis(self):
        logger.info("Inicializando Plugin: Extract Metadata")
        
        # --- CARGA MANUAL DEL ICONO PRINCIPAL ---
        if get_icons:
            try:
                icono = get_icons('images/icon.png')
                self.qaction.setIcon(icono)
                logger.debug("Icono cargado correctamente de forma manual.")
            except Exception as e:
                logger.error(f"No se pudo cargar el icono principal - {e}")
        else:
            logger.warning("No se pudo importar get_icons. El icono no se cargará.")
        # ----------------------------------------
        
        self.qaction.triggered.connect(self.extract_metadatas)

    def extract_metadatas(self):
        '''Acción principal para extraer metadatos'''
        logger.info("Acción disparada: Iniciando proceso de extracción")
        
        rows = self.gui.library_view.selectionModel().selectedRows()
        if not rows or len(rows) == 0:
            logger.warning("Intento de extracción sin libros seleccionados.")
            return error_dialog(self.gui, 'No selection',
                                'You must select one or more books to extract metadata.', 
                                show=True)
        
        book_ids = self.gui.library_view.get_selected_ids()
        db = self.gui.library_view.model().db
        logger.debug(f"Libros seleccionados para procesar (IDs): {book_ids}")

        # Verificar si las columnas personalizadas existen
        if not self._check_custom_field(db):
            logger.error("Cancelando extracción: Faltan columnas personalizadas en la biblioteca.")
            return
        
        logger.info(f"Lanzando hilo de trabajo para {len(book_ids)} libros...")
        # Iniciamos el trabajo en segundo plano
        start_extract_threaded(self.gui, book_ids, Dispatcher(self._extraction_complete))

    def _check_custom_field(self, db):
        '''Verifica la existencia de #generator, #book_producer, #title_opf y #subjects'''
        missing_fields = []
        for label in ['generator', 'book_producer', 'title_opf', 'subjects']:
            key = f'#{label}'
            if key not in db.custom_field_keys():
                missing_fields.append(key)
        
        if missing_fields:
            msg = f"Faltan las siguientes columnas personalizadas: {', '.join(missing_fields)}"
            logger.error(msg)
            error_dialog(self.gui, 'Missing Custom Fields', 
                       f"{msg}\n\nPor favor, créalas antes de usar el plugin.", 
                       show=True)
            return False
            
        logger.debug("Validación de columnas personalizadas: OK")
        return True

    def _extraction_complete(self, job):
        '''Maneja la finalización del trabajo desde el gestor de tareas'''
        logger.info("Trabajo de extracción finalizado. Procesando resultados...")
        
        if job.failed:
            logger.error(f"El trabajo de extracción falló en el gestor de Calibre: {job.exception}")
            self.gui.job_exception(job, dialog_title='Error en lote de extracción')
            return  
        
        extracted_ids, failed_ids, no_metadata_ids, det_msg = get_job_details(job)
        logger.info(f"Resumen de Job: {len(extracted_ids)} éxitos, {len(no_metadata_ids)} sin datos, {len(failed_ids)} fallos")
        
        self.gui.status_bar.show_message('Metadata extraction completed', 3000)
        
        # Actualización de la base de datos
        db = self.gui.current_db
        for book_id, title, generator, book_producer, title_opf, subjects in extracted_ids:
            try:
                logger.debug(f"Actualizando ID {book_id}: Título='{title}', Gen='{generator}', Prod='{book_producer}', Título OPF='{title_opf}'")
                if generator:
                    db.set_custom(book_id, generator, label='generator', commit=False)
                if book_producer:
                    db.set_custom(book_id, book_producer, label='book_producer', commit=False)
                if title_opf:
                    db.set_custom(book_id, title_opf, label='title_opf', commit=False)
                if subjects:
                    # Si la columna es de texto simple, mejor enviamos un string limpio
                    # Si es de etiquetas, Calibre suele aceptar ambos, pero el string es más seguro.
                    val_subjects = ', '.join(subjects) if isinstance(subjects, list) else subjects
                    db.set_custom(book_id, val_subjects, label='subjects', commit=False)
                db.commit_dirty_cache() # Guardar cambios
            except Exception as e:
                logger.error(f"Error al actualizar campos para el libro ID {book_id}: {str(e)}")
                error_dialog(self.gui, 'Error updating fields',
                           'Failed to update custom fields for {0}: {1}'.format(title, str(e)),
                           show=True)

        # Refrescar solo los libros procesados en este lote
        all_ids = [item[0] for item in extracted_ids + failed_ids + no_metadata_ids]
        if all_ids:
            logger.debug(f"Refrescando {len(all_ids)} entradas en la vista de Calibre.")
            self.gui.library_view.model().refresh_ids(all_ids)
        
        # En lugar de un diálogo molesto por cada lote, usamos la barra de estado
        # Solo mostramos diálogo si quieres ver el resumen final de ese lote específico
        self.gui.status_bar.show_message(f'Lote finalizado: {len(extracted_ids)} actualizados', 2000)
        
        # Solo mostrar resultados si hubo errores críticos en este lote
        if failed_ids:
            self._show_results(extracted_ids, failed_ids, no_metadata_ids, det_msg)

    def _show_results(self, extracted_ids, failed_ids, no_metadata_ids, det_msg):
        '''Muestra el diálogo de resultados al usuario'''
        msg = 'Metadata Extraction Results\n'
        msg += '=' * 40 + '\n\n'
        msg += f'Successfully extracted: {len(extracted_ids)}\n'
        
        if no_metadata_ids:
            msg += f'No metadata found: {len(no_metadata_ids)}\n'
        if failed_ids:
            msg += f'Failed: {len(failed_ids)}\n'
        
        total = len(extracted_ids) + len(no_metadata_ids) + len(failed_ids)
        msg += f'\nProcessed {total} books'
        
        logger.debug("Mostrando diálogo de resultados al usuario.")
        
        if failed_ids or no_metadata_ids:
            ErrorNotification(det_msg, 'Extraction Details', 
                            'Extraction complete', msg,
                            det_msg=det_msg,
                            show_copy_button=True,
                            parent=self.gui).show()
        else:
            info_dialog(self.gui, 'Extraction Complete', msg, show=True)
