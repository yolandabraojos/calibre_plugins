import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import zipfile
import unicodedata
import hashlib
from lxml import etree

logger = logging.getLogger('ebook_comparator.extractor')

# Patrones de nombre de archivo que se ignoran siempre (ruido de sistema)
IGNORE_PATTERNS = [
    'titlepage.xhtml',
    'calibre_raster_cover',
    'metadata.opf',
    'nav.xhtml',
    'toc.ncx',
]

# Extensiones HTML reconocidas (en minúsculas para comparación case-insensitive)
_HTML_EXTENSIONS = ('.html', '.xhtml', '.htm')

# Media-types OPF que indican contenido HTML/XHTML (cubre .xml en algunos EPUBs)
_HTML_MEDIA_TYPES = {'application/xhtml+xml', 'text/html'}


# ---------------------------------------------------------------------------
# Detección binaria (sin parsear el EPUB)
# ---------------------------------------------------------------------------

def file_size(path):
    """Tamaño del fichero en bytes, o -1 si no se puede leer."""
    try:
        return os.path.getsize(path)
    except Exception:
        return -1


def file_sha1(path, _bufsize=1024 * 1024):
    """
    SHA-1 del fichero completo, leído por bloques para no cargarlo en memoria.
    Devuelve None si el fichero no se puede leer.  Sirve para detectar
    duplicados binarios exactos sin abrir el EPUB ni extraer texto.
    """
    try:
        h = hashlib.sha1()
        with open(path, 'rb') as f:
            for block in iter(lambda: f.read(_bufsize), b''):
                h.update(block)
        return h.hexdigest()
    except Exception:
        logger.debug('No se pudo calcular SHA-1 de %s', path, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Caché de extracción por libro
# ---------------------------------------------------------------------------
# Un mismo libro puede aparecer en varios pares (un grupo de 3 copias genera 3
# pares).  Sin caché se extraería y parsearía el EPUB varias veces.  La clave
# incluye (path, mtime, size) para invalidarse automáticamente si el fichero
# cambia.  Es thread-safe porque Calibre lanza los lotes como ThreadedJobs que
# pueden ejecutarse concurrentemente en el mismo proceso.

_CHAPTER_CACHE = {}
_CHAPTER_CACHE_LOCK = threading.Lock()
_CHAPTER_CACHE_MAX = 512   # nº máximo de libros cacheados (evita crecer sin límite)


def _cache_key(path):
    try:
        st = os.stat(path)
        return (os.path.abspath(path), int(st.st_mtime), st.st_size)
    except Exception:
        return None


def extract_book_chapters_cached(book_path):
    """
    Igual que extract_book_chapters() pero memoiza el resultado por
    (path, mtime, size).  Devuelve copias superficiales de los contenedores
    para que el llamante pueda mutarlos sin corromper la entrada cacheada.
    """
    key = _cache_key(book_path)
    if key is None:
        return extract_book_chapters(book_path)

    with _CHAPTER_CACHE_LOCK:
        hit = _CHAPTER_CACHE.get(key)
    if hit is not None:
        chapters, ignored = hit
        return dict(chapters), list(ignored)

    chapters, ignored = extract_book_chapters(book_path)

    with _CHAPTER_CACHE_LOCK:
        if len(_CHAPTER_CACHE) >= _CHAPTER_CACHE_MAX:
            # Política simple: vaciar al alcanzar el tope (las ejecuciones son
            # acotadas en el tiempo, no necesitamos LRU real).
            _CHAPTER_CACHE.clear()
        _CHAPTER_CACHE[key] = (chapters, ignored)

    return dict(chapters), list(ignored)


def clear_chapter_cache():
    """Vacía la caché de extracción.  Útil entre ejecuciones independientes."""
    with _CHAPTER_CACHE_LOCK:
        _CHAPTER_CACHE.clear()


def _is_html_file(name):
    """Devuelve True si el nombre de archivo tiene extensión HTML (case-insensitive)."""
    return name.lower().endswith(_HTML_EXTENSIONS)


def _is_system_file(name):
    """
    Devuelve True si el archivo coincide con algún patrón de sistema.
    La comparación se hace en minúsculas para tolerar cualquier capitalización.
    """
    name_lower = name.lower()
    return any(p in name_lower for p in IGNORE_PATTERNS)


def _is_jacket_by_name(name):
    """
    Detecta portadillas jacket por nombre de archivo.
    Cubre variantes habituales: jacket.xhtml, jacket.html, jacket.HTML, etc.
    """
    basename = name.rsplit('/', 1)[-1].lower()
    return basename.startswith('jacket')


def _get_manifest_html_items(zf, all_names):
    """
    Parsea el OPF y devuelve el conjunto de rutas ZIP que corresponden a
    ítems de contenido HTML/XHTML según su media-type en el manifiesto.

    Esto permite detectar archivos con extensión .xml que son en realidad
    documentos XHTML (frecuente en EPUBs generados por ciertas herramientas
    donde el spine referencia ficheros con extensión .xml pero media-type
    application/xhtml+xml).
    """
    import posixpath
    opf_name = next((n for n in all_names if n.endswith('.opf')), None)
    if not opf_name:
        return set()
    try:
        raw  = zf.read(opf_name)
        root = etree.fromstring(raw)
        ns   = {'opf': 'http://www.idpf.org/2007/opf'}
        base = opf_name.rsplit('/', 1)[0] + '/' if '/' in opf_name else ''

        zip_set      = set(all_names)
        lower_index  = {n.lower(): n for n in all_names}

        html_items = set()
        for item in root.findall('.//opf:item', ns):
            media_type = (item.get('media-type') or '').lower().split(';')[0].strip()
            if media_type not in _HTML_MEDIA_TYPES:
                continue
            href = (item.get('href') or '').split('#')[0]
            if not href:
                continue
            candidate = posixpath.normpath(base + href).lstrip('./')
            if candidate in zip_set:
                html_items.add(candidate)
            elif candidate.lower() in lower_index:
                html_items.add(lower_index[candidate.lower()])
        return html_items
    except Exception:
        logger.debug('Error parseando manifest HTML items', exc_info=True)
        return set()


def _is_jacket_by_content(raw_bytes):
    """
    Detecta archivos jacket inspeccionando el contenido HTML.
    Calibre incluye <meta name="calibre-content" content="jacket"/> en la
    portadilla de metadatos aunque el archivo tenga otro nombre (frecuente en
    conversiones AZW3 donde el jacket se fragmenta o renombra).
    """
    try:
        # Búsqueda rápida en bytes antes de parsear el árbol completo
        snippet = raw_bytes[:4096].lower()
        if b'calibre-content' not in snippet and b'jacket' not in snippet:
            return False
        parser = etree.HTMLParser(recover=True, encoding='utf-8')
        root = etree.fromstring(raw_bytes, parser=parser)
        for meta in root.iter('meta'):
            name_attr    = (meta.get('name')    or '').lower()
            content_attr = (meta.get('content') or '').lower()
            if name_attr == 'calibre-content' and content_attr == 'jacket':
                return True
    except Exception:
        pass
    return False


def extract_epub_chapters(epub_path):
    """
    Devuelve una tupla ({nombre_archivo: texto_limpio}, [ignored_files]).

    ignored_files es una lista de dicts:
        {'name': str, 'reason': str}
    con las siguientes razones posibles:
        'sistema'  -- coincide con IGNORE_PATTERNS (nav, toc, titlepage...)
        'jacket'   -- portadilla de metadatos Calibre (por nombre o por contenido)
        'vacío'    -- el archivo existe pero no contiene ningún texto extraíble
                     (página completamente en blanco o solo imágenes sin alt-text)

    Estrategia de cobertura completa:
    - Se usa el spine del OPF para obtener el orden canónico.
    - Los archivos HTML presentes en el ZIP pero AUSENTES del spine
      (notas, apéndices, archivos huérfanos) se añaden al final en
      orden alfabético, para que no se pierda ningún contenido.
    - NO se filtran archivos por longitud mínima: incluso los fragmentos
      muy cortos (dedicatorias, citas, páginas de copyright) se incluyen
      en la comparativa. Solo se ignoran los archivos que resultan en
      cadena vacía tras la extracción de texto.
    """
    logger.debug('Extracting EPUB chapters from %s', epub_path)
    chapters = {}
    ignored  = []

    with zipfile.ZipFile(epub_path, 'r') as zf:
        all_names = zf.namelist()

        # -- Paso 1a: detectar ítems HTML/XHTML por manifest OPF --
        # Cubre archivos con extensión .xml que el OPF declara como
        # application/xhtml+xml (frecuente en algunos EPUBs generados por
        # herramientas propietarias).
        manifest_html = _get_manifest_html_items(zf, all_names)

        def _is_html_candidate(name):
            return _is_html_file(name) or name in manifest_html

        # -- Paso 1b: separar archivos HTML de sistema (sin leer contenido) --
        system_files = [n for n in all_names if _is_html_candidate(n) and _is_system_file(n)]
        for n in system_files:
            ignored.append({'name': n, 'reason': 'sistema'})

        # -- Paso 2: candidatos reales (HTML no-sistema) --
        html_candidates = {n for n in all_names if _is_html_candidate(n) and not _is_system_file(n)}

        # -- Paso 3: orden canónico (spine OPF) + huérfanos al final --
        spine_ordered = [n for n in _get_spine_order(zf, all_names) if n in html_candidates]
        spine_set     = set(spine_ordered)
        extra_names   = sorted(n for n in html_candidates if n not in spine_set)
        ordered_names = spine_ordered + extra_names

        if extra_names:
            logger.debug('%s: %d archivos fuera del spine añadidos: %s',
                         epub_path, len(extra_names), extra_names)

        # -- Paso 4: procesar cada candidato --
        for name in ordered_names:
            try:
                raw = zf.read(name)
            except Exception:
                logger.debug('Error leyendo %s en %s', name, epub_path)
                ignored.append({'name': name, 'reason': 'error de lectura'})
                continue

            # Detección de jacket por nombre (evita parsear HTML innecesariamente)
            if _is_jacket_by_name(name):
                ignored.append({'name': name, 'reason': 'jacket'})
                continue

            # Detección de jacket por contenido (cubre renombrados en AZW3)
            if _is_jacket_by_content(raw):
                ignored.append({'name': name, 'reason': 'jacket'})
                logger.debug('Jacket detectado por contenido: %s en %s', name, epub_path)
                continue

            text = _html_to_text(raw)
            if text:
                chapters[name] = text
            else:
                # Solo ignoramos si no hay absolutamente ningún texto extraíble
                ignored.append({'name': name, 'reason': 'vacío'})

    return chapters, ignored


def extract_book_chapters(book_path):
    """
    Devuelve (chapters, ignored_files).
    Ambas funciones internas devuelven la misma tupla.
    """
    ext = os.path.splitext(book_path)[1].lower()
    if ext == '.epub':
        return extract_epub_chapters(book_path)
    if ext == '.azw3':
        return extract_azw3_chapters(book_path)
    raise ValueError('Formato no soportado: {}'.format(ext))


def _find_ebook_convert():
    candidates = [
        shutil.which('ebook-convert'),
        os.path.join(os.path.dirname(sys.executable), 'ebook-convert.exe'),
        os.path.join(os.path.dirname(sys.executable), 'ebook-convert'),
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    raise FileNotFoundError('No se encontró ebook-convert.')


def extract_azw3_chapters(azw3_path):
    converter = _find_ebook_convert()
    with tempfile.TemporaryDirectory() as tmpdir:
        epub_path = os.path.join(tmpdir, 'temp_conv.epub')
        creationflags = 0
        if sys.platform == 'win32':
            creationflags = subprocess.CREATE_NO_WINDOW
        proc = subprocess.run(
            [
                converter, azw3_path, epub_path,
                # Evita que Calibre trocee los HTML grandes en fragmentos
                # 'partNNNN_split_00M.html' que no existen en el AZW3 original
                # y que inflaban los "únicos en B" al comparar (1 capítulo de A
                # frente a varios fragmentos de B).
                '--flow-size', '0',            # sin partición por tamaño
                '--dont-split-on-page-breaks', # sin partición por saltos de página
            ],
            capture_output=True, text=True, creationflags=creationflags,
        )
        if proc.returncode != 0:
            raise RuntimeError('Error convirtiendo AZW3')
        return extract_epub_chapters(epub_path)


def _get_spine_order(zf, all_names):
    """
    Devuelve los archivos del spine en orden canónico, con rutas normalizadas
    que coincidan exactamente con los nombres del ZIP.

    - Elimina fragmentos (#anchor) de los hrefs antes de resolver la ruta.
    - Usa posixpath.normpath para resolver '..' y '.' en rutas relativas.
    - Si la ruta construida no existe en el ZIP, intenta buscarla por basename
      como último recurso (EPUBs con hrefs simples sin directorio).
    - Devuelve lista vacía (no all_names) cuando el spine parsea pero está
      vacío, para que el caller use su propio fallback controlado.
    - La búsqueda en el ZIP es case-insensitive para tolerar EPUBs con
      extensiones en mayúsculas (.HTML, .XHTML).
    """
    import posixpath
    opf_name = next((n for n in all_names if n.endswith('.opf')), None)
    if not opf_name:
        return []
    try:
        raw  = zf.read(opf_name)
        root = etree.fromstring(raw)
        ns   = {'opf': 'http://www.idpf.org/2007/opf'}
        manifest = {
            item.get('id'): item.get('href', '')
            for item in root.findall('.//opf:item', ns)
        }
        base    = opf_name.rsplit('/', 1)[0] + '/' if '/' in opf_name else ''
        zip_set = set(all_names)

        # Índice case-insensitive: ruta_lower -> ruta_original
        lower_index = {n.lower(): n for n in all_names}
        # Índice basename (case-insensitive) -> ruta_original para último recurso
        basename_index = {}
        for n in all_names:
            bn = n.rsplit('/', 1)[-1].lower()
            basename_index.setdefault(bn, n)

        ordered = []
        seen    = set()
        for itemref in root.findall('.//opf:itemref', ns):
            href = manifest.get(itemref.get('idref'), '')
            if not href:
                continue
            href = href.split('#')[0]
            if not href:
                continue
            candidate = posixpath.normpath(base + href)
            candidate = candidate.lstrip('./')

            # Búsqueda exacta primero, luego case-insensitive, luego por basename
            if candidate in zip_set:
                path = candidate
            elif candidate.lower() in lower_index:
                path = lower_index[candidate.lower()]
            else:
                path = basename_index.get(href.rsplit('/', 1)[-1].lower())

            if path and path not in seen:
                ordered.append(path)
                seen.add(path)
        return ordered
    except Exception:
        logger.debug('Error parseando spine de %s', opf_name, exc_info=True)
        return []


def _html_to_text(raw_bytes):
    try:
        parser = etree.HTMLParser(recover=True, encoding='utf-8')
        root = etree.fromstring(raw_bytes, parser=parser)
        for tag in root.iter('script', 'style', 'head'):
            tag.text = tag.tail = None
        text = ' '.join(root.itertext())
    except Exception:
        text = re.sub(r'<[^>]+>', ' ', raw_bytes.decode('utf-8', errors='ignore'))
    return _normalize(text)


def _normalize(text):
    """Normalización robusta: minúsculas, sin acentos y limpieza de espacios."""
    text = text.lower()
    text = "".join(
        c for c in unicodedata.normalize('NFD', text)
        if unicodedata.category(c) != 'Mn'
    )
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text
