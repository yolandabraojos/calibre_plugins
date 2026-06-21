from __future__ import unicode_literals, division, absolute_import, print_function

__license__   = 'GPL v3'
__copyright__ = '2026, Fix Metadata Plugin'

import logging

logger = logging.getLogger('FIX_METADATA_PLUGIN')

from calibre.gui2.convert.single import sort_formats_by_preference
from calibre.gui2.threaded_jobs import ThreadedJob
from calibre.utils.config import prefs

try:
    from calibre_plugins.fix_metadata.extractor import extract_metadata
except Exception as e:
    logger.error(f"Could not import extractor.py: {e}")


def start_extract_threaded(gui, book_ids, callback):
    '''
    Split book_ids into chunks and launch one ThreadedJob per chunk.
    '''
    CHUNK_SIZE = 100
    chunks   = [book_ids[i:i + CHUNK_SIZE] for i in range(0, len(book_ids), CHUNK_SIZE)]
    num_jobs = len(chunks)
    logger.info(f"Launching {num_jobs} extraction job(s) for {len(book_ids)} book(s).")

    for index, chunk in enumerate(chunks):
        job = ThreadedJob(
            'fix_metadata_extract',
            f'Fix Metadata – Extract (batch {index + 1}/{num_jobs})',
            _extract_threaded,
            (chunk, gui.current_db),
            {},
            callback,
        )
        gui.job_manager.run_threaded_job(job)

    gui.status_bar.show_message(f'Launched {num_jobs} extraction job(s)…', 3000)


def _extract_threaded(book_ids, db, log=None, abort=None, notifications=None):
    '''Worker function executed inside a ThreadedJob.'''
    book_ids        = list(book_ids)
    extracted_ids   = []
    failed_ids      = []
    no_metadata_ids = []
    no_formats_ids  = []
    count           = 0

    input_map = prefs['input_format_order']

    for book_id in book_ids:
        if abort.is_set():
            break

        mi = None
        try:
            mi      = db.get_metadata(book_id, index_is_id=True, get_user_categories=False)
            title   = mi.title
            formats = mi.formats

            if not formats:
                log.error(f'  No formats for: {title}')
                failed_ids.append((book_id, title))
                no_formats_ids.append((book_id, title))
            else:
                sorted_formats   = sort_formats_by_preference(formats, input_map)
                generator        = None
                book_producer    = None
                title_opf        = None
                subtitle         = None
                subjects         = []
                supported_format = None

                for fmt in sorted_formats:
                    fmt_upper = fmt.upper()
                    if fmt_upper not in ('EPUB', 'AZW3'):
                        continue
                    supported_format = fmt_upper
                    file_path = db.format_abspath(book_id, fmt, index_is_id=True)
                    if file_path:
                        try:
                            generator, book_producer, title_opf, subjects, subtitle = \
                                extract_metadata(file_path, fmt_upper)
                            if generator or book_producer or title_opf or subjects or subtitle:
                                break
                        except Exception as e:
                            log.error(f'  Error reading {fmt}: {e}')

                if not supported_format:
                    log.error(f'  No supported formats for: {title}')
                    failed_ids.append((book_id, title))
                elif generator or book_producer or title_opf or subjects or subtitle:
                    extracted_ids.append(
                        (book_id, title, generator, book_producer, title_opf,
                         subjects, subtitle))
                else:
                    log.warn(f'  No metadata found in: {title}')
                    no_metadata_ids.append((book_id, title))

        except Exception as e:
            import traceback
            traceback.print_exc()
            log.error(f'Exception extracting metadata: {e}')
            title = mi.title if mi is not None else 'Unknown'
            failed_ids.append((book_id, title))

        count += 1
        if notifications:
            notifications.put((count / len(book_ids),
                               f'Scanned {count} of {len(book_ids)}'))

    log.info(f'Extraction complete – {len(failed_ids)} failure(s)')
    return (extracted_ids, failed_ids, no_metadata_ids, no_formats_ids)


def get_job_details(job):
    extracted_ids, failed_ids, no_metadata_ids, no_formats_ids = job.result
    if not hasattr(job, 'html_details'):
        job.html_details = job.details

    lines = []

    for book_id, title in failed_ids:
        suffix = 'No formats' if (book_id, title) in no_formats_ids else 'Extraction failed'
        lines.append(f'{title} ({suffix})')

    if no_metadata_ids:
        if lines:
            lines.append('-' * 40)
        for book_id, title in no_metadata_ids:
            lines.append(f'{title} (No metadata found)')

    if extracted_ids:
        if lines:
            lines.append('-' * 40)
        for book_id, title, generator, book_producer, title_opf, subjects, subtitle \
                in extracted_ids:
            parts = []
            if generator:
                parts.append(f'Generator: {generator}')
            if book_producer:
                parts.append(f'Producer: {book_producer}')
            if title_opf:
                parts.append(f'Title: {title_opf}')
            if subtitle:
                parts.append(f'Subtitle: {subtitle}')
            if subjects:
                parts.append('Subjects: ' + ', '.join(subjects))
            lines.append(f'{title} ({", ".join(parts)})')

    return extracted_ids, failed_ids, no_metadata_ids, '\n'.join(lines)
