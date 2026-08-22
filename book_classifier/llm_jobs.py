# -*- coding: utf-8 -*-
"""
Rescate con IA en la nube como TAREA DE CALIBRE (ThreadedJob).

IMPORTANTE (patron de all_libraries_stats/jobs.py): el job corre en un hilo del
gestor de tareas y NO debe tocar la base de datos ni objetos Qt (hacerlo crashea
con "Cannot set parent, new parent is in a different thread"). Por eso los datos
de los libros se LEEN antes, en el hilo de la GUI (en action._run_llm_rescue), y
aqui solo se hace red + calculo. Las escrituras se aplican luego en el callback.

Recoge los libros que el clasificador local dejo sin resolver ('[REVISAR]' o
'(sin datos)') — o TODOS si force_all — y los manda en lotes al LLM. Solo
reescribe los que el LLM resuelve con confianza.

La libreria que devuelve la IA se escribe en un campo PROPIO y separado
(`llm_library_field`, por defecto `#libreria_ia`) — nunca en el campo
principal de clasificacion (`ml_library_field`). Ese campo principal solo lo
escriben el clasificador local (`ml_jobs.py`) y su nivel de promocion, que
LEE `llm_library_field` pero jamas escribe en el.
"""
from __future__ import unicode_literals, division, absolute_import, print_function

import re
import time
import math
import traceback
import unicodedata

from calibre_plugins.book_classifier.ml_jobs import _merge_prefixed


def _norm_txt(v):
    """Normaliza para comparar: minusculas, sin acentos, espacios colapsados."""
    s = '' if v is None else str(v)
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return ' '.join(s.lower().split())


def _is_residue(lib_value):
    """True si el valor de libreria es del plugin pero sin resolver."""
    if not lib_value:
        return False
    v = str(lib_value).strip()
    return ('[REVISAR]' in v) or v.endswith('(sin datos)')


# Prefijos "en crudo" (formato PRE-fix_metadata: jerarquia con puntos) que
# codifican directamente la libreria/genero. fix_metadata los canoniza a
# 'Genero · X', pero un libro que aun no ha pasado por fix_metadata puede
# conservarlos tal cual.
_LEAK_RAW_PREFIX_RE = re.compile(
    r'^(_?Biblioteca\.|_?Libreria\.|English\.|Spanish\.|Temas\.|Themes\.|FICTION/)',
    re.IGNORECASE)

# Grupos canonicos 'Grupo · Valor' (ver fix_metadata/tags_map.json) que
# codifican la libreria/genero de forma practicamente 1:1. OJO: fix_metadata
# canoniza TODA la taxonomia (Subgenero/Ambientacion/Tono/Dinamica/Arquetipo/
# Paranormal incluidos) al mismo separador ' · ', asi que ya NO vale usar
# "contiene ·" como señal de fuga -eso descartaria tambien las tags de tropos/
# ambientacion, que son señal legitima y no repiten la clase-. Solo el grupo
# 'Genero' (y los alias estructurales Biblioteca/Libreria) equivale a la
# propia etiqueta #libreria.
_LEAK_GROUPS = ('genero', 'biblioteca', 'libreria')


def _leak_group(tag):
    """Grupo normalizado (sin acentos, minusculas) de una tag canonica
    'Grupo · Valor'; '' si la tag no tiene ese formato."""
    t = str(tag or '')
    if '·' not in t:
        return ''
    grupo = t.split('·', 1)[0].strip()
    grupo = unicodedata.normalize('NFKD', grupo)
    grupo = ''.join(c for c in grupo if not unicodedata.combining(c))
    return grupo.lower()


def _is_leak_tag(tag):
    """True si la tag equivale a la propia libreria/genero que se le pide a
    la IA (grupo 'Genero'/'Biblioteca'/'Libreria' en formato canonico, o el
    prefijo en crudo pre-fix_metadata). Mismo criterio de fuga que en el
    reentrenamiento (ver memory/book-classifier-retrain.md), pero acotado al
    grupo que de verdad es circular: si se manda tal cual a la IA de rescate
    como contexto, puede sesgar #libreria hacia lo que ya diga (a veces mal)
    una tag anterior en vez de basarse en la sinopsis. Las demas tags
    canonicas (Subgenero/Ambientacion/Tono/Dinamica/Arquetipo/Paranormal) NO
    se filtran: son señal de contenido derivada del texto, no un eco de la
    clase.
    """
    t = str(tag or '').strip()
    if not t:
        return False
    if _leak_group(t) in _LEAK_GROUPS:
        return True
    return bool(_LEAK_RAW_PREFIX_RE.match(t))


# ---------------------------------------------------------------------------
# Limpieza de los tags que se mandan al LLM
# ---------------------------------------------------------------------------
# Los tags son la MEJOR senal de genero que hay (son la etiqueta comercial:
# "paranormal-romance", "urban-fantasy"), y el modelo local esta entrenado con
# ellos dentro del texto. Pero vienen de Goodreads o del EPUB tal cual, asi que
# traen dos cosas que estorban: estanterias que hablan del LECTOR y no del
# libro ("to-read", "kindle", "5-stars"), y a veces sesenta tags por libro, que
# en un lote de 20 desequilibran la llamada entera -la sinopsis se corta a 1200
# caracteres y los tags no se cortaban nunca-.

MAX_TAGS_PROMPT = 25

_NOISE_EXACT = {
    # estado de lectura
    'to read', 'toread', 'tbr', 'want to read', 'currently reading', 'read',
    'reading', 'reread', 're read', 'unread', 'dnf', 'did not finish',
    'abandoned', 'leido', 'leidos', 'leyendo', 'por leer', 'sin leer',
    'pendiente', 'pendientes', 'releer', 'terminado', 'abandonado',
    # propiedad, formato y procedencia
    'owned', 'own', 'i own', 'i own it', 'books i own', 'my books',
    'my library', 'mis libros', 'biblioteca personal', 'kindle', 'ebook',
    'e book', 'ebooks', 'audiobook', 'audiobooks', 'audible', 'paperback',
    'hardcover', 'epub', 'mobi', 'azw3', 'pdf', 'calibre', 'comprado',
    'comprados', 'descargado', 'descargados', 'borrowed', 'lent', 'gift',
    'signed', 'bought', 'arc', 'netgalley', 'review copy', 'giveaway',
    # listas y varios sin contenido
    'favorites', 'favourites', 'favoritos', 'favorito', 'favorite',
    'favourite', 'favs', 'wishlist', 'wish list', 'default', 'shelf',
    'book club', 'club de lectura', 'todos', 'varios', 'otros',
}

_NOISE_RE = re.compile(
    r'^(?:'
    r'\d{1,4}'                                   # 42, 2019
    r'|(?:19|20)\d\d[- ]?(?:reads?|lecturas?)?'
    r'|(?:read|leidos?)[- ](?:19|20)\d\d'
    r'|\d[- ]?(?:stars?|estrellas?)'
    r'|shelf[- ]?\d*'
    r')$')

# Palabras que delatan una tag con contenido de genero. Se usa SOLO para
# ordenar cuando hay que recortar, nunca para descartar.
_GENERO_HINT_RE = re.compile(
    r'romance|romantas|fantas|sci-?fi|science fiction|ciencia ficcion|'
    r'mystery|misterio|thriller|suspense|terror|horror|paranormal|vampir|'
    r'werewolf|shifter|lobo|witch|bruja|dragon|\bfae\b|angel|demon|'
    r'historic|contemporan|contemporary|distop|dystop|young adult|juvenil|'
    r'erotic|\bdark\b|cozy|noir|policiac|espionaje|apocalip|apocalyp|zombi|'
    r'steampunk|litrpg|isekai|western|belic|guerra|\bwar\b|crime|crimen|'
    r'detective|space|espacial|alien|magic|magia|mitolog|myth|biograf|ensayo|'
    r'divulgac|autoayuda|no ficcion|nonfiction|non-fiction')


def _is_noise_tag(tag):
    """True si la tag habla del lector (estado, formato, listas) y no del libro."""
    t = _norm_txt(tag).replace('_', ' ').replace('-', ' ')
    t = ' '.join(t.split())
    if not t:
        return True
    return t in _NOISE_EXACT or bool(_NOISE_RE.match(t))


def _tag_score(tag):
    """Cuanto promete una tag como senal de genero (solo para ordenar)."""
    bruto = str(tag or '')
    t = _norm_txt(bruto)
    s = 0
    if '\u00b7' in bruto:          # 'Subgenero · X': ya canonizada por fix_metadata
        s += 4
    if _GENERO_HINT_RE.search(t):
        s += 3
    if ' ' in t or '-' in bruto or '_' in bruto:
        s += 2                      # varias palabras: mas especifica
    if len(t) > 6:
        s += 1
    return s


def tags_para_prompt(tags, quitar=(), max_tags=MAX_TAGS_PROMPT):
    """Los tags que se le mandan al LLM: sin los del propio plugin, sin ruido
    de estanteria y recortados a `max_tags`, los mas informativos primero.

    `quitar` son los prefijos del plugin (`Biblioteca: `, `Tema: `...). Se
    pasan TODOS los configurados, no solo los del campo que hoy apunta a
    'tags': un `Tema: X` que quedo de una configuracion anterior sigue siendo
    el eco de una clasificacion vieja, no una senal del libro.
    """
    limpias = []
    for t in (tags or []):
        st = str(t)
        if not st.strip():
            continue
        if any(st.startswith(p) for p in quitar if p):
            continue
        if _is_leak_tag(st) or _is_noise_tag(st):
            continue
        limpias.append(st)
    if max_tags and len(limpias) > max_tags:
        orden = sorted(range(len(limpias)),
                       key=lambda i: (-_tag_score(limpias[i]), i))
        elegidas = sorted(orden[:max_tags])
        limpias = [limpias[i] for i in elegidas]
    return limpias


# ---------------------------------------------------------------------------
# Clave de identidad "es el mismo libro": autor + titulo (+ idioma)
# ---------------------------------------------------------------------------
# La usan DOS cosas: agrupar las copias de una misma tanda (dedup, abajo) y
# consultar el indice de libros YA clasificados de la biblioteca, para no
# volver a pagarle al LLM una respuesta que ya esta en la base de datos.

_TITLE_PAREN_RE = re.compile(r'\s*[\(\[][^\)\]]*[\)\]]\s*$')
_TITLE_SUB_RE = re.compile(r'\s*[:;]\s+.*$')


def _norm_author(authors):
    """Primer autor, normalizado y con sus palabras ORDENADAS alfabeticamente,
    para que 'Sanderson, Brandon' y 'Brandon Sanderson' -las dos formas que
    conviven en Calibre- den la MISMA clave. Solo el primero: el orden de los
    demas varia entre copias del mismo libro."""
    if isinstance(authors, (list, tuple)):
        first = authors[0] if authors else ''
    else:
        first = str(authors or '').split('&')[0]
    a = _norm_txt(first).replace(',', ' ')
    toks = [t for t in re.split(r'[\s.]+', a) if t]
    return ' '.join(sorted(toks))


def _norm_title(title, loose=False):
    """Titulo normalizado (sin acentos, sin puntuacion, minusculas).

    Con loose=True quita ademas el subtitulo tras ':' y el sufijo entre
    parentesis '(Saga X, 2)'. NUNCA quita las cifras finales: 'Dune 2' y
    'Dune 3' no deben colapsar nunca.
    """
    s = _norm_txt(title)
    if loose:
        prev = s
        while True:
            s2 = _TITLE_PAREN_RE.sub('', s).strip()
            if s2 == s:
                break
            s = s2
        prev = s
        s = _TITLE_SUB_RE.sub('', s).strip() or prev
    s = re.sub(r'[^\w\s]', ' ', s, flags=re.UNICODE)
    return ' '.join(s.split())


def book_key(title, authors, idioma='', loose=False):
    """Clave de identidad de un libro para cruzar copias."""
    return (_norm_author(authors), _norm_title(title, loose), _norm_txt(idioma))


def build_donor_index(rows):
    """Indice de DONANTES: libros de la biblioteca que ya tienen libreria y
    pueden responder por otra copia con el mismo titulo y autor, sin gastar
    una llamada al LLM.

    `rows` lo lee action._prefetch_donor_index en el hilo de la GUI (este
    modulo corre dentro de un job y NO puede tocar la BD). Cada fila:
    {'id', 'title', 'authors', 'idioma', 'libreria', 'temas', 'origen',
    'conf_pct', 'serie', 'motivo'}, con 'libreria'/'temas' ya SIN el
    prefijo de tags. 'motivo' solo viene relleno si 'origen' es 'ia' (el
    clasificador local no razona un motivo).

    Dos niveles de clave:
      - ESTRICTA (titulo completo): responde libreria Y temas.
      - LAXA (sin subtitulo ni '(Saga X, 2)'): responde SOLO la libreria, y
        solo si TODOS los donantes de esa clave coinciden. Los tomos de una
        saga comparten genero -por eso vale-, pero no comparten temas; y dos
        titulos distintos que empiecen igual ('Star Wars: ...') se anulan
        entre si en cuanto discrepan.
    """
    strict, loose = {}, {}
    for r in rows:
        lib = (r.get('libreria') or '').strip()
        if not lib or _is_residue(lib):
            continue
        title, authors, idioma = r.get('title'), r.get('authors'), r.get('idioma')
        ks = book_key(title, authors, idioma)
        if ks not in strict:
            strict[ks] = r
        kl = book_key(title, authors, idioma, loose=True)
        if kl in loose:
            cur = loose[kl]
            if cur is not None and (cur.get('libreria') or '').strip() != lib:
                loose[kl] = None  # discrepancia: esta clave laxa no responde
        else:
            loose[kl] = r
    return {'strict': strict,
            'loose': dict((k, v) for k, v in loose.items() if v is not None)}


def lookup_donor(bk, donors):
    """Respuesta ya conocida para `bk`: (donante, nivel) o (None, '')."""
    if not donors:
        return None, ''
    title, authors, idioma = bk.get('title'), bk.get('authors'), bk.get('idioma')
    for nivel, key in (('estricta', book_key(title, authors, idioma)),
                       ('laxa', book_key(title, authors, idioma, loose=True))):
        d = donors.get('strict' if nivel == 'estricta' else 'loose', {}).get(key)
        if d is not None and d.get('id') != bk.get('id'):
            return d, nivel
    return None, ''


def _llm_already_value(bk, llm_lib_field, llm_prefix_eff):
    """Valor que el rescate con IA ya escribio en su campo dedicado, o None.

    Sin esto el rescate REPITE trabajo: el filtro de residuo mira el campo
    principal (`library_field`), donde el rescate no escribe nunca, asi que un
    libro rescatado ayer sigue con '[REVISAR]' ahi y se volveria a mandar al
    LLM en cada pasada.
    """
    if not llm_lib_field:
        return None
    v = (bk.get('prev') or {}).get(llm_lib_field)
    if isinstance(v, (list, tuple)):
        if not llm_prefix_eff:
            # Columna PROPIA multivalor: no hay prefijo porque TODO su
            # contenido es del plugin. Antes se devolvia None y el libro se
            # reenviaba al LLM en cada pasada aunque ya estuviera rescatado.
            if llm_lib_field != 'tags':
                return next((str(t).strip() for t in v if str(t).strip()), None)
            return None  # 'tags' sin prefijo: indistinguible del resto
        for t in v:
            if str(t).startswith(llm_prefix_eff):
                return str(t)
        return None
    if v is None:
        return None
    v = str(v).strip()
    return v or None


def select_rescue_candidates(books, settings):
    """
    PASO 1 (puro, sin red ni BD ni Qt: puede llamarse desde el hilo de la
    GUI, es rapido). Filtra `books` (ya leidos de la BD en
    action._prefetch_books) a los que hay que mandar al LLM -residuo
    '[REVISAR]'/'(sin datos)', o TODOS si force_all-. Devuelve (candidatos,
    diag): candidatos es una lista de tuplas (bk, item) lista para
    `classify_batch`; diag trae 'with_value' y 'sample' para el diagnostico
    cuando no se encuentra ningun candidato.
    """
    s = settings
    force = bool(s.get('force_all', False))
    lib_field  = s.get('library_field', 'tags')
    mood_field = s.get('mood_field', 'tags')
    lib_prefix  = s.get('library_prefix', 'Biblioteca: ')
    mood_prefix = s.get('mood_prefix', 'Tema: ')
    lib_prefix_eff  = lib_prefix if lib_field == 'tags' else ''
    mood_prefix_eff = mood_prefix if mood_field == 'tags' else ''
    llm_lib_field   = s.get('llm_library_field', '#libreria_ia') or ''
    llm_lib_prefix  = s.get('llm_library_prefix', 'Biblioteca IA: ')
    llm_prefix_eff  = llm_lib_prefix if llm_lib_field == 'tags' else ''
    # Para el prompt se quitan TODOS los prefijos del plugin, apunten hoy a
    # 'tags' o no: los que quedaron de una configuracion anterior son eco de
    # una clasificacion vieja, no senal del libro. Un prefijo vacio no se usa
    # nunca como filtro (`startswith("")` casa con todo).
    quitar = [p for p in (lib_prefix, mood_prefix, llm_lib_prefix,
                          s.get('llm_temas_prefix') or 'Tema IA: ') if p]
    try:
        max_tags = int(s.get('llm_max_tags', MAX_TAGS_PROMPT) or MAX_TAGS_PROMPT)
    except (TypeError, ValueError):
        max_tags = MAX_TAGS_PROMPT

    diag = {'with_value': 0, 'sample': [], 'already_llm': 0}
    cand = []
    for bk in books:
        lib_value = bk.get('lib_value')
        if lib_value:
            diag['with_value'] += 1
            if len(diag['sample']) < 4:
                diag['sample'].append(repr(lib_value)[:70])
        if not force and not _is_residue(lib_value):
            continue
        # Ya rescatado en una pasada anterior: su campo dedicado tiene valor.
        # `force_all` sigue permitiendo reevaluarlo a proposito.
        if not force:
            ya = _llm_already_value(bk, llm_lib_field, llm_prefix_eff)
            if ya and not _is_residue(ya):
                diag['already_llm'] += 1
                continue
        tags = bk.get('tags') or []
        comments = re.sub(r'<[^>]+>', ' ', bk.get('comments') or '')
        comments = re.sub(r'\s+', ' ', comments).strip()
        item = {
            'titulo': bk.get('title') or 'Sin titulo',
            'autor': ', '.join(bk.get('authors') or []),
            'sinopsis': comments,
            'tags': ', '.join(tags_para_prompt(tags, quitar, max_tags)),
        }
        cand.append((bk, item))

    # Deduplicacion: agrupa copias con el mismo autor+titulo+idioma y manda a la
    # IA UN SOLO representante por grupo (el de sinopsis mas larga). El resultado
    # se aplica luego a todas las copias del grupo (ver run_rescue_batch_task).
    groups = {}
    order = []
    for bk, item in cand:
        key = book_key(bk.get('title'), bk.get('authors'), bk.get('idioma'))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append((bk, item))
    deduped = []
    for key in order:
        members = groups[key]
        rep_bk, rep_item = max(
            members, key=lambda mi: len(mi[1].get('sinopsis') or ''))
        rep_bk = dict(rep_bk)
        rep_bk['dup_group'] = [m[0] for m in members]
        deduped.append((rep_bk, rep_item))
    diag['groups'] = len(deduped)
    diag['duplicates_saved'] = len(cand) - len(deduped)
    return deduped, diag


def _write_cfg(s):
    """Ajustes de escritura derivados una sola vez. Los comparten el job del
    LLM y la resolucion por indice, para que no puedan divergir."""
    mood_field = s.get('mood_field', 'tags')
    mood_prefix = s.get('mood_prefix', 'Tema: ')
    llm_lib_field = s.get('llm_library_field', '#libreria_ia')
    llm_lib_prefix = s.get('llm_library_prefix', 'Biblioteca IA: ')
    # Campo PROPIO de los temas de la IA (3.9.0). Vacio = comportamiento
    # anterior: escribir en el campo de temas del motor local, pisando los
    # que puso por regex.
    temas_field = (s.get('llm_temas_field') or '').strip() or mood_field
    temas_prefix = (mood_prefix if temas_field == mood_field
                    else (s.get('llm_temas_prefix') or 'Tema IA: '))
    return {
        'mood_field': mood_field,
        'mood_prefix_eff': mood_prefix if mood_field == 'tags' else '',
        'temas_field': temas_field,
        'temas_prefix_eff': temas_prefix if temas_field == 'tags' else '',
        'llm_lib_field': llm_lib_field,
        'llm_lib_prefix_eff': llm_lib_prefix if llm_lib_field == 'tags' else '',
        'overwrite': s.get('overwrite', True),
        'write_temas': s.get('llm_write_temas', True),
        'write_reason': s.get('llm_write_reason', True),
        'reason_field': (s.get('llm_reason_field') or '').strip(),
        'write_serie': s.get('llm_write_serie', True),
        'write_conf': s.get('llm_write_conf', True),
    }


def _stage_write(writes, field, bid, newvals, prefixes, m, overwrite):
    """Acumula UNA escritura en writes[field][bid].

    Encadena sobre lo que ya hubiera pendiente para ese mismo campo y libro:
    si libreria y temas acaban en el MISMO campo (los dos en `tags`, o el
    campo de temas de la IA dejado vacio), la segunda no puede partir del
    valor previo de la base de datos o borraria la primera.
    """
    base = writes.get(field, {}).get(bid)
    if base is None:
        base = (m.get('prev') or {}).get(field)
    merged = _merge_prefixed(newvals, base, field, prefixes, overwrite)
    writes.setdefault(field, {})[bid] = merged
    return merged


def apply_llm_result(bk, r, cfg, result, revisar='[REVISAR]', tier='IA'):
    """Convierte UNA respuesta -del LLM o copiada del indice- en escrituras
    dentro de `result`, para TODAS las copias del grupo de duplicados.

    % de confianza y motivo se guardan siempre que haya respuesta, aunque no
    llegue al umbral y no se toquen libreria/temas: asi se puede analizar el
    residuo "(revisar)" sin perder la senal de la IA.
    """
    lib = r.get('libreria')
    resolved = bool(lib) and lib != revisar
    temas = r.get('temas') or []
    motivo = (r.get('motivo') or '').strip()
    serie = (r.get('serie') or '').strip() if cfg['write_serie'] else ''
    try:
        conf_pct = int(round(float(r.get('confianza', 0) or 0) * 100))
    except (ValueError, TypeError):
        conf_pct = None
    writes = result['writes_by_field']
    for m in (bk.get('dup_group') or [bk]):
        bid = m['id']
        if resolved:
            _stage_write(writes, cfg['llm_lib_field'], bid,
                         [cfg['llm_lib_prefix_eff'] + lib],
                         [cfg['llm_lib_prefix_eff']], m, cfg['overwrite'])
            if cfg['write_serie'] and serie:
                result['serie_writes'][bid] = serie
            result['rescued'] += 1
            result['dist'][lib] = result['dist'].get(lib, 0) + 1
        # Los TEMAS ya no viajan de paquete con la libreria: desde 3.9.0 van a
        # un campo PROPIO (`llm_temas_field`), asi que se guardan aunque la
        # libreria quede sin resolver -antes colgaban del mismo `if resolved`
        # y se tiraban con el libro, que era el hueco sistematico del hallazgo
        # 4 de coherencia- y ya no pisan los temas del motor local.
        if cfg['write_temas'] and temas:
            _stage_write(writes, cfg['temas_field'], bid,
                         [cfg['temas_prefix_eff'] + t for t in temas],
                         [cfg['temas_prefix_eff']], m, cfg['overwrite'])
            if not resolved:
                result['temas_sin_libreria'] = \
                    result.get('temas_sin_libreria', 0) + 1
        if not resolved:
            # Por que se queda sin resolver: cada causa pide una accion
            # distinta (bajar el umbral, arreglar el catalogo, aceptar la duda
            # o reintentar el lote), asi que no se mezclan en el informe.
            causa = r.get('causa') or 'otro'
            result['revisar_causes'][causa] = \
                result['revisar_causes'].get(causa, 0) + 1
            if causa == 'nombre':
                bruto = (r.get('libreria_raw') or '').strip()[:40] or '(vacio)'
                result['unknown_names'][bruto] = \
                    result['unknown_names'].get(bruto, 0) + 1
        if cfg['write_reason'] and cfg['reason_field'] and motivo:
            result['reason_writes'][bid] = motivo[:300]
        if cfg['write_conf'] and conf_pct is not None:
            result['conf_writes'][bid] = conf_pct
        if len(result['book_details']) < 400:
            result['book_details'].append({
                'title': m.get('title') or '', 'library': lib or revisar,
                'confidence': round(float(r.get('confianza', 0) or 0), 3),
                'uncertain': not resolved, 'moods': temas, 'tier': tier,
                'motivo': motivo,
            })


def _empty_result(label):
    return {
        'label': label, 'candidates': 0, 'rescued': 0, 'errors': 0,
        'cancelled': False, 'writes_by_field': {}, 'dist': {},
        'book_details': [], 'failed': False, 'error': '', 'first_error': '',
        'reason_writes': {}, 'serie_writes': {}, 'conf_writes': {},
        'revisar_causes': {}, 'unknown_names': {}, 'temas_sin_libreria': 0,
        # Consumo acumulado del proveedor. 'cache' son los tokens de entrada
        # que sirvio de su cache de prefijo: la parte fija del prompt son unos
        # 31.000 caracteres que se repiten en cada lote, asi que si esto se
        # queda en cero lote tras lote se esta pagando entera cada vez.
        'tokens': {'in': 0, 'out': 0, 'cache': 0, 'llamadas': 0},
    }


def resolve_from_index(cand, donors, settings):
    """PASO 2 (puro, sin red: corre en el hilo de la GUI). Resuelve los
    candidatos cuyo titulo+autor YA esta clasificado en la biblioteca,
    copiando la respuesta del donante en vez de gastar una llamada al LLM.

    Devuelve (pendientes, result). `result` tiene el mismo formato que
    run_rescue_batch_task, asi que el callback lo aplica con el mismo codigo.
    """
    result = _empty_result('indice')
    result['from_index'] = 0
    result['from_index_loose'] = 0
    if not donors or not cand:
        return cand, result
    cfg = _write_cfg(settings)
    pend = []
    for bk, item in cand:
        d, nivel = lookup_donor(bk, donors)
        if d is None:
            pend.append((bk, item))
            continue
        estricta = (nivel == 'estricta')
        conf = d.get('conf_pct')
        lib_copiada = d.get('libreria')
        # El motivo no se limita a decir DE DONDE se copio: si el donante
        # viene de la IA (no del clasificador local), tambien se lleva su
        # razonamiento original, para poder auditar el residuo sin tener
        # que ir a mirar el libro donante. La clasificacion en si YA se
        # copia (mas abajo, 'libreria': lib_copiada) asi que no hace falta
        # repetirla tambien en el texto del motivo.
        partes_motivo = [
            'Copiado de otra copia ya clasificada (id {}, coincidencia {} '
            'de titulo y autor).'.format(d.get('id'), nivel)]
        if d.get('origen') == 'ia':
            motivo_donante = (d.get('motivo') or '').strip()
            if motivo_donante:
                partes_motivo.append('Motivo original de la IA: {}'.format(motivo_donante))
        r = {
            'libreria': lib_copiada,
            'temas': list(d.get('temas') or []) if estricta else [],
            'serie': (d.get('serie') or '') if estricta else '',
            'confianza': (float(conf) / 100.0) if conf is not None else None,
            'motivo': ' '.join(partes_motivo),
        }
        apply_llm_result(bk, r, cfg, result, tier='indice')
        n = len(bk.get('dup_group') or [bk])
        result['from_index'] += n
        if not estricta:
            result['from_index_loose'] += n
    result['candidates'] = result['from_index']
    return pend, result


def plan_rescue_chunks(cand, settings):
    """
    Reparte los candidatos YA filtrados en jobs. UN job = UNA llamada a la IA.

    No trocea de `llm_batch` en `llm_batch` dejando el resto en un job aparte:
    calcula PRIMERO cuantas llamadas hacen falta y reparte los libros a partes
    iguales entre ellas.

    El motivo es como se paga el prompt. El coste total es
    `llamadas * parte_fija + libros * parte_por_libro`, y la parte fija son
    unos 19.500 caracteres (reglas + mapa de subgeneros + los temas con su
    descripcion). Como la suma de libros no cambia, **solo cuenta el numero de
    llamadas**: un job de sobra cuesta la parte fija entera tanto si lleva 1
    libro como si lleva 19. Por eso no hay un "resto minimo" optimo que
    justifique un job aparte; lo que hay es un TECHO de libros por llamada que
    no conviene pasar (respuesta que se trunca y peor atencion al final del
    lote).

    Con `llm_batch=20` y `llm_batch_tolerancia=0.25` el techo es 25:
      46 candidatos -> 23 + 23  (2 llamadas)   en vez de  20 + 20 + 6  (3)
      21 candidatos -> 21       (1 llamada)    en vez de  20 + 1       (2)
    Nunca se pasa del techo, nunca queda un job de un libro suelto, y el
    numero de llamadas es el minimo posible para ese techo.
    """
    n = len(cand)
    if not n:
        return []
    batch_sz = max(int(settings.get('llm_batch', 20) or 20), 1)
    try:
        tol = float(settings.get('llm_batch_tolerancia', 0.25))
    except (TypeError, ValueError):
        tol = 0.25
    techo = max(batch_sz, int(round(batch_sz * (1.0 + max(tol, 0.0)))))
    k = int(math.ceil(n / float(techo)))
    base, resto = divmod(n, k)
    chunks, i = [], 0
    for j in range(k):
        size = base + (1 if j < resto else 0)
        chunks.append({'cand': cand[i:i + size],
                       'label': 'lote {}-{}'.format(i + 1, i + size)})
        i += size
    return chunks


def run_rescue_batch_task(cand, settings, label, log=None, abort=None, notifications=None):
    """
    Tarea de ThreadedJob para UN job del rescate: procesa un trozo YA
    filtrado de candidatos (de `select_rescue_candidates`) en UNA sola llamada
    a la IA. Varios de estos jobs corren por separado en vez de un unico job
    gigante, asi que cada uno aplica sus escrituras en cuanto termina.

    El tamano del job lo decide `plan_rescue_chunks`, que ya respeta el techo
    de libros por llamada; aqui NO se vuelve a trocear por `llm_batch` -si se
    hiciera, un job de 25 con `llm_batch=20` se partiria en 20+5 y volverian
    las dos llamadas por job que se quitaron en 3.11.0-. El bucle se conserva
    por si a esta funcion la llama alguien con una lista sin planificar.
    """
    s = settings
    result = _empty_result(label)
    result['candidates'] = len(cand)
    cfg = _write_cfg(s)

    provider  = s.get('llm_provider', 'glm')
    key       = (s.get('llm_api_key') or '').strip()
    model     = (s.get('llm_model') or '').strip() or None
    base      = (s.get('llm_base_url') or '').strip() or None
    batch_sz  = max(len(cand), 1)   # 1 job = 1 llamada (ver el docstring)
    min_conf  = float(s.get('llm_min_conf', 0.55) or 0.55)
    write_temas  = s.get('llm_write_temas', True)
    write_serie  = s.get('llm_write_serie', True)
    # El resto de ajustes de escritura (campos, prefijos, overwrite) van en
    # `cfg`, compartido con la resolucion por indice: ver _write_cfg. El
    # rescate escribe SOLO en el campo DEDICADO de la IA (llm_library_field),
    # nunca en el campo principal -eso lo hace, como mucho, el nivel de
    # promocion de ml_jobs.run_classify_chunk_task, que a su vez NUNCA escribe
    # en el campo de la IA-.

    if provider != 'local' and not key:
        result['failed'] = True
        result['error'] = ('No hay clave de API configurada. Ponla en '
                           'Configurar plugin -> Rescate con IA.')
        return result

    temas_vocab = []
    if write_temas:
        try:
            from calibre_plugins.book_classifier.ml_classifier import _load_json
            crudo = _load_json('mood_rules.json') or {}
            # dict {nombre: descripcion}: el LLM solo ve los NOMBRES del
            # vocabulario, nunca la regex, asi que la descripcion es lo unico
            # que puede desambiguar un tema. Con el formato antiguo (valor =
            # regex) queda vacia y el prompt sale como antes.
            temas_vocab = {}
            for nombre, regla in crudo.items():
                temas_vocab[nombre] = ((regla.get('desc') or '')
                                       if isinstance(regla, dict) else '')
        except Exception:
            temas_vocab = []

    from calibre_plugins.book_classifier import llm_rescue_engine as eng

    def is_cancelled():
        try:
            return bool(abort is not None and abort.is_set())
        except Exception:
            return False

    def progress(frac, msg):
        if notifications is not None:
            try:
                notifications.put((float(max(0.0, min(1.0, frac))), msg))
            except Exception:
                pass

    total = len(cand)
    nbatches = int(math.ceil(total / float(max(batch_sz, 1))))
    done = 0
    for b in range(0, total, batch_sz):
        if is_cancelled():
            result['cancelled'] = True
            break
        lote = cand[b:b + batch_sz]
        items = [c[1] for c in lote]
        bi = b // batch_sz + 1
        progress(done / float(max(total, 1)),
                 '{}: lote {}/{} ({}/{} libros) - llamando al modelo...'.format(
                     label, bi, nbatches, done, total))
        try:
            res_list = eng.classify_batch(
                items, provider, key, model=model, base=base,
                temas_vocab=temas_vocab, librerias=eng.LIBRERIAS,
                min_conf=min_conf, pedir_serie=write_serie)
        except Exception as e:
            tb = traceback.format_exc()
            if not result['first_error']:
                result['first_error'] = '{}: {}\n{}'.format(type(e).__name__, e, tb)
                print('[LLM RESCUE] primer error ({}):'.format(label), e)
                print(tb)
            result['errors'] += len(lote)
            done += len(lote)
            continue

        try:
            uso = dict(getattr(eng, 'ULTIMO_USO', {}) or {})
        except Exception:
            uso = {}
        if uso:
            tk = result['tokens']
            tk['in'] += int(uso.get('in', 0))
            tk['out'] += int(uso.get('out', 0))
            tk['cache'] += int(uso.get('cache', 0))
            tk['llamadas'] += 1
            print('[LLM RESCUE] {}: lote {}/{} - entrada {} tokens ({} de '
                  'cache), salida {}'.format(label, bi, nbatches,
                                             uso.get('in', 0),
                                             uso.get('cache', 0),
                                             uso.get('out', 0)))

        for (bk, item), r in zip(lote, res_list):
            apply_llm_result(bk, r, cfg, result, revisar=eng.REVISAR, tier='IA')
        done += len(lote)
        progress(done / float(max(total, 1)),
                 '{}: lote {}/{} completado ({}/{} libros)'.format(
                     label, bi, nbatches, min(done, total), total))
        if b + batch_sz < total:
            time.sleep(1.0)

    return result
