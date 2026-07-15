from __future__ import unicode_literals, division, absolute_import, print_function
print("DEBUG: Cargando jobs.py...")

__license__   = 'GPL v3'
__copyright__ = '2024, Extract Generator Plugin'

import logging

# Configuramos el logger para que use el mismo canal que el extractor
logger = logging.getLogger('EXTRACTOR_PLUGIN')

from threading import Event
from calibre.gui2.convert.single import sort_formats_by_preference
from calibre.gui2.threaded_jobs import ThreadedJob
from calibre.utils.config import prefs
try:
    from calibre_plugins.extract_metadata.extractor import extract_metadata
    logger.debug("Import de extractor.py desde jobs.py OK")
except Exception as e:
    logger.error(f"No se pudo importar extractor.py: {str(e)}")

def start_extract_threaded(gui, book_ids, callback):
    '''
    Inicia la extracción dividiendo los IDs en múltiples trabajos (Jobs)
    para aprovechar el procesamiento paralelo de Calibre.
    '''
    CHUNK_SIZE = 100  # Número de libros por cada Job
    
    # Dividimos la lista de IDs en trozos
    chunks = [book_ids[i:i + CHUNK_SIZE] for i in range(0, len(book_ids), CHUNK_SIZE)]
    num_jobs = len(chunks)
    
    logger.info(f"Iniciando segmentación: {len(book_ids)} libros divididos en {num_jobs} jobs.")

    for index, chunk in enumerate(chunks):
        description = f'Extract Metadata (Lote {index + 1}/{num_jobs})'
        
        # Creamos un Job independiente para cada trozo
        job = ThreadedJob(
            'extract_metadata',
            description,
            extract_threaded, 
            (chunk, gui.current_db), 
            {}, 
            callback
        )
        gui.job_manager.run_threaded_job(job)
    
    gui.status_bar.show_message(f'Lanzados {num_jobs} procesos de extracción...', 3000)

def extract_threaded(book_ids, db, log=None, abort=None, notifications=None):
    '''
    In combination with start_extract_threaded, this function performs
    the extraction in a separate thread.
    
    :param book_ids: List of book IDs to extract generator from
    :param db: Calibre database object
    :param log: Logging object for progress messages
    :param abort: Threading Event to signal abort
    :param notifications: Queue for progress notifications
    :return: Tuple of (extracted_ids, failed_ids, no_metadata_ids, no_formats_ids)
    '''
    book_ids = list(book_ids)
    extracted_ids = []
    failed_ids = []
    no_metadata_ids = []
    no_formats_ids = []
    count = 0
    
    input_map = prefs['input_format_order']
    
    for book_id in book_ids:
        if abort.is_set():
            logger.error('Aborting...')
            break
        
        try:
            mi = db.get_metadata(book_id, index_is_id=True, get_user_categories=False)
            title = mi.title
            formats = mi.formats
            
            if not formats:
                logger.error('  No formats available for: {0}'.format(title))
                failed_ids.append((book_id, title))
                no_formats_ids.append((book_id, title))
            else:
                # Sort formats using the preferred input conversion list
                sorted_formats = sort_formats_by_preference(formats, input_map)
                generator = None
                book_producer = None
                title_opf = None
                supported_format = None
                subjects = [] # Inicializamos lista de temas
                
                for fmt in sorted_formats:
                    fmt_upper = fmt.upper()
                    
                    # Only support EPUB and AZW3
                    if fmt_upper not in ('EPUB', 'AZW3'):
                        continue
                    
                    supported_format = fmt_upper
                    file_path = db.format_abspath(book_id, fmt, index_is_id=True)
                    
                    if file_path:
                        try:
                            generator, book_producer, title_opf, subjects = extract_metadata(file_path, fmt_upper)
                            if generator or book_producer or title_opf or subjects:
                                if generator:
                                    log.info('  Generator extracted: {0}'.format(generator))
                                if book_producer:
                                    log.info('  Book contributor extracted: {0}'.format(book_producer))
                                if title_opf:
                                    log.info('  Title extracted: {0}'.format(title_opf))
                                if subjects:
                                    log.info('  Subjects extracted: {0}'.format(subjects))
                                break
                        except Exception as e:
                            log.error('  Error reading {0}: {1}'.format(fmt, str(e)))
                
                if not supported_format:
                    log.error('  No supported formats for: {0}'.format(title))
                    failed_ids.append((book_id, title))
                elif generator or book_producer or title_opf or subjects:
                    log.info('  New metadata extracted')
                    extracted_ids.append((book_id, title, generator, book_producer, title_opf, subjects))
                else:
                    log.warn('  No generator or contributor metadata found in: {0}'.format(title))
                    no_metadata_ids.append((book_id, title))
        
        except Exception as e:
            import traceback
            traceback.print_exc()
            log.error('Exception when extracting metadata: {0}'.format(str(e)))
            title = mi.title if 'mi' in locals() else 'Unknown'
            failed_ids.append((book_id, title))
        
        log.info('=' * 60)
        count += 1
        if notifications:
            notifications.put((count / len(book_ids),
                              'Scanned %d of %d' % (count, len(book_ids))))
    
    log.info('Extraction complete, with {0} failures'.format(len(failed_ids)))
    return (extracted_ids, failed_ids, no_metadata_ids, no_formats_ids)


def get_job_details(job):
    '''
    Convert the job result into a detail message summarizing the extraction.
    '''
    extracted_ids, failed_ids, no_metadata_ids, no_formats_ids = job.result
    if not hasattr(job, 'html_details'):
        job.html_details = job.details
    
    det_msg = []
    
    # Add failed IDs
    for book_id, title in failed_ids:
        if (book_id, title) in no_formats_ids:
            msg = title + ' (' + 'No formats' + ')'
        else:
            msg = title + ' ( Extraction failed )'
        det_msg.append(msg)
    
    # Add no generator found IDs
    if no_metadata_ids:
        if det_msg:
            det_msg.append('-' * 40)
        for book_id, title in no_metadata_ids:
            msg = title + ' (' + 'No metadata found' + ')'
            det_msg.append(msg)
    
    # Add successfully extracted IDs
    if extracted_ids:
        if det_msg:
            det_msg.append('-' * 40)
        for book_id, title, generator, book_producer, title_opf, subjects in extracted_ids:
            parts = []
            if generator:
                parts.append('Generator: ' + generator)
            if book_producer:
                parts.append('Producer: ' + book_producer)
            if title_opf:
                parts.append('Title: ' + title_opf) 
            if subjects:
                # Convertimos la lista ['A', 'B'] en "A, B"
                subjects_str = ', '.join(subjects) 
                parts.append('Subjects: ' + subjects_str)
            msg = '{0} ({1})'.format(title, ', '.join(parts))
            det_msg.append(msg)
    
    det_msg = '\n'.join(det_msg)
    return extracted_ids, failed_ids, no_metadata_ids, det_msg
