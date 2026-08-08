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

# Extensiones que NUNCA contienen capitulos: evitan leer imagenes y fuentes
# enteras en la deteccion por contenido.
# Problemas de formato que hacen recomendable reconvertir el libro con Calibre.
# Se detectan durante la extraccion, sin releer nada: son observaciones de lo que
# ya ha habido que mirar para sacar los capitulos.
ISSUE_LABELS = {
    'zip_danado':        'el ZIP esta danado (hubo que rescatarlo con ebook-convert)',
    'sin_opf':           'no tiene OPF',
    'opf_ilegible':      'el OPF no se puede interpretar',
    'fuera_del_manifest': 'tiene capitulos que el OPF no declara',
    'sin_spine':         'el OPF no define el orden de lectura (spine)',
    'rescatado_por_contenido': 'sus capitulos no se reconocian ni por nombre ni por OPF',
    'muy_troceado':      'esta partido en muchos fragmentos por una conversion',
    'sin_texto':         'no se le ha podido extraer ningun texto',
}

_BINARY_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.bmp', '.tif', '.tiff',
    '.otf', '.ttf', '.woff', '.woff2', '.eot',
    '.css', '.js', '.ncx', '.opf', '.xpgt', '.mp3', '.mp4', '.m4a', '.pdf',
}


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


def _unquote_href(href):
    """
    Desescapa un href del OPF.

    Los href van percent-encoded (RFC 3986): un fichero llamado
    'cap 01.html' aparece como 'cap%2001.html'.  Sin desescapar, el nombre no
    coincide con el del ZIP, el item se descarta y el libro puede acabar con
    CERO capitulos aunque tenga texto.
    """
    try:
        from urllib.parse import unquote           # Python 3
    except ImportError:                            # pragma: no cover
        from urllib import unquote                 # Python 2
    try:
        return unquote(href)
    except Exception:
        return href


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
            href = _unquote_href(href)
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


# ---------------------------------------------------------------------------
# Clasificacion de fragmentos '_split_' para fusion (movido aqui desde
# merge_splits.py el 2026-08-06 para que extract_epub_chapters() pueda usar
# el MISMO criterio al decidir si un libro esta 'muy_troceado' de verdad, en
# vez de mantener dos logicas separadas que podrian discrepar. merge_splits.py
# importa estas funciones de aqui.
# ---------------------------------------------------------------------------

# Umbral por defecto: el mismo que marca 'muy_troceado' en el informe, para que
# lo que aqui se arregla sea exactamente lo que alli se senala.
DEFAULT_MIN_SPLITS = 20

# Tamano maximo de un fichero fusionado: el mismo 'flow_size' que usa Calibre
# por defecto al convertir (260 KB, el limite historico de Adobe Digital
# Editions).  SIN este tope, fusionar todo el grupo de un tiron puede crear un
# unico fichero de mas de 1 MB si el libro entero comparte una sola base (p.
# ej. un MOBI/AZW3 cuyo contenido original ya era UN flujo continuo, sin
# ficheros por capitulo): eso vuelve a ser justo el problema que el limite de
# Calibre existe para evitar (la mayoria de lectores no tragan ficheros
# grandes).  Con el tope, un grupo largo se fusiona en VARIOS tramos en vez de
# uno solo, respetando siempre los cortes que Calibre ya dejo hechos (no se
# inventa ningun punto de corte nuevo).
DEFAULT_MAX_MERGED_KB = 260

# Sufijos '_split_000' encadenados (un libro reconvertido varias veces los
# acumula: 'cap_split_002_split_000.html').  Se quitan TODOS para agrupar.
_SPLIT_SUFFIX = re.compile(r'(_split_?\d+)+$', re.IGNORECASE)


def split_base(name):
    """Nombre sin los sufijos '_split_NNN', conservando carpeta y extension."""
    folder, base = os.path.split(name)
    stem, ext = os.path.splitext(base)
    stem = _SPLIT_SUFFIX.sub('', stem)
    return '{}/{}{}'.format(folder, stem, ext) if folder else stem + ext


def is_split_name(name):
    stem = os.path.splitext(os.path.split(name)[1])[0]
    return bool(_SPLIT_SUFFIX.search(stem))


def group_spine(names):
    """
    Agrupa nombres CONSECUTIVOS del spine con la misma base.

    Devuelve [[n1, n2, ...], ...] solo con los grupos de 2 o mas.  Se exige que
    sean consecutivos a proposito: dos ficheros con la misma base pero
    separados por otro capitulo en medio no vienen del mismo corte, y unirlos
    cambiaria el orden de lectura.
    """
    groups, current, current_base = [], [], None
    for name in names:
        base = split_base(name)
        if current and base == current_base and is_split_name(name):
            current.append(name)
            continue
        if len(current) > 1:
            groups.append(current)
        current = [name] if is_split_name(name) else []
        current_base = base if current else None
    if len(current) > 1:
        groups.append(current)
    return groups


def size_bounded_subgroups(sizes, max_size):
    """
    Parte una lista de tamanos (bytes) en tramos CONSECUTIVOS cuya suma no pase
    de 'max_size'.  Devuelve una lista de listas de INDICES.

    No inventa ningun punto de corte: los unicos candidatos son los limites que
    Calibre ya dejo entre fragmentos.  Solo decide cuales conservar (los
    necesarios para no pasarse de tamano) y cuales fusionar.  Un fragmento que
    el solo ya supera 'max_size' va en su propio tramo: no hay nada mejor que
    hacer sin trocearlo por dentro, que es justo lo que no se quiere reinventar.
    """
    groups, current, current_ids, total = [], [], [], 0
    for i, s in enumerate(sizes):
        if current_ids and total + s > max_size:
            groups.append(current_ids)
            current_ids, total = [], 0
        current_ids.append(i)
        total += s
    if current_ids:
        groups.append(current_ids)
    return groups


# Elementos de cabecera que se consideran arranque de capitulo/seccion.  Es la
# MISMA senal que usa el propio Calibre para detectar estructura (ver
# DetectStructure.detect_chapters en structure.py, que tambien busca h1/h2 como
# candidato por defecto), reutilizada aqui en vez de inventar un criterio
# nuevo.
_HEADING_TAGS = frozenset({'h1', 'h2', 'h3', 'h4', 'h5', 'h6'})
# Envoltorios sin contenido propio (div de maquetacion, span de estilo...): se
# atraviesan sin contar, porque Calibre suele meter el titulo (o la imagen de
# portadilla) dentro de uno de estos justo tras el salto de pagina.
_STRUCTURAL_TAGS = frozenset({'div', 'span', 'section', 'article', 'body'})
_SKIP_TAGS = frozenset({'script', 'style', 'meta', 'link', 'title'})

# Palabras que por si solas ya bastan: no hace falta que las siga un numero
# porque no se usan de otra forma al arrancar una linea corta.  Incluye tanto
# marcadores de capitulo como secciones sueltas de portada/cierre
# (agradecimientos, sobre la autora...): a efectos de en que fichero quedan
# se tratan igual, todas abren fichero nuevo y no admiten que nada se les
# fusione por delante.
_CHAPTER_WORDS_UNAMBIGUOUS = (
    r'cap[ií]tulos?', r'chapters?', r'pr[oó]logo', r'prologue',
    r'ep[ií]logo', r'epilogue',
    r'prefacio', r'preface', r'foreword',
    r'posfacio', r'postfacio', r'afterword',
    r'agradecimientos?', r'acknowledge?ments?',
    r'sobre\s+(?:el\s+autor|la\s+autora|los\s+autores|las\s+autoras)',
    r'about\s+the\s+authors?',
    r'dedicatoria', r'dedication',
    r'ep[ií]grafe', r'epigraph',
    r'nota\s+(?:de\s+la\s+autora|del\s+autor|de\s+autor|de\s+la\s+editorial|'
    r'del\s+traductor|de\s+la\s+traductora)',
    r"(?:author|translator)'?s\s+notes?",
    r'notas?(?:\s+finales?)?',
    r'glosario', r'glossary',
    r'bibliograf[ií]a', r'bibliography',
    r'ap[eé]ndice', r'appendix',
    r'tambi[eé]n\s+de\s+(?:est[ae]|la\s+autora|el\s+autor)',
    r'also\s+by',
    r'adelanto', r'avance', r'excerpt', r'sneak\s+peek',
    r'personajes', r'cast\s+of\s+characters',
    r'playlist', r'lista\s+de\s+reproducci[oó]n',
)
# Palabras normales y corrientes que TAMBIEN se usan para titular capitulos
# ("Parte II", "Libro Segundo", "Acto I"), pero que aparecen todo el tiempo
# como primera palabra de una frase cualquiera ("Parte de la culpa fue mia").
# Para no confundir una con otra, aqui hace falta ademas un numero/ordinal
# detras.
_CHAPTER_WORDS_NEED_ORDINAL = (
    r'parte', r'part', r'libro', r'book', r'secci[oó]n', r'section',
    r'acto', r'act', r'interludio', r'interlude',
)
_ORDINAL = (
    r'(?:\d+|[ivxlcdm]+\b|'
    r'primer[ao]?|segund[ao]|tercer[ao]?|cuart[ao]|quint[ao]|sext[ao]|'
    r's[eé]ptim[ao]|octav[ao]|noven[ao]|d[eé]cim[ao]|'
    r'one|two|three|four|five|six|seven|eight|nine|ten|'
    r'first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)'
)
_CHAPTER_TEXT_RE = re.compile(
    r'^\s*(?:'
    + '|'.join(_CHAPTER_WORDS_UNAMBIGUOUS)
    + r'|(?:' + '|'.join(_CHAPTER_WORDS_NEED_ORDINAL) + r')\s*[:.\-]?\s*' + _ORDINAL
    + r')\b',
    re.IGNORECASE,
)
# Un titulo es una linea corta.  Sin este tope, una frase normal que EMPIECE
# por "Parte" o "Capitulo" usado como nombre propio colaria como titulo.
_CHAPTER_TEXT_MAX_LEN = 80

# Ver el comentario dentro de classify_fragment_start().
_HEADING_LOOKAHEAD_CHARS = 400


def _looks_like_chapter_text(text):
    text = (text or '').strip()
    if not text or len(text) > _CHAPTER_TEXT_MAX_LEN:
        return False
    return bool(_CHAPTER_TEXT_RE.match(text))


# El indice se reconoce distinto de un capitulo: suele ser SOLO esa palabra en
# la linea (nada de "Indice de la primera parte..." con texto detras), asi
# que aqui se exige la linea COMPLETA, no solo el arranque.
_TOC_WORDS = (
    r'[ií]ndices?(?:\s+de\s+contenidos?)?',
    r'tabla\s+de\s+contenidos?',
    r'contenidos?',
    r'table\s+of\s+contents',
    r'contents',
    r'index(?:es)?',
)
_TOC_TEXT_RE = re.compile(r'^\s*(?:' + '|'.join(_TOC_WORDS) + r')\s*$',
                          re.IGNORECASE)


def _looks_like_toc_text(text):
    text = (text or '').strip()
    if not text or len(text) > _CHAPTER_TEXT_MAX_LEN:
        return False
    return bool(_TOC_TEXT_RE.match(text))


def _has_toc_nav(body):
    """True si hay un <nav epub:type="toc"> en algun sitio del fragmento."""
    for el in body.iter():
        tag = el.tag
        if not isinstance(tag, str) or tag.rsplit('}', 1)[-1].lower() != 'nav':
            continue
        for key, val in el.attrib.items():
            if key.rsplit('}', 1)[-1].lower() == 'type' and 'toc' in (val or '').lower():
                return True
    return False


def _is_link_list(el):
    """
    True si 'el' es un <ul>/<ol> donde la mayoria de <li> son practicamente
    solo un enlace -- la forma clasica de un indice sin marcar como <nav>
    (EPUB2, o TOC hecho a mano).  Con pocos elementos no se puede distinguir
    de una lista cualquiera, asi que se pide un minimo.
    """
    tag = el.tag
    bare = tag.rsplit('}', 1)[-1].lower() if isinstance(tag, str) else None
    if bare not in ('ul', 'ol'):
        return False
    items = [c for c in el if isinstance(c.tag, str)
            and c.tag.rsplit('}', 1)[-1].lower() == 'li']
    if len(items) < 3:
        return False
    con_enlace = sum(
        1 for li in items
        if any(isinstance(d.tag, str) and d.tag.rsplit('}', 1)[-1].lower() == 'a'
              for d in li.iter()))
    return con_enlace >= max(3, int(0.7 * len(items)))


def classify_fragment_start(root):
    """
    Clasifica un fragmento por como EMPIEZA, mirando los primeros elementos
    con contenido real de <body> (atraviesa envoltorios vacios sin contar).

    Devuelve una de:
      'heading'  -- arranca con un titulo h1-h6 (que no sea el del indice).
      'chapter_text' -- arranca con una linea corta tipo "Capitulo 5",
                    "Parte II" o "Agradecimientos", sin etiqueta de titulo
                    (habitual en EPUB mal maquetados: todo son <p>, no hay
                    h1-h6 en ningun sitio).
      'toc'      -- es la tabla de contenidos: un <nav epub:type="toc">, una
                    lista de enlaces tipica de indice, o un titulo/texto tipo
                    "Indice"/"Contents".
      'image'    -- el fragmento entero no tiene NINGUN texto, solo imagenes
                    (portadilla decorativa antes del titulo, que Calibre a
                    veces deja en su propio fichero al partir).
      'content'  -- contenido normal: no es un arranque de nada.

    Por que hace falta esto y no basta el tamano: Calibre trocea un fichero
    por DOS motivos (structure.py + split.py) -- saltos de pagina, que SI son
    capitulos, y limite de tamano, que parte por la mitad sin mirar que hay
    ahi.  Al comprimir el resultado a un unico EPUB esa distincion se pierde:
    no queda ninguna marca que diga cual de los dos motivos causo cada corte.
    Esta funcion es la mejor aproximacion posible sin esa marca.  Es una
    heuristica, no una certeza -- igual que las que usa el propio Calibre
    para lo mismo.
    """
    if root is None or not hasattr(root, 'find'):
        return 'content'
    ns = '{http://www.w3.org/1999/xhtml}'
    body = root.find(ns + 'body')
    if body is None:
        body = root.find('body')
    if body is None:
        # Recorrido manual: cubre tanto arboles namespaced (el contenedor de
        # Calibre, container.parsed(), que usa merge_splits.py al fusionar)
        # como los que devuelve etree.HTMLParser() al analizar un fragmento
        # suelto SIN namespace, que es como lo hace extractor.py al escanear
        # sin pasar por Calibre (ver _parse_fragment_root). Sin este segundo
        # intento, classify_fragment_start() siempre devolveria 'content'
        # fuera de Calibre y la deteccion de 'muy_troceado' no distinguiria
        # nada.
        for el in root.iter():
            tag = el.tag
            if isinstance(tag, str) and tag.rsplit('}', 1)[-1].lower() == 'body':
                body = el
                break
    if body is None:
        return 'content'

    def bare_tag(el):
        tag = el.tag
        if not isinstance(tag, str):
            return None
        return tag.rsplit('}', 1)[-1].lower()

    if _has_toc_nav(body):
        return 'toc'

    # Portadilla: el fragmento ENTERO no tiene texto, solo imagenes (y quiza
    # saltos de linea/reglas).  Se mira el cuerpo completo, no solo el
    # arranque: un fichero asi puede ser SOLO una imagen a pagina completa.
    full_text = ''.join(body.itertext()).strip()
    if not full_text:
        has_image = any(bare_tag(el) == 'img' for el in body.iter())
        if has_image:
            return 'image'

    # Cuanto texto de "portada" (epigrafe, cita, dedicatoria corta...) se
    # admite ANTES de un h1-h6 y el fragmento se sigue contando como el mismo
    # arranque de capitulo.  Sin este margen, un capitulo real que empieza con
    # una cita de una o dos lineas antes del titulo se clasificaba como
    # 'content' porque el bucle se rendia a las DOS lineas de texto, sin
    # llegar nunca a visitar el <h1> que venia justo despues (encontrado
    # 2026-08-06: un libro con capitulos reales seguia marcandose como
    # 'muy_troceado' porque cada fragmento empezaba con un par de lineas de
    # epigrafe). Un titulo que aparece MAS ALLA de este margen no cuenta como
    # arranque: es mas probable que sea un subtitulo interno a mitad de un
    # capitulo largo (p. ej. un "Nota" a pie de seccion), no el principio de
    # uno nuevo.
    chars_seen = 0
    elems_seen = 0
    for el in body.iter():
        if el is body:
            continue
        bare = bare_tag(el)
        if bare is None or bare in _SKIP_TAGS:
            continue
        if bare in _HEADING_TAGS:
            heading_text = ''.join(el.itertext()).strip()
            if _looks_like_toc_text(heading_text):
                return 'toc'
            if chars_seen <= _HEADING_LOOKAHEAD_CHARS:
                return 'heading'
            return 'content'
        if bare == 'img':
            continue  # una imagen antes del titulo no cuenta como contenido
        if bare in ('ul', 'ol') and _is_link_list(el):
            return 'toc'
        own_text = (el.text or '').strip()
        if bare in _STRUCTURAL_TAGS and not own_text:
            continue  # envoltorio puro: se sigue mirando dentro, sin contar
        if not own_text and bare != 'hr':
            continue  # elemento vacio, sin contenido propio
        if own_text and _looks_like_toc_text(own_text):
            return 'toc'
        if own_text and _looks_like_chapter_text(own_text):
            return 'chapter_text'
        chars_seen += len(own_text)
        elems_seen += 1
        if chars_seen > _HEADING_LOOKAHEAD_CHARS or elems_seen >= 12:
            return 'content'
    return 'content'


def chapter_runs_from_kinds(kinds):
    """
    Agrupa los INDICES de una lista de clasificaciones (la salida de
    'classify_fragment_start' para cada fragmento de un mismo grupo, ver
    'group_spine') en tramos que representan un mismo capitulo/indice/
    portadilla.  Reglas, en orden:

      1. 'heading' o 'chapter_text' SIEMPRE abren un tramo nuevo: es un
         capitulo (o seccion tipo agradecimientos) que empieza.
      2. 'toc' abre un tramo nuevo TAMBIEN -- salvo que el tramo abierto sea
         OTRO 'toc': asi un indice grande partido en varios _split_ se
         fusiona consigo mismo (respetando despues el tope de tamano), pero
         nunca con el capitulo de al lado.
      3. 'content' continua el tramo abierto -- EXCEPTO si el tramo abierto
         es un 'toc': el indice no admite que se le pegue prosa normal
         detras, asi que un 'content' fuerza tramo nuevo justo despues.
      4. 'image' (portadilla sin texto) NO abre tramo por si sola en esta
         primera pasada: se decide DESPUES, yendo hacia atras, pegandola al
         tramo que la sigue si ese tramo es un capitulo o un indice.  Una
         portadilla suelta que no precede a nada especial se queda donde
         estaba, como contenido normal.

    Devuelve una lista de listas de INDICES.
    """
    n = len(kinds)
    starts_new = [False] * n
    run_kind = None
    for i, kind in enumerate(kinds):
        if i == 0:
            starts_new[i] = True
        elif kind in ('heading', 'chapter_text'):
            starts_new[i] = True
        elif kind == 'toc':
            starts_new[i] = (run_kind != 'toc')
        elif kind == 'content':
            starts_new[i] = (run_kind == 'toc')
        # 'image': se deja en False aqui a proposito, ver la segunda pasada.
        if kind != 'image' or starts_new[i]:
            run_kind = kind

    # Segunda pasada, hacia atras: una portadilla de imagen se pega al tramo
    # que la sigue si ese tramo abre capitulo o indice.
    for i in range(n - 2, -1, -1):
        if kinds[i] == 'image' and starts_new[i + 1]:
            starts_new[i] = True
            starts_new[i + 1] = False

    runs, current = [], []
    for i in range(n):
        if current and starts_new[i]:
            runs.append(current)
            current = []
        current.append(i)
    if current:
        runs.append(current)
    return runs


# Motivo legible por el que un fragmento queda SEPARADO del anterior, uno por
# cada valor que puede devolver classify_fragment_start.  Sirve para que el
# informe explique la decision en vez de solo aplicarla en silencio.
_REASON_LABELS = {
    'heading': 'capitulo (titulo h1-h6)',
    'chapter_text': 'capitulo o seccion (texto sin etiqueta, ej. "Capitulo 5", '
                    '"Agradecimientos")',
    'toc': 'indice (no se fusiona con el contenido de alrededor)',
    'image': 'portadilla de imagen (se deja junto al capitulo que decora)',
    'content': 'arranque del fichero original',
}


def explain_tramos(sizes, kinds, max_size):
    """
    Como 'chapter_and_size_bounded_groups', pero devuelve ademas el MOTIVO por
    el que cada tramo quedo separado del anterior -- para poder explicarselo
    en el informe en vez de solo aplicarlo en silencio.

    Devuelve una lista de (indices, motivo).
    """
    out = []
    for run in chapter_runs_from_kinds(kinds):
        motivo = _REASON_LABELS.get(kinds[run[0]], 'arranque del fichero original')
        run_sizes = [sizes[i] for i in run]
        for j, local_idxs in enumerate(size_bounded_subgroups(run_sizes, max_size)):
            idxs = [run[k] for k in local_idxs]
            m = (motivo if j == 0 else
                'corte por tamano (dentro de un tramo mas largo que '
                '--max-merged-kb: {})'.format(motivo))
            out.append((idxs, m))
    return out


def chapter_and_size_bounded_groups(sizes, kinds, max_size):
    """
    Combina los dos limites: no cruzar un arranque de capitulo/indice
    (chapter_runs_from_kinds) y no superar 'max_size' dentro de cada tramo
    resultante (size_bounded_subgroups).  El de capitulo manda primero -- el
    tamano solo entra a repartir en tramos MAS PEQUENOS dentro de un mismo
    capitulo, nunca a unir dos capitulos (o un capitulo y el indice) distintos.

    Devuelve una lista de listas de INDICES en la lista original.  Es
    'explain_tramos' sin el motivo, para quien solo necesite aplicar la
    fusion sin explicarla.
    """
    return [idxs for idxs, _motivo in explain_tramos(sizes, kinds, max_size)]


def _parse_fragment_root(raw_bytes):
    """
    Como _html_to_text pero devuelve el ARBOL en vez de texto, para poder
    pasarlo a classify_fragment_start.  Fuera de Calibre no hay contenedor
    (container.parsed()) que ya lo de hecho, asi que hay que parsear cada
    fragmento suelto -- por eso _mergeable_split_fragment_count() solo se usa
    cuando de verdad hace falta (ver extract_epub_chapters).
    """
    try:
        parser = etree.HTMLParser(recover=True, encoding='utf-8')
        return etree.fromstring(raw_bytes, parser=parser)
    except Exception:
        return None


def _mergeable_split_fragment_count(zf, ordered_names, max_merged_kb=DEFAULT_MAX_MERGED_KB):
    """
    Cuantos ficheros '_split_' DESAPARECERIAN si se aplicara la misma fusion
    que hace merge_splits.py (mismo criterio: classify_fragment_start + tope
    de tamano, ver explain_tramos): para cada grupo de fragmentos consecutivos
    con la misma base, cuenta cuantos quedan absorbidos en el primero de su
    tramo en vez de en fichero propio.

    Sirve para que 'muy_troceado' no salte cuando los '_split_' de un libro
    son en realidad capitulos, secciones (agradecimientos, indice...) o
    portadillas legitimas que la propia herramienta de fusion NUNCA uniria
    entre si: en ese caso avisar de que "esta muy troceado" seria enganoso,
    porque fusionar no cambiaria nada.  Pedido por Yolanda, 2026-08-06: "no
    deberia considerar como muy troceado si el fichero cumple con los
    criterios por lo que no se unirian".

    Solo se llama cuando el conteo bruto de nombres '_split_' ya paso el
    umbral (ver extract_epub_chapters): simular la fusion cuesta parsear cada
    fragmento con lxml, y la inmensa mayoria de libros no tiene ni cerca de
    ese umbral de ficheros '_split_', asi que el caso comun no paga este
    coste.
    """
    total = 0
    for group in group_spine(ordered_names):
        try:
            raws = [zf.read(name) for name in group]
        except Exception:
            # No se puede leer: no se arriesga el aviso, se cuenta como si
            # fuera a fusionarse entero (comportamiento conservador, igual
            # que el conteo bruto anterior).
            total += len(group) - 1
            continue
        sizes = [len(r) for r in raws]
        kinds = [classify_fragment_start(_parse_fragment_root(r)) for r in raws]
        for idxs, _motivo in explain_tramos(sizes, kinds, max_merged_kb * 1024):
            if len(idxs) >= 2:
                total += len(idxs) - 1
    return total


def extract_epub_chapters(epub_path, issues=None):
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
    # 'issues' es un parametro de SALIDA opcional: quien lo pase recibe las
    # senales de mala formacion del EPUB.  Se hace asi, y no cambiando el valor
    # devuelto, para no romper a quien ya llama a esta funcion (el plugin).
    if issues is None:
        issues = []

    with zipfile.ZipFile(epub_path, 'r') as zf:
        all_names = zf.namelist()

        # -- Paso 1a: detectar ítems HTML/XHTML por manifest OPF --
        # Cubre archivos con extensión .xml que el OPF declara como
        # application/xhtml+xml (frecuente en algunos EPUBs generados por
        # herramientas propietarias).
        manifest_html = _get_manifest_html_items(zf, all_names)
        opf_name = next((n for n in all_names if n.lower().endswith('.opf')), None)
        if not opf_name:
            issues.append('sin_opf')
        else:
            try:
                etree.fromstring(zf.read(opf_name))
            except Exception:
                issues.append('opf_ilegible')

        def _is_html_candidate(name):
            return _is_html_file(name) or name in manifest_html

        # -- Paso 1b: separar archivos HTML de sistema (sin leer contenido) --
        system_files = [n for n in all_names if _is_html_candidate(n) and _is_system_file(n)]
        for n in system_files:
            ignored.append({'name': n, 'reason': 'sistema'})

        # -- Paso 2: candidatos reales (HTML no-sistema) --
        html_candidates = {n for n in all_names if _is_html_candidate(n) and not _is_system_file(n)}

        # -- Paso 2b: red de seguridad por CONTENIDO --
        # Si ni la extension ni el manifest han identificado nada, el libro se
        # daria por vacio ("0 capitulos") aunque tenga texto.  Pasa con EPUBs
        # cuyos ficheros no acaban en .html (p. ej. '...html_split_000') y cuyo
        # OPF no se ha podido interpretar.  Antes de rendirse, se mira si el
        # contenido empieza como un documento HTML.
        if not html_candidates:
            for name in all_names:
                if name.endswith('/') or _is_system_file(name):
                    continue
                if os.path.splitext(name)[1].lower() in _BINARY_EXTENSIONS:
                    continue
                try:
                    head = zf.read(name)[:512].lstrip().lower()
                except Exception:
                    continue
                if head.startswith((b'<!doctype html', b'<html', b'<?xml')) and b'<body' in head or \
                   head.startswith((b'<!doctype html', b'<html')):
                    html_candidates.add(name)
            if html_candidates:
                issues.append('rescatado_por_contenido')
                logger.debug('%s: %d ficheros recuperados por contenido',
                             epub_path, len(html_candidates))

        # -- Paso 3: orden canónico (spine OPF) + huérfanos al final --
        spine_ordered = [n for n in _get_spine_order(zf, all_names) if n in html_candidates]
        spine_set     = set(spine_ordered)
        extra_names   = sorted(n for n in html_candidates if n not in spine_set)
        ordered_names = spine_ordered + extra_names

        if html_candidates and not spine_ordered:
            issues.append('sin_spine')
        no_declarados = [n for n in html_candidates if n not in manifest_html
                         and not _is_html_file(n)]
        if no_declarados:
            issues.append('fuera_del_manifest')
        n_split_names = sum(1 for n in html_candidates if '_split_' in n.lower())
        if n_split_names >= DEFAULT_MIN_SPLITS:
            # No basta con contar nombres '_split_': algunos son capitulos,
            # secciones (agradecimientos, indice...) o portadillas legitimas
            # que merge_splits.py NUNCA fusionaria entre si (ver
            # classify_fragment_start). Avisar de 'muy_troceado' en ese caso
            # seria enganoso, porque fusionar no cambiaria nada. Solo se
            # cuenta el problema si de verdad HABRIA fragmentos que
            # desaparecerian al fusionar (Yolanda, 2026-08-06).
            try:
                mergeable = _mergeable_split_fragment_count(zf, ordered_names)
            except Exception:
                logger.debug('No se pudo simular la fusion de %s', epub_path,
                             exc_info=True)
                mergeable = n_split_names  # si algo falla, no se arriesga el aviso
            if mergeable >= DEFAULT_MIN_SPLITS:
                issues.append('muy_troceado')

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

    if not chapters:
        issues.append('sin_texto')
    return chapters, ignored


# ---------------------------------------------------------------------------
# Procedencia de un EPUB: edición editorial vs conversión casera
# ---------------------------------------------------------------------------
# Cuando dos copias tienen EXACTAMENTE el mismo contenido, el criterio para
# quedarse con una u otra ya no puede salir del texto.  Lo que sí distingue a un
# EPUB comprado de una conversión hecha en casa son las marcas que deja cada
# herramienta en el contenedor.
#
# Esta función vive en extractor.py a propósito: la usan TANTO el plugin (ui.py,
# al marcar duplicados) COMO dedupe_cli.py.  Un único sitio, para que no puedan
# discrepar al elegir qué copia se conserva.
#
# Es una HEURÍSTICA, no una certeza: se devuelven también los motivos, para que
# el informe pueda explicar por qué ganó una copia y el usuario pueda discrepar.

ORIGIN_EDITORIAL   = 'editorial'
ORIGIN_CALIBRE     = 'calibre'
ORIGIN_UNKNOWN     = 'desconocido'

# Menor es mejor: se conserva la copia con el rango más bajo.  Un EPUB sin
# ninguna marca se considera mejor que uno con marcas de Calibre, porque Calibre
# casi siempre se firma como generador ('bkp') al convertir.
ORIGIN_RANK = {ORIGIN_EDITORIAL: 0, ORIGIN_UNKNOWN: 1, ORIGIN_CALIBRE: 2}

_FONT_EXTS = ('.otf', '.ttf', '.woff', '.woff2')


def epub_provenance(book_path):
    """
    Devuelve (origen, motivos) para un EPUB.

    origen es 'editorial', 'calibre' o 'desconocido'.  motivos es una lista de
    cadenas cortas, aptas para mostrar en un informe.

    Para ficheros que NO son .epub (p. ej. AZW3) devuelve ('desconocido', []):
    un AZW3 hay que convertirlo con Calibre para leerlo, así que el EPUB
    resultante llevaría siempre marcas de Calibre y la detección no diría nada
    del fichero original.  No se adivina: se admite que no se sabe.
    """
    if os.path.splitext(book_path)[1].lower() != '.epub':
        return ORIGIN_UNKNOWN, []

    calibre_hits, editorial_hits = [], []
    try:
        with zipfile.ZipFile(book_path, 'r') as zf:
            names = zf.namelist()
            lower = [n.lower() for n in names]

            # --- Señales de conversión con Calibre ---
            if any('jacket' in n for n in lower):
                calibre_hits.append('portadilla de Calibre (jacket)')
            if any(('index_split_' in n) or ('part0000' in n) for n in lower):
                calibre_hits.append('ficheros troceados por Calibre')

            # --- Señales de origen editorial (por presencia de ficheros) ---
            if 'meta-inf/encryption.xml' in lower:
                editorial_hits.append('fuentes protegidas (encryption.xml)')
            if any('com.apple.ibooks.display-options' in n for n in lower):
                editorial_hits.append('metadatos de Apple Books')
            if any('itunesmetadata.plist' in n for n in lower):
                editorial_hits.append('metadatos de iTunes')
            if any(n.endswith(_FONT_EXTS) for n in lower):
                editorial_hits.append('tipografías incrustadas')

            # --- Señales dentro del OPF ---
            opf_name = next((n for n in names if n.lower().endswith('.opf')), None)
            if opf_name:
                try:
                    raw = zf.read(opf_name)
                except Exception:
                    raw = b''
                low = raw.lower()
                if b'calibre' in low:
                    # Calibre se firma como generador ('bkp') y escribe
                    # <meta name="calibre:timestamp">.  Es la marca más fiable.
                    if b'calibre:timestamp' in low:
                        calibre_hits.append('calibre:timestamp en el OPF')
                    elif b'bkp' in low or b'calibre-ebook.com' in low:
                        calibre_hits.append('Calibre firmado como generador')
                    else:
                        calibre_hits.append('mención a Calibre en el OPF')
                if b'scheme="isbn"' in low or b"scheme='isbn'" in low or b'urn:isbn' in low:
                    editorial_hits.append('ISBN en el OPF')
                m = re.search(br'<dc:publisher[^>]*>\s*([^<]{2,})</dc:publisher>', raw,
                              re.IGNORECASE)
                if m:
                    pub = m.group(1).strip()
                    if pub and b'calibre' not in pub.lower():
                        editorial_hits.append('editorial: {}'.format(
                            pub.decode('utf-8', 'replace')[:40]))
    except Exception:
        logger.debug('No se pudo leer la procedencia de %s', book_path, exc_info=True)
        return ORIGIN_UNKNOWN, []

    # Las marcas de Calibre mandan: significan que el fichero pasó por una
    # conversión, que es exactamente lo que queremos evitar conservar.
    if calibre_hits:
        return ORIGIN_CALIBRE, calibre_hits
    if editorial_hits:
        return ORIGIN_EDITORIAL, editorial_hits
    return ORIGIN_UNKNOWN, []


def origin_rank(origin):
    """Rango de preferencia (menor gana) para un origen dado."""
    return ORIGIN_RANK.get(origin, ORIGIN_RANK[ORIGIN_UNKNOWN])


def extract_book_chapters(book_path, issues=None):
    """
    Devuelve (chapters, ignored_files).

    'issues' es una lista opcional donde se anotan los problemas de formato
    detectados (claves de ISSUE_LABELS), para poder sugerir que libros conviene
    reconvertir.
    """
    if issues is None:
        issues = []
    ext = os.path.splitext(book_path)[1].lower()
    if ext == '.epub':
        try:
            return extract_epub_chapters(book_path, issues=issues)
        except zipfile.BadZipFile:
            # zipfile no ha encontrado el indice central (fichero truncado o
            # con el indice danado).  Calibre suele poder abrirlo igualmente,
            # asi que se intenta el rescate por conversion antes de rendirse.
            logger.warning('%s: zipfile lo rechaza; intento rescatarlo con '
                           'ebook-convert', book_path)
            issues.append('zip_danado')
            return _convert_and_extract(book_path)
    if ext == '.azw3':
        return extract_azw3_chapters(book_path)
    raise ValueError('Formato no soportado: {}'.format(ext))


def _find_ebook_convert():
    candidates = [
        shutil.which('ebook-convert'),
        os.path.join(os.path.dirname(sys.executable), 'ebook-convert.exe'),
        os.path.join(os.path.dirname(sys.executable), 'ebook-convert'),
    ]
    # Fuera de Calibre (p. ej. dedupe_cli.py con el Python del sistema),
    # sys.executable no apunta a la carpeta de Calibre y ebook-convert puede no
    # estar en el PATH: probamos tambien las rutas de instalación habituales.
    if sys.platform == 'win32':
        for var in ('PROGRAMFILES', 'PROGRAMFILES(X86)'):
            base = os.environ.get(var)
            if base:
                candidates.append(os.path.join(base, 'Calibre2', 'ebook-convert.exe'))
                candidates.append(os.path.join(base, 'Calibre', 'ebook-convert.exe'))
    elif sys.platform == 'darwin':
        candidates.append('/Applications/calibre.app/Contents/MacOS/ebook-convert')
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    raise FileNotFoundError(
        'No se encontró ebook-convert (viene con Calibre). Añade la carpeta de '
        'Calibre al PATH para poder analizar ficheros AZW3.')


# Tope de tiempo para ebook-convert, en segundos.  Un AZW3 con muchas imagenes
# tarda minutos legitimamente, pero uno defectuoso puede no terminar nunca y
# dejaria colgado un escaneo de horas.  dedupe_cli.py lo ajusta con
# --convert-timeout.
CONVERT_TIMEOUT = 900


def _convert_and_extract(book_path):
    """
    Convierte un libro a EPUB con ebook-convert y extrae los capitulos del
    resultado.

    Se usa para los AZW3 (que hay que convertir siempre) y como RESCATE de los
    EPUB que la libreria zipfile de Python rechaza.  Calibre trae su propio
    lector de ZIP, mas tolerante: abre ficheros con el indice central danado que
    zipfile da por invalidos.  Si Calibre puede abrirlo, se aprovecha.

    Aviso: el EPUB reconstruido por Calibre puede trocear los capitulos de otra
    forma, asi que su huella no tiene por que coincidir con la de una copia sana
    del mismo libro.  Se puede perder una coincidencia, pero nunca se inventa
    una: dos libros distintos siguen dando huellas distintas.
    """
    converter = _find_ebook_convert()
    with tempfile.TemporaryDirectory() as tmpdir:
        epub_path = os.path.join(tmpdir, 'temp_conv.epub')
        creationflags = 0
        if sys.platform == 'win32':
            creationflags = subprocess.CREATE_NO_WINDOW
        try:
            proc = subprocess.run(
                [
                    converter, book_path, epub_path,
                    # Evita que Calibre trocee los HTML grandes en fragmentos
                    # 'partNNNN_split_00M.html' que no existen en el AZW3
                    # original y que inflaban los "únicos en B" al comparar
                    # (1 capítulo de A frente a varios fragmentos de B).
                    '--flow-size', '0',
                    '--dont-split-on-page-breaks',
                ],
                # OJO: capture_output SIN text=True, a propósito.
                #
                # ebook-convert imprime el título del libro en su salida, y con
                # text=True Python la decodifica con la codificación local de la
                # consola (cp1252 en Windows). Un título con caracteres fuera de
                # cp1252 hacía saltar UnicodeDecodeError dentro del hilo lector de
                # subprocess, y ese libro quedaba fuera del análisis. Se captura en
                # bytes y se decodifica aquí, con errors='replace', solo si hay que
                # construir un mensaje de error.
                capture_output=True, creationflags=creationflags,
                timeout=CONVERT_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                'ebook-convert paso de {} s con {!r} y se ha cortado. Suele ser '
                'un libro enorme o con muchisimas imagenes; si se repite, el '
                'fichero puede estar defectuoso.'.format(
                    CONVERT_TIMEOUT, os.path.basename(book_path)))
        if proc.returncode != 0:
            err = (proc.stderr or b'').decode('utf-8', 'replace').strip()
            raise RuntimeError('Error convirtiendo {!r}: {}'.format(
                os.path.basename(book_path),
                err[-400:] or 'ebook-convert devolvió {}'.format(proc.returncode)))
        return extract_epub_chapters(epub_path)


def extract_azw3_chapters(azw3_path):
    """Extrae los capitulos de un AZW3 convirtiendolo antes a EPUB."""
    return _convert_and_extract(azw3_path)


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
            href = _unquote_href(href.split('#')[0])
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
