#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dedupe_cli.py -- Duplicados EXACTOS (100 %) en una o MUCHAS bibliotecas de
Calibre, sin abrir la interfaz de Calibre.

Reutiliza el motor del plugin Ebook Comparator (extractor.py + comparator.py)
pero cambia la estrategia: en lugar de emparejar libros por titulo/autor y
comparar cada pareja, extrae CADA libro UNA vez, calcula su huella de contenido
(comparator.book_fingerprint) y agrupa por huella.  Asi encuentra duplicados
exactos aunque el titulo y el autor no se parezcan en nada, y aunque las copias
esten en bibliotecas distintas.

Flujo en DOS FASES (la parte lenta no se repite):

  1. ESCANEO -- lento, en solo lectura, puedes tener Calibre abierto:

       dedupe.cmd --root "D:\\Bibliotecas"

     Produce un informe HTML y un plan JSON con las copias sobrantes.

  2. BORRADO -- segundos, con Calibre cerrado:

       dedupe.cmd --apply duplicados_20260726.plan.json

     Lee el plan, comprueba que nada ha cambiado desde el escaneo, respalda cada
     metadata.db y delega el borrado en Calibre.

El script NUNCA escribe en metadata.db: lo abre en modo solo lectura y el
borrado lo ejecuta 'calibredb remove' (o api.remove_books bajo calibre-debug),
sin --permanent.

AVISO comprobado en la practica: eso NO garantiza poder deshacerlo desde
Calibre.  En una biblioteca real, tras borrar con calibredb, "Restaurar libros
borrados recientemente" apareció VACIO (0 libros, 0 formatos).  Ademas la propia
opcion "Permanently delete after" de Calibre puede estar en "on close", que
vacia la papelera al cerrar el programa.  Por eso la copia que de verdad
protege es la que hace este script antes de borrar: la carpeta exportada
(ficheros + portada + OPF) y el respaldo de metadata.db.
"""

from __future__ import absolute_import, division, print_function, unicode_literals

import argparse
import codecs
import hashlib
import html
import json
import logging
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from collections import defaultdict, OrderedDict

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# Los informes y planes NO deben caer en la carpeta del plugin: el generador de
# ZIP empaqueta todo lo que hay ahi, y un informe suelto de varios MB acabaria
# dentro del plugin instalado en Calibre.  Por defecto van a 'dedupe_out/' en la
# raiz del repositorio (el padre de la carpeta del plugin), que esta ignorada
# por git.  Se puede cambiar con --out-dir.
_DEFAULT_OUT_DIR = os.path.join(os.path.dirname(_HERE), 'dedupe_out')

SUPPORTED_FORMATS = ('EPUB', 'AZW3')
PLAN_VERSION = 1

logger = logging.getLogger('dedupe_cli')


# ---------------------------------------------------------------------------
# Entorno
# ---------------------------------------------------------------------------

def running_inside_calibre():
    try:
        import calibre  # noqa: F401
        return True
    except Exception:
        return False


def _calibre_config_dir():
    env = os.environ.get('CALIBRE_CONFIG_DIRECTORY')
    if env:
        return env
    if sys.platform == 'win32':
        base = os.environ.get('APPDATA') or os.path.expanduser('~')
        return os.path.join(base, 'calibre')
    if sys.platform == 'darwin':
        return os.path.expanduser('~/Library/Preferences/calibre')
    return os.path.expanduser('~/.config/calibre')


def calibre_current_library():
    """La biblioteca que Calibre tiene/tuvo abierta, o None."""
    if running_inside_calibre():
        try:
            from calibre.utils.config import prefs
            if prefs['library_path']:
                return os.path.abspath(prefs['library_path'])
        except Exception:
            pass
    cfg = _calibre_config_dir()
    for name in ('global.py.json', 'global.py'):
        fn = os.path.join(cfg, name)
        if not os.path.exists(fn):
            continue
        try:
            raw = codecs.open(fn, 'r', 'utf-8').read()
        except Exception:
            continue
        if name.endswith('.json'):
            try:
                path = json.loads(raw).get('library_path')
                if path:
                    return os.path.abspath(path)
            except Exception:
                pass
        else:
            m = re.search(r"library_path\s*=\s*[uU]?['\"](.+?)['\"]", raw)
            if m:
                try:
                    return os.path.abspath(
                        m.group(1).encode('utf-8').decode('unicode_escape'))
                except Exception:
                    return os.path.abspath(m.group(1))
    return None


# ---------------------------------------------------------------------------
# Comprobacion del entorno
# ---------------------------------------------------------------------------

def check_lxml():
    """
    lxml es OBLIGATORIO, no opcional.

    extractor._html_to_text usa el parser HTML de lxml y, si falla, cae a un
    fallback por expresion regular que mete en el texto el contenido de
    <style>, <script> y <title>.  Ese texto distinto produce hashes distintos,
    con dos consecuencias graves:

      - Las huellas de una pasada sin lxml NO son comparables con las de una
        pasada con lxml (ni con las del plugin dentro de Calibre).
      - Dos copias del mismo libro que solo difieran en la hoja de estilos
        dejan de detectarse como duplicados.

    Por eso se aborta con instrucciones en vez de dar resultados peores en
    silencio.
    """
    try:
        import lxml  # noqa: F401
        return True
    except ImportError:
        pass
    exe = sys.executable or 'python'
    raise SystemExit(
        'Falta el modulo lxml, que este script necesita para leer los EPUB.\n'
        '\nInterprete en uso: {exe}\n'
        '\nDos formas de arreglarlo:\n'
        '\n  1) Usar el interprete de Calibre, que ya trae lxml (sin instalar nada):\n'
        '       calibre-debug -e "{script}" -- --root "D:\\Bibliotecas"\n'
        '     El lanzador dedupe.cmd hace esto solo si tu Python no tiene lxml.\n'
        '\n  2) Instalarlo en tu Python (mas rapido: permite paralelizar por procesos):\n'
        '       "{exe}" -m pip install lxml\n'
        '\nNo funciono sin lxml a proposito: el texto extraido seria distinto y se\n'
        'perderian duplicados reales.'.format(
            exe=exe, script=os.path.join(_HERE, 'dedupe_cli.py')))


def inspect_book(path):
    """
    Diagnostico de UN libro: por que se extraen (o no) sus capitulos.

    Pensado para los libros que el informe marca como "sin contenido
    comparable": muestra el contenido del ZIP, si el OPF se puede interpretar,
    que items declara y que se descarto y por que.
    """
    import extractor
    print('Fichero: {}'.format(path))
    if not os.path.exists(path):
        print('  NO EXISTE.')
        return 1
    print('Tamano : {}'.format(human_size(_safe_size(path))))
    ext = os.path.splitext(path)[1].lower()
    print('Formato: {}'.format(ext or '(sin extension)'))

    if ext == '.epub':
        import zipfile
        try:
            zf = zipfile.ZipFile(path)
        except Exception as exc:
            print('  NO es un ZIP valido: {}'.format(exc))
            return 1
        names = zf.namelist()
        print('\nContenido del ZIP: {} entradas'.format(len(names)))
        for n in names[:40]:
            print('   {}'.format(n))
        if len(names) > 40:
            print('   ... y {} mas'.format(len(names) - 40))

        opf = next((n for n in names if n.lower().endswith('.opf')), None)
        print('\nOPF: {}'.format(opf or 'NO ENCONTRADO'))
        if opf:
            try:
                from lxml import etree
                etree.fromstring(zf.read(opf))
                print('  se interpreta correctamente')
            except Exception as exc:
                print('  NO SE PUEDE INTERPRETAR: {}'.format(exc))
                print('  (sin OPF legible hay que reconocer los capitulos por '
                      'extension o por contenido)')
        items = extractor._get_manifest_html_items(zf, names)
        print('  items HTML segun el manifest: {}'.format(len(items)))
        for n in sorted(items)[:10]:
            print('     {}'.format(n))

    issues = []
    chapters, ignored = extractor.extract_book_chapters(path, issues=issues)
    print('\nCapitulos extraidos: {}'.format(len(chapters)))
    for n, text in list(chapters.items())[:5]:
        print('   {:50} {} caracteres'.format(n[:50], len(text)))
    if len(chapters) > 5:
        print('   ... y {} mas'.format(len(chapters) - 5))
    print('\nDescartados: {}'.format(len(ignored)))
    reasons = defaultdict(list)
    for i in ignored:
        reasons[i['reason']].append(i['name'])
    for reason, items in sorted(reasons.items()):
        print('   {} ({}): {}'.format(reason, len(items), ', '.join(items[:4])))

    print('\nProblemas de formato: {}'.format(
        ', '.join(extractor.ISSUE_LABELS.get(i, i) for i in issues) or 'ninguno'))

    # Diagnostico especifico de 'muy_troceado': por que SI o NO se marca, grupo
    # a grupo y fragmento a fragmento, con el MISMO criterio que usaria
    # merge_splits.py al fusionar de verdad. Pensado para pegar aqui la salida
    # cuando un libro se marca (o se deja de marcar) de forma inesperada.
    if ext == '.epub':
        try:
            with zipfile.ZipFile(path) as zf2:
                names2 = zf2.namelist()
                manifest_html = extractor._get_manifest_html_items(zf2, names2)
                cand = {n for n in names2
                       if (extractor._is_html_file(n) or n in manifest_html)
                       and not extractor._is_system_file(n)}
                spine_ord = [n for n in extractor._get_spine_order(zf2, names2) if n in cand]
                extra = sorted(n for n in cand if n not in set(spine_ord))
                ordered2 = spine_ord + extra
                n_split = sum(1 for n in cand if '_split_' in n.lower())
                print('\nFicheros HTML: {} | con "_split_" en el nombre: {} '
                     '(umbral: {})'.format(len(cand), n_split, extractor.DEFAULT_MIN_SPLITS))
                if n_split:
                    groups = extractor.group_spine(ordered2)
                    print('Grupos de fragmentos consecutivos con la misma base: {}'.format(len(groups)))
                    total_mergeable = 0
                    for gi, g in enumerate(groups, 1):
                        raws = []
                        for n in g:
                            try:
                                raws.append(zf2.read(n))
                            except Exception:
                                raws.append(b'')
                        sizes = [len(r) for r in raws]
                        kinds = [extractor.classify_fragment_start(
                                    extractor._parse_fragment_root(r)) for r in raws]
                        print('\n  Grupo {}: {} fragmentos'.format(gi, len(g)))
                        for n, k, s in zip(g, kinds, sizes):
                            print('     {:50} {:8}  {}'.format(n[-50:], human_size(s), k))
                        tramos = extractor.explain_tramos(
                            sizes, kinds, extractor.DEFAULT_MAX_MERGED_KB * 1024)
                        for idxs, motivo in tramos:
                            mark = ' -> SE FUSIONARIAN' if len(idxs) >= 2 else ''
                            print('     tramo {}: {}{}'.format(
                                [g[i][-30:] for i in idxs], motivo, mark))
                            if len(idxs) >= 2:
                                total_mergeable += len(idxs) - 1
                    print('\nFragmentos que DESAPARECERIAN al fusionar: {} '
                         '(umbral: {})'.format(total_mergeable, extractor.DEFAULT_MIN_SPLITS))
                    print('-> {}'.format(
                        'SI se marcaria muy_troceado' if total_mergeable >= extractor.DEFAULT_MIN_SPLITS
                        else 'NO se marcaria muy_troceado (son capitulos/secciones legitimas)'))
        except Exception as exc:
            print('\n  (no se pudo hacer el diagnostico de fragmentos: {})'.format(exc))

    origin, why = extractor.epub_provenance(path)
    print('\nProcedencia: {} {}'.format(origin, why or ''))
    import comparator
    print('Huella     : {}'.format(comparator.book_fingerprint(chapters) or 'NINGUNA'))
    if not chapters:
        print('\n-> Este libro NO entra en la comparacion. Pega esta salida para')
        print('   que se pueda ajustar la deteccion.')
    return 0


def doctor():
    """Diagnostico del entorno: que interprete, si hay lxml, si hay calibredb."""
    print('Interprete      : {}'.format(sys.executable))
    print('Version         : {}'.format(sys.version.split()[0]))
    print('Dentro de Calibre: {}'.format('si' if running_inside_calibre() else 'no'))
    try:
        import lxml.etree as _le
        print('lxml            : si ({})'.format(
            getattr(_le, '__version__', 'version desconocida')))
    except ImportError:
        print('lxml            : NO  <-- imprescindible, mira el mensaje de error')
    try:
        import extractor, comparator  # noqa: F401
        print('motor del plugin: si (extractor.py + comparator.py)')
    except Exception as exc:
        print('motor del plugin: NO ({})'.format(exc))
    cdb = find_calibredb()
    print('calibredb       : {}'.format(cdb or 'NO encontrado (necesario para --apply)'))
    print('nucleos de CPU  : {}'.format(os.cpu_count()))
    cur = calibre_current_library()
    print('biblioteca abierta en Calibre: {}'.format(cur or 'no detectada'))


# ---------------------------------------------------------------------------
# Descubrimiento de bibliotecas
# ---------------------------------------------------------------------------

def is_calibre_library(path):
    return os.path.isfile(os.path.join(path, 'metadata.db'))


def discover_libraries(roots, max_depth=6):
    """
    Busca bibliotecas de Calibre bajo cada carpeta de 'roots'.

    Una biblioteca es una carpeta con metadata.db.  Al encontrar una NO se sigue
    bajando por dentro: las subcarpetas de una biblioteca son las carpetas de
    autor/libro, no bibliotecas anidadas, y recorrerlas en una biblioteca grande
    cuesta mucho tiempo para nada.

    'max_depth' limita cuanto se baja desde cada raiz, para no barrer un disco
    entero por accidente.
    """
    found = []
    seen = set()
    for root in roots:
        root = os.path.abspath(os.path.expanduser(root))
        if not os.path.isdir(root):
            logger.warning('No es una carpeta: %s', root)
            continue
        root_depth = root.rstrip(os.sep).count(os.sep)
        for dirpath, dirnames, _filenames in os.walk(root):
            depth = dirpath.rstrip(os.sep).count(os.sep) - root_depth
            if depth >= max_depth:
                dirnames[:] = []
                continue
            # No entrar en carpetas ocultas ni en las de sistema
            dirnames[:] = [d for d in dirnames
                           if not d.startswith('.') and d not in ('__pycache__',)]
            if is_calibre_library(dirpath):
                real = os.path.realpath(dirpath)
                if real not in seen:
                    seen.add(real)
                    found.append(dirpath)
                dirnames[:] = []   # no bajar dentro de la biblioteca
    found.sort()
    return found


def resolve_libraries(explicit_libraries, roots):
    """
    Decide la lista final de bibliotecas a analizar.

    Prioridad: --library (una o varias) + --root (una o varias).  Si no se pasa
    ninguna, se usa la biblioteca que Calibre tiene abierta.
    """
    libs = []
    for lib in (explicit_libraries or ()):
        p = os.path.abspath(os.path.expanduser(lib))
        if not is_calibre_library(p):
            raise SystemExit('No hay metadata.db en {!r}: no parece una '
                             'biblioteca de Calibre.'.format(p))
        libs.append(p)

    if roots:
        libs.extend(discover_libraries(roots))

    if not libs:
        env = os.environ.get('CALIBRE_LIBRARY_PATH')
        cand = env or calibre_current_library()
        if cand and is_calibre_library(cand):
            libs.append(os.path.abspath(cand))

    # Quitar duplicados conservando el orden (el orden importa: desempata al
    # decidir en que biblioteca se conserva la copia).
    out, seen = [], set()
    for p in libs:
        real = os.path.realpath(p)
        if real not in seen:
            seen.add(real)
            out.append(p)
    return out


# ---------------------------------------------------------------------------
# Carga de libros
# ---------------------------------------------------------------------------
# El id de Calibre solo es unico DENTRO de su biblioteca: dos bibliotecas
# distintas tienen ambas un libro con id 1.  Con varias bibliotecas en juego,
# todo se indexa por 'uid' = "<indice de biblioteca>:<id>".

def _safe_size(path):
    try:
        return os.path.getsize(path)
    except Exception:
        return 0


def _safe_mtime(path):
    try:
        return int(os.path.getmtime(path))
    except Exception:
        return 0


def load_books_calibre_api(library_path):
    from calibre.library import db as calibre_db_factory
    lib = calibre_db_factory(library_path)
    api = getattr(lib, 'new_api', lib)
    books = []
    for book_id in api.all_book_ids():
        try:
            fmts = {f.upper() for f in (api.formats(book_id) or ())}
        except Exception:
            fmts = set()
        chosen_fmt, chosen_path = None, None
        format_paths = {}
        for fmt in SUPPORTED_FORMATS:
            if fmt in fmts:
                try:
                    p = api.format_abspath(book_id, fmt)
                except Exception:
                    p = None
                if p and os.path.exists(p):
                    format_paths[fmt] = p
                    if chosen_fmt is None:
                        chosen_fmt, chosen_path = fmt, p
        if not chosen_fmt:
            continue
        try:
            title = (api.field_for('title', book_id) or '').strip()
        except Exception:
            title = ''
        try:
            authors = api.field_for('authors', book_id) or ()
            authors = ' & '.join(authors) if isinstance(authors, (list, tuple)) else str(authors)
        except Exception:
            authors = ''
        try:
            has_cover = bool(api.field_for('cover', book_id))
        except Exception:
            has_cover = False
        books.append({
            'id': book_id, 'title': title, 'authors': authors,
            'format': chosen_fmt, 'path': chosen_path,
            'size': _safe_size(chosen_path), 'mtime': _safe_mtime(chosen_path),
            'formats': sorted(fmts), 'has_cover': has_cover,
            'format_paths': format_paths,
        })
    try:
        lib.close()
    except Exception:
        pass
    return books


def load_books_sqlite(library_path):
    """Lee metadata.db en SOLO LECTURA (mode=ro): seguro con Calibre abierto."""
    dbfile = os.path.join(library_path, 'metadata.db')
    if not os.path.exists(dbfile):
        raise SystemExit('No encuentro metadata.db en {!r}.'.format(library_path))

    uri = 'file:{}?mode=ro'.format(
        dbfile.replace('?', '%3f').replace('#', '%23'))
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""
            SELECT b.id AS id, b.title AS title, b.path AS bookpath,
                   b.has_cover AS has_cover, d.format AS format, d.name AS name,
                   d.uncompressed_size AS usize
            FROM books b JOIN data d ON d.book = b.id
        """).fetchall()
        authors_by_book = defaultdict(list)
        for r in conn.execute("""
            SELECT bal.book AS book, a.name AS name
            FROM books_authors_link bal JOIN authors a ON a.id = bal.author
            ORDER BY bal.id
        """):
            authors_by_book[r['book']].append((r['name'] or '').replace('|', ','))
    finally:
        conn.close()

    per_book = defaultdict(lambda: {'formats': {}, 'meta': None})
    for r in rows:
        e = per_book[r['id']]
        e['formats'][(r['format'] or '').upper()] = (r['name'], r['usize'])
        if e['meta'] is None:
            e['meta'] = (r['title'], r['bookpath'], r['has_cover'])

    books = []
    for book_id, e in per_book.items():
        title, bookpath, has_cover = e['meta']
        fmts = e['formats']
        chosen_fmt, chosen_path, chosen_size = None, None, 0
        format_paths = {}
        for fmt in SUPPORTED_FORMATS:
            if fmt in fmts:
                name, usize = fmts[fmt]
                p = os.path.join(library_path,
                                 (bookpath or '').replace('/', os.sep),
                                 '{}.{}'.format(name, fmt.lower()))
                if os.path.exists(p):
                    format_paths[fmt] = p
                    if chosen_fmt is None:
                        chosen_fmt, chosen_path, chosen_size = fmt, p, usize
        if not chosen_fmt:
            continue
        books.append({
            'id': book_id, 'title': (title or '').strip(),
            'authors': ' & '.join(authors_by_book.get(book_id, ())),
            'format': chosen_fmt, 'path': chosen_path,
            'size': _safe_size(chosen_path) or (chosen_size or 0),
            'mtime': _safe_mtime(chosen_path),
            'formats': sorted(fmts.keys()), 'has_cover': bool(has_cover),
            'format_paths': format_paths,
        })
    return books


def load_all_books(libraries, force_backend=None, limit_per_library=0):
    """
    Carga los libros de TODAS las bibliotecas indicadas.

    Devuelve (books, backend).  Cada libro lleva 'library' (ruta), 'lib_index'
    (posicion en la lista, que desempata al elegir la copia a conservar) y
    'uid' (clave global unica).
    """
    want = force_backend or ('calibre' if running_inside_calibre() else 'sqlite')
    all_books = []
    backend_used = 'sqlite'
    for idx, lib in enumerate(libraries):
        books = None
        if want == 'calibre':
            try:
                books = load_books_calibre_api(lib)
                backend_used = 'calibre-api'
            except Exception as exc:
                logger.warning('API de Calibre no disponible (%s); uso sqlite3.', exc)
        if books is None:
            books = load_books_sqlite(lib)
        books.sort(key=lambda b: b['id'])
        if limit_per_library:
            books = books[:limit_per_library]
        for b in books:
            b['library'] = lib
            b['lib_index'] = idx
            b['uid'] = '{}:{}'.format(idx, b['id'])
        print('  [{}/{}] {}  ->  {} libros con EPUB/AZW3'.format(
            idx + 1, len(libraries), lib, len(books)))
        all_books.extend(books)
    return all_books, backend_used


# ---------------------------------------------------------------------------
# Huella de contenido: una extraccion por libro
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Cache persistente de huellas
# ---------------------------------------------------------------------------
# Un escaneo de miles de libros cuesta minutos u horas. Sin cache, repetirlo
# (porque cambio una opcion, porque lo interrumpi, o porque quiero rehacer el
# informe) vuelve a leer y convertir todo. La cache guarda la huella por
# (ruta, tamano, mtime), asi que un segundo pase solo trabaja sobre los libros
# nuevos o modificados.
#
# Invalidacion automatica: se almacena el hash del CODIGO de extractor.py y
# comparator.py. Si cambian, las huellas viejas dejan de ser comparables con las
# nuevas (paso de verdad al arreglar la conversion de AZW3), asi que la cache se
# descarta entera en vez de mezclar resultados de dos motores distintos.

CACHE_NAME = 'fingerprint_cache.json'


def engine_signature():
    """Hash del codigo de extraccion, para invalidar la cache si cambia."""
    h = hashlib.md5()
    for name in ('extractor.py', 'comparator.py'):
        try:
            with open(os.path.join(_HERE, name), 'rb') as fh:
                h.update(fh.read())
        except Exception:
            h.update(name.encode('utf-8'))
    return h.hexdigest()


def load_cache(cache_path):
    """
    Devuelve {ruta: registro} valido, o {} si no sirve.

    Informa SIEMPRE de lo que pasa con la cache, por pantalla y no por el log:
    "no la esta usando" es una queja habitual y sin este mensaje hay que
    adivinar si el fichero no existia, estaba ilegible o era de otro motor.
    """
    if not cache_path:
        print('Cache: desactivada (--no-cache).')
        return {}
    print('Cache: {}'.format(cache_path))
    if not os.path.exists(cache_path):
        print('  no existe todavia; se creara durante este escaneo.')
        return {}
    try:
        with codecs.open(cache_path, 'r', 'utf-8') as fh:
            data = json.load(fh)
    except Exception as exc:
        print('  ILEGIBLE ({}): la ignoro y la reescribo.'.format(exc))
        return {}
    books = data.get('books') or {}
    if data.get('engine') != engine_signature():
        print('  es de otra version del motor de extraccion ({} entradas): la '
              'descarto.'.format(len(books)))
        print('  (paso al cambiar extractor.py o comparator.py: las huellas de '
              'motores distintos no son comparables)')
        return {}
    print('  valida, guardada el {}, {} entradas.'.format(
        data.get('saved', '?'), len(books)))
    return books


def save_cache(cache_path, entries):
    if not cache_path:
        return
    try:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        tmp = cache_path + '.tmp'
        with codecs.open(tmp, 'w', 'utf-8') as fh:
            json.dump({'engine': engine_signature(),
                       'saved': time.strftime('%Y-%m-%d %H:%M:%S'),
                       'books': entries}, fh)
        if os.path.exists(cache_path):
            os.remove(cache_path)
        os.rename(tmp, cache_path)
    except Exception as exc:
        # Un fallo aqui significa repetir horas de escaneo la proxima vez: se
        # avisa por pantalla, no en el log, donde pasaria desapercibido.
        print('AVISO: no se pudo guardar la cache en {}: {}'.format(cache_path, exc))


def _cache_key(book):
    return os.path.realpath(book['path'])


def split_cached(books, cache):
    """
    Separa los libros ya conocidos de los que hay que leer.

    Un libro solo se da por cacheado si coinciden tamano Y mtime: cualquier
    reconversion o reemplazo del fichero lo devuelve a la cola.
    """
    hits, misses = {}, []
    for b in books:
        rec = cache.get(_cache_key(b))
        if (rec and rec.get('size') == b['size'] and rec.get('mtime') == b['mtime']):
            hits[b['uid']] = {
                'uid': b['uid'], 'sha1': rec.get('sha1'),
                'fingerprint': rec.get('fingerprint'),
                'n_chapters': rec.get('n_chapters') or 0,
                'n_ignored': rec.get('n_ignored') or 0,
                'error': rec.get('error'), 'format': b['format'],
                'origin': rec.get('origin') or 'desconocido',
                'origin_reasons': rec.get('origin_reasons') or [],
                'issues': rec.get('issues') or [],
                'elapsed': 0.0, 'cached': True,
            }
        else:
            misses.append(b)
    return hits, misses


def update_cache(cache, books, fps):
    by_uid = {b['uid']: b for b in books}
    for uid, r in fps.items():
        if r.get('cached'):
            continue
        b = by_uid.get(uid)
        if not b:
            continue
        cache[_cache_key(b)] = {
            'size': b['size'], 'mtime': b['mtime'], 'sha1': r.get('sha1'),
            'fingerprint': r.get('fingerprint'),
            'n_chapters': r.get('n_chapters'), 'n_ignored': r.get('n_ignored'),
            'error': r.get('error'), 'origin': r.get('origin'),
            'origin_reasons': r.get('origin_reasons') or [],
            'issues': r.get('issues') or [],
        }
    return cache


def fingerprint_one(task):
    """
    Worker de nivel superior (necesario para ProcessPoolExecutor).

    Recibe (uid, path, fmt) y devuelve, ademas de la huella, el formato y el
    tiempo empleado.  Medir por libro es lo que permite ver si el escaneo se va
    en los AZW3 (que hay que convertir llamando a ebook-convert, mucho mas caro
    que abrir un EPUB) o en la lectura de disco.
    """
    uid, path, fmt = task
    t0 = time.time()
    out = {'uid': uid, 'sha1': None, 'fingerprint': None, 'format': fmt,
           'n_chapters': 0, 'n_ignored': 0, 'error': None, 'elapsed': 0.0,
           'cached': False, 'origin': 'desconocido', 'origin_reasons': [],
           'issues': []}
    try:
        import extractor
        import comparator
        out['sha1'] = extractor.file_sha1(path)
        # Procedencia (editorial vs conversion casera) en la misma pasada: el
        # fichero ya esta abierto, asi que no cuesta E/S adicional.
        origin, reasons = extractor.epub_provenance(path)
        out['origin'] = origin
        out['origin_reasons'] = reasons
        issues = []
        chapters, ignored = extractor.extract_book_chapters(path, issues=issues)
        out['issues'] = sorted(set(issues))
        out['n_chapters'] = len(chapters)
        out['n_ignored'] = len(ignored)
        out['fingerprint'] = comparator.book_fingerprint(chapters)
    except Exception as exc:
        out['error'] = '{}: {}'.format(type(exc).__name__, exc)
    out['elapsed'] = time.time() - t0
    return out


def compute_fingerprints(books, jobs=None, progress_every=25, use_processes=True,
                         checkpoint_every=100, on_checkpoint=None, results=None):
    """
    Calcula la huella de todos los libros, en paralelo.

    'on_checkpoint' se llama cada 'checkpoint_every' libros con los
    resultados acumulados.  Sirve para ir guardando la cache: en un escaneo
    de miles de libros, interrumpirlo no debe tirar a la basura el trabajo
    hecho hasta ese momento.

    'results' permite al llamante pasar SU propio diccionario de resultados.
    Es lo que hace que un Ctrl-C conserve lo ya calculado: si el diccionario
    fuera local, la excepcion se llevaria por delante todo el trabajo.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    tasks = [(b['uid'], b['path'], b['format']) for b in books]
    total = len(tasks)
    if results is None:
        results = {}
    if jobs is None:
        jobs = max(1, (os.cpu_count() or 2))
    jobs = max(1, min(jobs, total or 1))
    started = time.time()

    def _tick(done):
        if done == total or done % progress_every == 0:
            el = time.time() - started
            rate = done / el if el > 0 else 0
            eta = (total - done) / rate if rate > 0 else 0
            sys.stderr.write('\r  huellas: {}/{}  ({:.1f} libros/s, faltan ~{:.0f}s)   '
                             .format(done, total, rate, eta))
            sys.stderr.flush()

    if jobs == 1 or total == 0:
        for n, t in enumerate(tasks, 1):
            r = fingerprint_one(t)
            results[r['uid']] = r
            _tick(n)
            if on_checkpoint and n % checkpoint_every == 0:
                on_checkpoint(results)
    else:
        executor_cls = ThreadPoolExecutor
        if use_processes:
            try:
                from concurrent.futures import ProcessPoolExecutor
                executor_cls = ProcessPoolExecutor
            except Exception:
                pass
        try:
            with executor_cls(max_workers=jobs) as ex:
                futs = [ex.submit(fingerprint_one, t) for t in tasks]
                for n, fut in enumerate(as_completed(futs), 1):
                    r = fut.result()
                    results[r['uid']] = r
                    _tick(n)
                    if on_checkpoint and n % checkpoint_every == 0:
                        on_checkpoint(results)
        except Exception as exc:
            if executor_cls is not ThreadPoolExecutor:
                logger.warning('Pool de procesos no disponible (%s); uso hilos.', exc)
                sys.stderr.write('\n')
                return compute_fingerprints(books, jobs=jobs,
                                            progress_every=progress_every,
                                            use_processes=False,
                                            checkpoint_every=checkpoint_every,
                                            on_checkpoint=on_checkpoint,
                                            results=results)
            raise
    sys.stderr.write('\n')
    return results


def timing_summary(fps):
    """
    Desglose del coste del escaneo por formato.

    Sirve para responder "por que va a N libros/s": si la mediana de AZW3 es
    ordenes de magnitud mayor que la de EPUB, el cuello de botella son las
    conversiones con ebook-convert y no el numero de nucleos.
    """
    import statistics
    by_fmt = defaultdict(list)
    fresh = [r for r in fps.values() if not r.get('cached')]
    for r in fresh:
        by_fmt[r.get('format') or '?'].append(r.get('elapsed') or 0.0)
    if not fresh:
        return
    print('\nCoste del escaneo por formato (solo libros leidos ahora):')
    print('  {:<8} {:>7} {:>10} {:>10} {:>10} {:>12}'.format(
        'formato', 'libros', 'mediana', 'media', 'maximo', 'total'))
    for fmt in sorted(by_fmt, key=lambda f: -sum(by_fmt[f])):
        ts = by_fmt[fmt]
        print('  {:<8} {:>7} {:>9.2f}s {:>9.2f}s {:>9.2f}s {:>11.0f}s'.format(
            fmt, len(ts), statistics.median(ts), sum(ts) / len(ts),
            max(ts), sum(ts)))
    slowest = sorted(fresh, key=lambda r: -(r.get('elapsed') or 0))[:5]
    if slowest and (slowest[0].get('elapsed') or 0) > 1.0:
        print('  Libros mas lentos:')
        for r in slowest:
            print('    {:.2f}s  {}  uid={}'.format(
                r['elapsed'], r.get('format') or '?', r['uid']))


# ---------------------------------------------------------------------------
# Agrupacion por huella (dentro de una biblioteca y ENTRE bibliotecas)
# ---------------------------------------------------------------------------

def group_duplicates(books, fps, min_chapters=1):
    """
    Agrupa por huella de contenido sobre el TOTAL de libros, de todas las
    bibliotecas a la vez, de modo que un grupo puede abarcar varias.

    Se descartan los libros sin huella o sin capitulos utiles: si no hay texto
    extraible todos compartirian la "misma" huella vacia y se declararian
    duplicados entre si, que es justo el falso positivo a evitar.
    """
    by_uid = {b['uid']: b for b in books}
    buckets = defaultdict(list)
    skipped = []
    for uid, r in fps.items():
        b = dict(by_uid[uid])
        b['sha1'] = r['sha1']
        b['n_chapters'] = r['n_chapters']
        b['n_ignored'] = r['n_ignored']
        b['origin'] = r.get('origin') or 'desconocido'
        b['origin_reasons'] = r.get('origin_reasons') or []
        b['issues'] = r.get('issues') or []
        if r['error']:
            b['skip_reason'] = 'error de extraccion: {}'.format(r['error'])
            skipped.append(b)
            continue
        if not r['fingerprint'] or r['n_chapters'] < min_chapters:
            b['skip_reason'] = 'sin contenido comparable ({} capitulos)'.format(r['n_chapters'])
            skipped.append(b)
            continue
        buckets[r['fingerprint']].append(b)

    groups = []
    for fp, members in buckets.items():
        if len(members) < 2:
            continue
        members.sort(key=lambda b: (b['lib_index'], b['id']))
        sha1s = {m['sha1'] for m in members}
        libs = {m['library'] for m in members}
        groups.append({
            'fingerprint': fp,
            'books': members,
            # Estricto: TODOS deben tener sha1 y ser el mismo.  Con un None por
            # medio el conjunto podia quedarse en un solo elemento y marcar como
            # "identicos byte a byte" un grupo que no lo era.
            'binary': None not in sha1s and len(sha1s) == 1,
            'cross': len(libs) > 1,
            'libraries': sorted(libs),
        })
    # Primero los cruzados (mas informativos), luego por tamano de grupo.
    groups.sort(key=lambda g: (not g['cross'], -len(g['books']),
                               -sum(b['size'] for b in g['books'])))
    return groups, skipped


def books_with_issues(books, fps):
    """
    Libros con problemas de formato, esten duplicados o no.

    Se recorren TODOS los libros analizados, no solo los de algun grupo: un
    libro unico y mal formado tambien conviene reconvertirlo.
    """
    by_uid = {b['uid']: b for b in books}
    out = []
    for uid, r in fps.items():
        issues = r.get('issues') or []
        if not issues:
            continue
        b = dict(by_uid[uid])
        b['issues'] = issues
        out.append(b)
    out.sort(key=lambda b: (b['lib_index'], b['id']))
    return out


def _origin_rank(origin):
    """Rango de procedencia (menor gana), delegando en extractor.py."""
    try:
        import extractor
        return extractor.origin_rank(origin)
    except Exception:
        return 1


KEEP_STRATEGIES = ('plugin', 'best', 'largest', 'smallest', 'oldest', 'newest')


def _keep_criteria(strategy, prefer_rank):
    """
    Lista ordenada de criterios: [(etiqueta, valor, formateador), ...].

    La clave de ordenacion Y la explicacion del informe salen de ESTA misma
    lista, a proposito.  Antes la explicacion era un texto fijo que siempre
    decia "el mayor de N" aunque el tamano no hubiera decidido nada, y llegaba a
    afirmar que la copia conservada era la mayor cuando era la menor.  Con una
    unica fuente, la explicacion no puede contradecir a la decision.

    Menor gana en todos los valores.
    """
    def rank(b):
        return prefer_rank.get(os.path.realpath(b['library']), 10 ** 6)

    def libname(b):
        return os.path.basename(b['library'].rstrip('/\\')) or b['library']

    pref   = ('biblioteca preferida', rank, libname)
    fmt    = ('formato', lambda b: 0 if b['format'] == 'EPUB' else 1,
              lambda b: b['format'])
    origin = ('procedencia', lambda b: _origin_rank(b.get('origin')),
              lambda b: b.get('origin') or 'desconocido')
    bigger = ('tamano', lambda b: -(b['size'] or 0),
              lambda b: human_size(b['size']))
    smaller = ('tamano', lambda b: (b['size'] or 0),
               lambda b: human_size(b['size']))
    cover  = ('portada', lambda b: 0 if b.get('has_cover') else 1,
              lambda b: 'con portada' if b.get('has_cover') else 'sin portada')
    liborder = ('orden de las bibliotecas en el comando',
                lambda b: b['lib_index'], libname)
    liborder_rev = ('orden inverso de las bibliotecas',
                    lambda b: -b['lib_index'], libname)
    id_low  = ('id mas bajo', lambda b: b['id'], lambda b: 'id={}'.format(b['id']))
    id_high = ('id mas alto', lambda b: -b['id'], lambda b: 'id={}'.format(b['id']))

    if strategy == 'largest':
        return [pref, bigger, liborder, id_low]
    if strategy == 'smallest':
        return [pref, smaller, liborder, id_low]
    if strategy == 'oldest':
        return [pref, liborder, id_low]
    if strategy == 'newest':
        return [pref, liborder_rev, id_high]
    # 'plugin' / 'best': el mismo orden que aplica el plugin en Calibre.
    return [pref, fmt, origin, bigger, cover, liborder, id_low]


def _keep_sort_key(strategy, prefer_rank):
    """Clave de orden: el PRIMER libro tras ordenar es el que se conserva."""
    criteria = _keep_criteria(strategy, prefer_rank or {})
    return lambda b: tuple(value(b) for _label, value, _fmt in criteria)


def explain_keep(group, strategy, prefer_rank):
    """
    Explica por que se conserva la copia elegida, comparandola con su rival mas
    cercano y diciendo QUE criterio los separo de verdad.

    Devuelve (texto, criterio) o (texto, None) si todos empataban.
    """
    criteria = _keep_criteria(strategy, prefer_rank or {})
    members = sorted(group['books'],
                     key=lambda b: tuple(v(b) for _l, v, _f in criteria))
    keep = members[0]
    if len(members) < 2:
        return 'unica copia', None
    rival = members[1]

    for label, value, fmt in criteria:
        va, vb = value(keep), value(rival)
        if va != vb:
            return ('decide {} -- {} (id={}) frente a {} (id={})'.format(
                label, fmt(keep), keep['id'], fmt(rival), rival['id']), label)
    return ('todas las copias empatan en todos los criterios; se conserva '
            'id={} por orden estable'.format(keep['id']), None)


def decide_group(group, strategy='best', prefer_rank=None):
    """
    Marca en el grupo cual se conserva ('keep') y cuales sobran ('drop').

    Salvaguarda: si un candidato a borrar tiene formatos NO COMPARADOS que la
    copia conservada no tiene (p. ej. tambien un PDF), borrarlo perderia ese
    fichero.  Se marca 'blocked' y no se borra, aunque el EPUB sea identico.
    EPUB y AZW3 no cuentan como formatos a proteger: son los que se comparan y
    el criterio ya decide entre ellos.
    """
    prefer_rank = prefer_rank or {}
    members = sorted(group['books'], key=_keep_sort_key(strategy, prefer_rank))
    keep = members[0]
    keep_fmts = set(keep.get('formats') or ())
    drops, blocked = [], []
    for b in members[1:]:
        # Solo protegen los formatos que NO participan en la comparacion.
        # EPUB y AZW3 se excluyen a proposito: son las dos caras del mismo libro
        # y el criterio ya dice que EPUB gana a AZW3, asi que proteger un AZW3
        # "porque es el unico AZW3" anularia el criterio y no borraria nunca las
        # copias en ese formato.  Un PDF, un MOBI o un DOCX si se protegen: no se
        # han comparado y perderlos seria una perdida real de contenido.
        extra = sorted((set(b.get('formats') or ()) - keep_fmts)
                       - set(SUPPORTED_FORMATS))
        if extra:
            b = dict(b)
            b['extra_formats'] = extra
            blocked.append(b)
        else:
            drops.append(b)
    group['keep'] = keep
    group['drop'] = drops
    group['blocked'] = blocked
    group['reclaimable'] = sum(b['size'] for b in drops)
    group['why'], group['why_criterion'] = explain_keep(group, strategy, prefer_rank)
    return group


def verify_all_formats(groups, cache, cache_path, jobs=None):
    """
    Comprueba que los formatos SECUNDARIOS de cada copia marcada para borrar
    tienen el mismo contenido que el grupo.

    De cada registro de Calibre solo se compara un fichero (EPUB si lo hay, si no
    AZW3).  Si un registro tiene ademas un AZW3 y ese AZW3 fuera OTRO libro -- una
    edicion distinta, o un error de metadatos que junto dos obras bajo el mismo
    id -- borrar el registro por su EPUB destruiria contenido que no esta en
    ninguna otra copia.

    Solo se verifican los candidatos a BORRAR, no toda la biblioteca: es donde
    importa, y asi el coste (convertir AZW3 con ebook-convert) se limita a unos
    pocos ficheros en vez de a todos.

    Los registros que no superan la comprobacion salen de 'drop' y pasan a
    'blocked' con el motivo, de modo que no entran en el plan de borrado.
    """
    tasks, owners = [], {}
    for gi, g in enumerate(groups):
        for b in g['drop']:
            for fmt, path in sorted((b.get('format_paths') or {}).items()):
                if path == b['path']:
                    continue          # el formato principal ya se comparo
                key = '{}|{}'.format(b['uid'], fmt)
                tasks.append({'uid': key, 'path': path, 'format': fmt,
                              'size': _safe_size(path), 'mtime': _safe_mtime(path)})
                owners[key] = (gi, b['uid'], fmt, path)
    if not tasks:
        return 0, 0

    print('\nVerificando {} formatos secundarios de las copias a borrar '
          '(para asegurar que no contienen otro libro)...'.format(len(tasks)))
    hits, misses = split_cached(tasks, cache) if cache else ({}, list(tasks))
    fps = dict(hits)
    if misses:
        compute_fingerprints(misses, jobs=jobs,
                             use_processes=not running_inside_calibre(),
                             results=fps)
    if cache_path:
        save_cache(cache_path, update_cache(cache, tasks, fps))

    by_uid = {}
    for g in groups:
        for b in g['drop']:
            by_uid[b['uid']] = b

    moved = 0
    for key, (gi, uid, fmt, path) in owners.items():
        r = fps.get(key)
        if r is None:
            continue
        g = groups[gi]
        b = by_uid.get(uid)
        if b is None or b not in g['drop']:
            continue                  # ya movido por otro formato
        problem = None
        if r.get('error'):
            problem = 'no se pudo leer su {}: {}'.format(fmt, r['error'])
        elif not r.get('fingerprint'):
            problem = 'su {} no tiene texto comparable'.format(fmt)
        elif r['fingerprint'] != g['fingerprint']:
            problem = 'su {} tiene CONTENIDO DISTINTO al del grupo'.format(fmt)
        if problem:
            g['drop'].remove(b)
            b = dict(b)
            b['mismatch'] = problem
            g['blocked'].append(b)
            moved += 1

    for g in groups:
        g['reclaimable'] = sum(x['size'] for x in g['drop'])
    return len(tasks), moved


def build_prefer_rank(prefer_libraries):
    rank = {}
    for i, p in enumerate(prefer_libraries or ()):
        rank[os.path.realpath(os.path.abspath(os.path.expanduser(p)))] = i
    return rank


# ---------------------------------------------------------------------------
# Plan de borrado: el escaneo lo escribe, --apply lo ejecuta
# ---------------------------------------------------------------------------
# Separar las dos fases es lo que evita repetir la parte lenta.  El escaneo
# (horas en una biblioteca grande) se hace en solo lectura y puede convivir con
# Calibre abierto; el borrado (segundos) se lanza despues con Calibre cerrado.
# Para eso el plan guarda, de cada copia a borrar, lo suficiente para detectar
# que la biblioteca ha cambiado desde el escaneo: id, titulo, ruta, tamano y
# mtime del fichero.

def _plan_entry(b, cross=False):
    return OrderedDict((
        ('library', b['library']),
        ('cross', bool(cross)),
        ('id', b['id']),
        ('title', b['title']),
        ('authors', b['authors']),
        ('format', b['format']),
        ('path', b['path']),
        ('size', b['size']),
        ('mtime', b['mtime']),
        ('origin', b.get('origin') or 'desconocido'),
    ))


def build_plan(groups, libraries, keep_strategy, skip_cross=False):
    plan_groups = []
    for g in groups:
        drops = g['drop']
        if skip_cross and g['cross']:
            continue
        if not drops:
            continue
        plan_groups.append(OrderedDict((
            ('fingerprint', g['fingerprint']),
            ('cross', g['cross']),
            ('binary', g['binary']),
            ('keep', _plan_entry(g['keep'], g['cross'])),
            ('drop', [_plan_entry(b, g['cross']) for b in drops]),
        )))
    return OrderedDict((
        ('plan_version', PLAN_VERSION),
        ('created', time.strftime('%Y-%m-%d %H:%M:%S')),
        ('libraries', list(libraries)),
        ('keep_strategy', keep_strategy),
        ('n_drop', sum(len(g['drop']) for g in plan_groups)),
        ('groups', plan_groups),
    ))


def write_plan(path, plan):
    with codecs.open(path, 'w', 'utf-8') as fh:
        json.dump(plan, fh, indent=1, ensure_ascii=False)
    return path


def read_plan(path):
    with codecs.open(path, 'r', 'utf-8') as fh:
        plan = json.load(fh)
    if plan.get('plan_version') != PLAN_VERSION:
        raise SystemExit('El plan {!r} es de otra version del script '
                         '(plan_version={}). Vuelve a escanear.'
                         .format(path, plan.get('plan_version')))
    return plan


def _library_snapshot(library_path):
    """{id: (path, size, mtime, title)} de los libros con EPUB/AZW3, en ro."""
    snap = {}
    for b in load_books_sqlite(library_path):
        snap[b['id']] = (b['path'], b['size'], b['mtime'], b['title'])
    return snap


def validate_plan(plan, tolerate_mtime=False):
    """
    Comprueba que el plan sigue siendo aplicable.

    Rechaza (no borra) cualquier entrada cuyo libro haya desaparecido, cambiado
    de titulo, de ruta o de contenido desde el escaneo.  Sin esto, aplicar un
    plan viejo podria borrar un libro distinto del que se analizo, porque
    Calibre reutiliza los ids liberados.

    Devuelve (ok_por_biblioteca, rechazos).
    """
    by_lib = defaultdict(list)
    for g in plan.get('groups', ()):
        for entry in g.get('drop', ()):
            by_lib[entry['library']].append((g, entry))

    ok = defaultdict(list)
    rejected = []
    for lib, items in by_lib.items():
        if not is_calibre_library(lib):
            for _g, e in items:
                rejected.append((e, 'la biblioteca ya no existe: {}'.format(lib)))
            continue
        snap = _library_snapshot(lib)
        for _g, e in items:
            cur = snap.get(e['id'])
            if cur is None:
                rejected.append((e, 'el libro id={} ya no esta en la biblioteca'.format(e['id'])))
                continue
            cur_path, cur_size, cur_mtime, cur_title = cur
            if os.path.realpath(cur_path) != os.path.realpath(e['path']):
                rejected.append((e, 'el fichero del id={} ha cambiado de ruta'.format(e['id'])))
                continue
            if (cur_title or '').strip() != (e['title'] or '').strip():
                rejected.append((e, 'el id={} tiene ahora otro titulo ({!r})'.format(
                    e['id'], cur_title)))
                continue
            if cur_size != e['size']:
                rejected.append((e, 'el fichero del id={} ha cambiado de tamano'.format(e['id'])))
                continue
            if cur_mtime != e['mtime'] and not tolerate_mtime:
                rejected.append((e, 'el fichero del id={} se ha modificado desde el escaneo'
                                    ' (usa --tolerate-mtime si es esperado)'.format(e['id'])))
                continue
            ok[lib].append(e)
    return ok, rejected


# ---------------------------------------------------------------------------
# Borrado (siempre a traves de las herramientas de Calibre)
# ---------------------------------------------------------------------------

def calibre_maybe_running():
    """Mejor esfuerzo: True si parece haber un Calibre abierto."""
    try:
        if sys.platform == 'win32':
            proc = subprocess.run(['tasklist', '/FO', 'CSV', '/NH'],
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            out = (proc.stdout or b'').decode('utf-8', 'replace').lower()
            return ('"calibre.exe"' in out) or ('"calibre-parallel.exe"' in out)
        proc = subprocess.run(['ps', '-eo', 'comm='], stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL)
        out = (proc.stdout or b'').decode('utf-8', 'replace')
        names = {l.strip().rsplit('/', 1)[-1] for l in out.splitlines()}
        return bool(names & {'calibre', 'calibre-parallel'})
    except Exception:
        return False


def backup_metadata_db(library_path):
    """Copia metadata.db (y WAL/SHM) antes de borrar.  Devuelve la ruta o None."""
    src = os.path.join(library_path, 'metadata.db')
    if not os.path.exists(src):
        return None
    dst = os.path.join(library_path,
                       'metadata.db.bak-{}'.format(time.strftime('%Y%m%d_%H%M%S')))
    try:
        shutil.copy2(src, dst)
    except Exception as exc:
        logger.warning('No se pudo respaldar %s: %s', src, exc)
        return None
    for suffix in ('-wal', '-shm'):
        if os.path.exists(src + suffix):
            try:
                shutil.copy2(src + suffix, dst + suffix)
            except Exception:
                pass
    return dst


def find_calibredb():
    cand = [shutil.which('calibredb')]
    exe = 'calibredb.exe' if sys.platform == 'win32' else 'calibredb'
    cand.append(os.path.join(os.path.dirname(sys.executable), exe))
    if sys.platform == 'win32':
        for pf in (os.environ.get('PROGRAMFILES'), os.environ.get('PROGRAMFILES(X86)')):
            if pf:
                cand.append(os.path.join(pf, 'Calibre2', exe))
                cand.append(os.path.join(pf, 'Calibre', exe))
    elif sys.platform == 'darwin':
        cand.append('/Applications/calibre.app/Contents/MacOS/calibredb')
    for c in cand:
        if c and os.path.exists(c):
            return c
    return None


def export_before_delete(library_path, ids, dest, batch=100):
    """
    Exporta con 'calibredb export' los libros que se van a borrar, ANTES de
    borrarlos.  Guarda los ficheros, la portada y los metadatos en un OPF.

    Es la red de seguridad que NO depende de ninguna papelera:

      - La papelera de Calibre y la de Windows se purgan (la de la biblioteca,
        a los pocos dias), asi que "es reversible" tiene fecha de caducidad.
      - Una biblioteca en un disco de red o externo puede no tener papelera del
        sistema, y entonces el borrado del fichero es definitivo.
      - Una carpeta exportada se puede volver a anadir a Calibre con
        'calibredb add' o arrastrandola, y el OPF recupera los metadatos.

    Devuelve (n_ficheros_exportados, errores).  Si falla, el llamante NO debe
    borrar: mejor no borrar nada que borrar sin copia.
    """
    exe = find_calibredb()
    if not exe:
        return 0, ['No encuentro calibredb: no puedo exportar antes de borrar.']
    try:
        os.makedirs(dest, exist_ok=True)
    except Exception as exc:
        return 0, ['No puedo crear {}: {}'.format(dest, exc)]

    ids = sorted(ids)
    errors = []
    # La plantilla por defecto de calibredb ('{author_sort}/{title}/{title} -
    # {authors}') NO lleva el id, y aqui se exportan justo duplicados: varios
    # libros comparten titulo y autor, calibredb los escribe en la MISMA
    # carpeta y unos OPF pisan a otros (menos metadata.opf que libros, copia
    # incompleta en silencio). El {id} en la plantilla lo evita.
    template = '{author_sort}/{title} ({id})/{title} - {authors} ({id})'
    for i in range(0, len(ids), batch):
        chunk = ids[i:i + batch]
        cmd = [exe, '--with-library', library_path, 'export',
               '--to-dir', dest, '--template', template,
               ','.join(str(x) for x in chunk)]
        kwargs = {}
        if sys.platform == 'win32':
            kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        proc = subprocess.run(cmd, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, **kwargs)
        if proc.returncode != 0:
            msg = (proc.stderr or b'').decode('utf-8', 'replace').strip()
            errors.append('calibredb export fallo en {}: {}'.format(
                library_path, msg or 'codigo {}'.format(proc.returncode)))
            break

    n = 0
    for _root, _dirs, files in os.walk(dest):
        n += len(files)
    if not errors and n == 0:
        errors.append('calibredb export no genero ningun fichero en {}'.format(dest))
    return n, errors


def delete_ids(library_path, ids, batch=200):
    """
    Borra 'ids' de 'library_path' con calibredb, sin --permanent.

    Que no sea --permanent NO implica que se pueda deshacer desde Calibre: se ha
    comprobado que la papelera de la biblioteca puede quedar vacia tras un
    borrado por linea de comandos.  Trata este borrado como definitivo y confia
    en la copia exportada.  Devuelve (n_borrados, errores).
    """
    exe = find_calibredb()
    if not exe:
        return 0, ['No encuentro calibredb. Anade la carpeta de Calibre al PATH, '
                   'o usa la busqueda "id:..." del informe para borrarlos desde Calibre.']
    done, errors = 0, []
    ids = sorted(ids)
    for i in range(0, len(ids), batch):
        chunk = ids[i:i + batch]
        cmd = [exe, '--with-library', library_path, 'remove',
               ','.join(str(x) for x in chunk)]
        kwargs = {}
        if sys.platform == 'win32':
            kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
        if proc.returncode == 0:
            done += len(chunk)
        else:
            msg = (proc.stderr or b'').decode('utf-8', 'replace').strip()
            if 'another calibre' in msg.lower() or 'is running' in msg.lower():
                msg += ('\n    -> Cierra Calibre por completo y repite el --apply. '
                        'Este lote no se ha borrado.')
            errors.append('calibredb fallo en {} (lote {}-{}): {}'.format(
                library_path, i + 1, i + len(chunk),
                msg or 'codigo {}'.format(proc.returncode)))
            break
    return done, errors


def apply_plan(plan, args):
    """Ejecuta un plan de borrado ya validado.  Devuelve un resumen."""
    if calibre_maybe_running() and not args.force_running:
        print('\nParece que Calibre esta ABIERTO. No borro nada.')
        print('Cierra Calibre y repite el --apply (o usa --force-running si estas')
        print('segura de que ninguna instancia usa estas bibliotecas).')
        return {'deleted': 0, 'errors': ['Calibre abierto'], 'rejected': [], 'backups': {}}

    ok_by_lib, rejected = validate_plan(plan, tolerate_mtime=args.tolerate_mtime)
    if args.skip_cross:
        # Cada entrada del plan lleva su propia marca 'cross', asi que filtrar es
        # directo y no depende de recalcular nada.
        for lib in list(ok_by_lib):
            ok_by_lib[lib] = [e for e in ok_by_lib[lib] if not e.get('cross')]

    total = sum(len(v) for v in ok_by_lib.values())
    print('\nA borrar: {} libros en {} biblioteca(s).'.format(total, len(ok_by_lib)))
    if rejected:
        print('Rechazados por haber cambiado desde el escaneo: {}'.format(len(rejected)))
        for e, why in rejected[:10]:
            print('  - id={} {!r}: {}'.format(e['id'], (e['title'] or '')[:50], why))
        if len(rejected) > 10:
            print('  ... y {} mas'.format(len(rejected) - 10))
    if not total:
        return {'deleted': 0, 'errors': [], 'rejected': rejected, 'backups': {}}

    if not args.yes:
        for lib, entries in sorted(ok_by_lib.items()):
            print('  {}: ids {}{}'.format(
                lib, ','.join(str(e['id']) for e in entries[:20]),
                ', ...' if len(entries) > 20 else ''))
        print('NO cuentes con deshacerlo desde Calibre: su papelera puede estar')
        print('vacia (depende de "Permanently delete after", que puede ser "on close")')
        print('y en cualquier caso caduca. Tu copia real es la carpeta exportada')
        print('y el respaldo de metadata.db que se hacen justo antes de borrar.')
        try:
            answer = input('Escribe BORRAR para confirmar: ').strip()
        except EOFError:
            answer = ''
        except KeyboardInterrupt:
            print('\nCancelado: no se ha borrado nada.')
            return {'deleted': 0, 'errors': [], 'rejected': rejected, 'backups': {}}
        if answer != 'BORRAR':
            print('Cancelado: no se ha borrado nada.')
            return {'deleted': 0, 'errors': [], 'rejected': rejected, 'backups': {}}

    deleted, errors, backups = 0, [], {}
    export_root = None
    if not args.no_export:
        export_root = args.export_dir or os.path.join(
            args.out_dir or _DEFAULT_OUT_DIR,
            'exportadas_{}'.format(time.strftime('%Y%m%d_%H%M%S')))

        # Presupuesto de disco ANTES de empezar.  'calibredb export' escribe por
        # cada libro: sus ficheros, la portada y un metadata.opf, asi que salen
        # entre 2 y 3 ficheros por libro y el tamano supera al de los EPUB
        # comparados.  Con 1900 libros eso son varios GB, y conviene saberlo
        # antes, no a mitad.
        approx = sum(e.get('size') or 0
                     for entries in ok_by_lib.values() for e in entries)
        print('\nExportando una copia de cada libro antes de borrarlo:')
        print('  destino: {}'.format(export_root))
        print('  {} libro{}, al menos {} (mas portadas, OPF y otros formatos:'
              ' cuenta con cerca del doble)'.format(
                  total, 's' if total != 1 else '', human_size(approx)))
        try:
            base = export_root
            while base and not os.path.isdir(base):
                parent = os.path.dirname(base)
                if parent == base:
                    break
                base = parent
            free = shutil.disk_usage(base).free
            print('  libre en destino: {}'.format(human_size(free)))
            if free < approx * 2:
                print('  AVISO: puede no caber. Usa --export-dir para mandarlo a')
                print('  otro disco. Con --no-export te quedas solo con el respaldo')
                print('  de metadata.db, que restaura la base de datos pero NO los')
                print('  ficheros borrados.')
                if not args.yes:
                    try:
                        if input('  Escribe SEGUIR para continuar igualmente: ').strip() != 'SEGUIR':
                            print('  Cancelado: no se ha borrado nada.')
                            return {'deleted': 0, 'errors': ['espacio insuficiente'],
                                    'rejected': rejected, 'backups': {}}
                    except EOFError:
                        pass
                    except KeyboardInterrupt:
                        print('\n  Cancelado: no se ha borrado nada.')
                        return {'deleted': 0, 'errors': ['espacio insuficiente'],
                                'rejected': rejected, 'backups': {}}
        except Exception:
            pass

    for lib, entries in sorted(ok_by_lib.items()):
        ids = [e['id'] for e in entries]

        # 1. Copia exportada. Si falla, NO se borra nada de esta biblioteca.
        if export_root:
            sub = os.path.join(export_root, re.sub(r'[^\w.-]+', '_',
                                                  os.path.basename(lib.rstrip('/\\')) or 'lib'))
            n_files, exp_errs = export_before_delete(lib, ids, sub)
            if exp_errs:
                errors.extend(exp_errs)
                print('  {}: NO borro nada, la exportacion fallo.'.format(lib))
                for e in exp_errs:
                    print('    ! {}'.format(e))
                continue
            exported_bytes = 0
            for _r, _d, _f in os.walk(sub):
                for name in _f:
                    try:
                        exported_bytes += os.path.getsize(os.path.join(_r, name))
                    except Exception:
                        pass
            # La copia exportada es la unica red de seguridad real, asi que se
            # comprueba que esta completa ANTES de borrar: calibredb escribe un
            # metadata.opf por libro, de modo que debe haber tantos OPF como
            # libros.  Si faltan, no se borra nada de esta biblioteca.
            n_opf = 0
            for _r, _d, _f in os.walk(sub):
                n_opf += sum(1 for name in _f if name.lower().endswith('.opf'))
            print('  {}: exportados {} ficheros, {} (de {} libro{}: cada uno '
                  'aporta su fichero, su portada y un metadata.opf)'.format(
                      lib, n_files, human_size(exported_bytes), len(ids),
                      's' if len(ids) != 1 else ''))
            if n_opf < len(ids):
                msg = ('la copia exportada esta INCOMPLETA: {} metadata.opf para '
                       '{} libros. NO borro nada de {}.'.format(n_opf, len(ids), lib))
                errors.append(msg)
                print('    ! {}'.format(msg))
                continue
            print('    copia verificada: {} metadata.opf para {} libros'.format(
                n_opf, len(ids)))

        # 2. Copia de metadata.db.
        if not args.no_backup:
            bk = backup_metadata_db(lib)
            backups[lib] = bk
            print('  copia de seguridad: {}'.format(bk or 'FALLIDA'))

        # 3. Borrado.
        n, errs = delete_ids(lib, ids)
        deleted += n
        errors.extend(errs)
        print('  {}: borrados {}/{}'.format(lib, n, len(entries)))
    for e in errors:
        print('  ! {}'.format(e))
    return {'deleted': deleted, 'errors': errors, 'rejected': rejected, 'backups': backups}


# ---------------------------------------------------------------------------
# Informe HTML
# ---------------------------------------------------------------------------

def human_size(n):
    n = float(n or 0)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024 or unit == 'TB':
            return '{:.0f} B'.format(n) if unit == 'B' else '{:.1f} {}'.format(n, unit)
        n /= 1024.0


_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { font: 15px/1.5 -apple-system, "Segoe UI", Roboto, sans-serif;
       margin: 0; padding: 2rem 1.5rem 4rem; background: #f6f7f9; color: #1b1d22; }
@media (prefers-color-scheme: dark) {
  body { background: #14161a; color: #e6e8ec; }
  .card, header.summary { background: #1d2026; border-color: #2c313a; }
  th { background: #24282f; }
  tr.keep { background: #14301f; } tr.blocked { background: #3a2f14; }
  code, .idsearch { background: #24282f; }
}
h1 { font-size: 1.5rem; margin: 0 0 .25rem; }
h2.sec { font-size: 1.15rem; margin: 2rem 0 .75rem; }
.sub { color: #6b7280; margin: 0 0 1.25rem; }
header.summary, .card { background: #fff; border: 1px solid #e3e6ea; border-radius: 10px;
                        padding: 1rem 1.25rem; margin-bottom: 1rem; }
.stats { display: flex; flex-wrap: wrap; gap: 1.5rem; }
.stat b { display: block; font-size: 1.6rem; line-height: 1.2; }
.stat span { color: #6b7280; font-size: .85rem; }
table { width: 100%; border-collapse: collapse; margin-top: .5rem; font-size: .9rem; }
th, td { text-align: left; padding: .45rem .6rem; border-bottom: 1px solid #e3e6ea; }
th { background: #f1f3f6; font-weight: 600; font-size: .78rem; text-transform: uppercase;
     letter-spacing: .03em; color: #6b7280; }
tr.keep { background: #e8f8ee; } tr.blocked { background: #fff5e0; }
td.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.tag { display: inline-block; font-size: .72rem; font-weight: 600; padding: .1rem .45rem;
       border-radius: 999px; border: 1px solid currentColor; white-space: nowrap; }
.tag.keep { color: #167c48; } .tag.drop { color: #a3271e; } .tag.blk { color: #8a5a00; }
.tag.bin { color: #4b5563; } .tag.cross { color: #6d28d9; }
.tag.ed { color: #167c48; } .tag.cal { color: #a3271e; } .tag.unk { color: #6b7280; }
.why { color: #6b7280; font-size: .8rem; }
.card h3 { font-size: 1rem; margin: 0 0 .1rem; }
.card .meta { color: #6b7280; font-size: .85rem; margin: 0 0 .5rem; }
code, .idsearch { background: #f1f3f6; padding: .1rem .35rem; border-radius: 4px;
                  font-family: ui-monospace, Consolas, monospace; font-size: .85em; }
.idsearch { display: block; padding: .5rem .6rem; margin: .35rem 0 .75rem; word-break: break-all; }
.path { color: #6b7280; font-size: .8rem; word-break: break-all; }
.lib { font-size: .8rem; color: #6d28d9; }
details summary { cursor: pointer; font-weight: 600; }
.mode { font-weight: 600; } .mode.dry { color: #8a5a00; } .mode.del { color: #a3271e; }
"""


def _short_lib(path, libraries):
    """Nombre corto y distinguible de la biblioteca (ultimo componente)."""
    base = os.path.basename(path.rstrip('/\\')) or path
    same = [l for l in libraries
            if (os.path.basename(l.rstrip('/\\')) or l) == base]
    if len(same) > 1:
        parent = os.path.basename(os.path.dirname(path.rstrip('/\\')))
        return '{}/{}'.format(parent, base) if parent else path
    return base


def _id_search(ids):
    """Linea pegable en la busqueda de Calibre.

    Calibre no admite 'id:1,2,3' (solo casa el primero); hace falta
    unir con 'or': 'id:1 or id:2 or id:3'.
    """
    return ' or '.join('id:{}'.format(i) for i in ids)

def _row(b, role, libraries, extra_tags=()):
    cls = {'keep': 'keep', 'blocked': 'blocked'}.get(role, '')
    lab = {'keep': ('keep', 'CONSERVAR'), 'drop': ('drop', 'borrar'),
           'blocked': ('blk', 'no se borra')}[role]
    extra = ''
    if b.get('extra_formats'):
        extra = ' <span class="tag blk">solo aqui: {}</span>'.format(
            html.escape(', '.join(b['extra_formats'])))
    if b.get('mismatch'):
        extra += ' <span class="tag blk">{}</span>'.format(html.escape(b['mismatch']))
    tags = ''.join(' <span class="tag bin">{}</span>'.format(html.escape(t))
                   for t in extra_tags)
    origin = b.get('origin') or 'desconocido'
    ocls = {'editorial': 'ed', 'calibre': 'cal'}.get(origin, 'unk')
    olabel = {'editorial': 'editorial', 'calibre': 'conversion Calibre'}.get(
        origin, 'origen desconocido')
    reasons = b.get('origin_reasons') or []
    tags += ' <span class="tag {}" title="{}">{}</span>'.format(
        ocls, html.escape('; '.join(reasons)), html.escape(olabel))
    return ('<tr class="{cls}"><td><span class="tag {lc}">{ln}</span></td>'
            '<td class="num">{bid}</td>'
            '<td>{title}<br><span class="lib">{lib}</span>'
            '<br><span class="path">{path}</span></td>'
            '<td>{authors}</td><td>{fmt}{extra}{tags}</td>'
            '<td class="num">{size}</td><td class="num">{chaps}</td></tr>').format(
        cls=cls, lc=lab[0], ln=lab[1], bid=b['id'],
        title=html.escape(b['title'] or '(sin titulo)'),
        lib=html.escape(_short_lib(b['library'], libraries)),
        path=html.escape(b['path']), authors=html.escape(b['authors'] or ''),
        fmt=html.escape('/'.join(b.get('formats') or [b['format']])),
        extra=extra, tags=tags, size=human_size(b['size']),
        chaps=b.get('n_chapters', 0))


def _group_card(g, i, libraries):
    parts = ['<div class="card">']
    badge = (' <span class="tag cross">entre bibliotecas</span>' if g['cross'] else '')
    parts.append('<h3>Grupo {} &middot; {} copias del mismo libro{}</h3>'.format(
        i, len(g['books']), badge))
    method = ('ficheros identicos byte a byte' if g['binary']
              else 'contenido identico (ignorando jackets)')
    parts.append('<p class="meta">{} &middot; recuperable {} &middot; huella <code>{}</code>'
                 '{}</p>'.format(html.escape(method), human_size(g['reclaimable']),
                                 g['fingerprint'][:16],
                                 ' &middot; ' + html.escape(', '.join(
                                     _short_lib(l, libraries) for l in g['libraries']))
                                 if g['cross'] else ''))
    parts.append('<table><thead><tr><th></th><th>id</th>'
                 '<th>Titulo / biblioteca / fichero</th><th>Autor</th>'
                 '<th>Formatos</th><th>Tamano</th><th>Caps.</th>'
                 '</tr></thead><tbody>')
    parts.append(_row(g['keep'], 'keep', libraries,
                      ('byte a byte',) if g['binary'] else ()))
    for b in g['drop']:
        parts.append(_row(b, 'drop', libraries))
    for b in g['blocked']:
        parts.append(_row(b, 'blocked', libraries))
    parts.append('</tbody></table>')
    keep = g['keep']
    parts.append('<p class="why">Se conserva id={}: {}.{}</p>'.format(
        keep['id'], html.escape(g.get('why') or ''),
        ' Procedencia: ' + html.escape('; '.join(keep.get('origin_reasons') or []))
        if keep.get('origin_reasons') else ''))
    if g['blocked']:
        parts.append('<p class="meta">Las filas en naranja NO se borran: o tienen '
                     'formatos no comparados que la copia conservada no tiene, o '
                     'alguno de sus ficheros no coincide con el contenido del '
                     'grupo.</p>')
    parts.append('</div>')
    return parts


def write_html_report(out_path, groups, skipped, stats):
    libraries = stats['libraries']
    p = ['<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width, initial-scale=1">',
         '<title>Duplicados exactos</title>',
         '<style>{}</style></head><body>'.format(_CSS)]

    mc, mt = (('del', 'BORRADO APLICADO') if stats['deleted']
              else ('dry', 'Escaneo: no se ha borrado nada'))
    p.append('<h1>Duplicados exactos (100 %)</h1>')
    p.append('<p class="sub">{n} biblioteca(s) &middot; {when} &middot; backend '
             '<code>{backend}</code> &middot; <span class="mode {mc}">{mt}</span></p>'
             .format(n=len(libraries), when=html.escape(stats['when']),
                     backend=html.escape(stats['backend']), mc=mc, mt=html.escape(mt)))

    p.append('<p class="sub">Criterio aplicado: <code>--keep {}</code>{}</p>'.format(
        html.escape(stats.get('keep_strategy') or 'plugin'),
        (' &middot; bibliotecas preferidas: <code>' +
         html.escape(', '.join(stats.get('prefer_libraries') or ())) + '</code>')
        if stats.get('prefer_libraries') else ''))
    p.append('<header class="summary"><div class="stats">')
    for v, l in ((stats['n_books'], 'libros analizados'),
                 (len(stats.get('problem_books') or ()), 'a reconvertir'),
                 (len(groups), 'grupos duplicados'),
                 (stats['n_cross'], 'grupos entre bibliotecas'),
                 (stats['n_drop'], 'copias sobrantes'),
                 (human_size(stats['reclaimable']), 'espacio recuperable'),
                 ('{:.0f} s'.format(stats['elapsed']), 'tiempo de escaneo')):
        p.append('<div class="stat"><b>{}</b><span>{}</span></div>'.format(
            html.escape(str(v)), html.escape(l)))
    p.append('</div>')
    p.append('<details><summary>Bibliotecas analizadas</summary><table><tbody>')
    for lib in libraries:
        p.append('<tr><td>{}</td><td class="path">{}</td></tr>'.format(
            html.escape(_short_lib(lib, libraries)), html.escape(lib)))
    p.append('</tbody></table></details>')
    if stats.get('plan'):
        p.append('<p class="meta">Plan de borrado: <code>{}</code><br>'
                 'Para aplicarlo, cierra Calibre y ejecuta: '
                 '<code>dedupe.cmd --apply "{}"</code></p>'.format(
                     html.escape(stats['plan']), html.escape(stats['plan'])))
    p.append('</header>')

    cross = [g for g in groups if g['cross']]
    inner = [g for g in groups if not g['cross']]

    if not groups:
        p.append('<div class="card"><h3>Sin duplicados exactos</h3><p class="meta">'
                 'Ningun libro tiene contenido identico a otro.</p></div>')

    if cross:
        p.append('<h2 class="sec">Duplicados ENTRE bibliotecas ({})</h2>'.format(len(cross)))
        for i, g in enumerate(cross, 1):
            p.extend(_group_card(g, i, libraries))
    if inner:
        p.append('<h2 class="sec">Duplicados dentro de una misma biblioteca ({})</h2>'
                 .format(len(inner)))
        for i, g in enumerate(inner, 1):
            p.extend(_group_card(g, i, libraries))

    # Busquedas pegables, una por biblioteca (los ids solo valen en la suya)
    by_lib = defaultdict(list)
    for g in groups:
        for b in g['drop']:
            by_lib[b['library']].append(b['id'])
    if by_lib:
        p.append('<div class="card"><h3>Busquedas para Calibre</h3>'
                 '<p class="meta">Un id solo es valido en su propia biblioteca. '
                 'Abre cada biblioteca en Calibre y pega su linea para seleccionar '
                 'las copias sobrantes.</p>')
        for lib in libraries:
            ids = by_lib.get(lib)
            if not ids:
                continue
            p.append('<p class="meta" style="margin:0">{}</p>'.format(
                html.escape(_short_lib(lib, libraries))))
            p.append('<span class="idsearch">{}</span>'.format(
                _id_search(sorted(ids))))
        p.append('</div>')

    problem_books = stats.get('problem_books') or ()
    if problem_books:
        try:
            import extractor
            labels = extractor.ISSUE_LABELS
        except Exception:
            labels = {}
        p.append('<h2 class="sec">Libros que conviene reconvertir ({})</h2>'
                 .format(len(problem_books)))
        p.append('<div class="card"><p class="meta">EPUB mal formados: se han '
                 'podido leer (o no), pero su estructura interna tiene defectos. '
                 'Reconvertirlos con Calibre (Convertir libros &rarr; EPUB) suele '
                 'dejarlos limpios y mejora la deteccion de duplicados.</p>')

        # Lineas pegables, por biblioteca y por tipo de problema.
        by_lib = defaultdict(lambda: defaultdict(list))
        for b in problem_books:
            for key in b['issues']:
                by_lib[b['library']][key].append(b['id'])
        for lib in libraries:
            per_issue = by_lib.get(lib)
            if not per_issue:
                continue
            all_ids = sorted({i for ids in per_issue.values() for i in ids})
            p.append('<p class="meta" style="margin:.6rem 0 0"><b>{}</b> '
                     '&mdash; {} libros</p>'.format(
                         html.escape(_short_lib(lib, libraries)), len(all_ids)))
            p.append('<span class="idsearch">{}</span>'.format(
                _id_search(all_ids)))
            for key, ids in sorted(per_issue.items()):
                p.append('<p class="meta" style="margin:0">{} ({})</p>'.format(
                    html.escape(labels.get(key, key)), len(set(ids))))
                p.append('<span class="idsearch">{}</span>'.format(
                    _id_search(sorted(set(ids)))))

        p.append('<table><thead><tr><th>id</th><th>Biblioteca</th><th>Titulo</th>'
                 '<th>Problemas</th></tr></thead><tbody>')
        for b in problem_books:
            p.append('<tr><td class="num">{}</td><td class="lib">{}</td>'
                     '<td>{}<br><span class="path">{}</span></td><td>{}</td></tr>'
                     .format(b['id'], html.escape(_short_lib(b['library'], libraries)),
                             html.escape(b['title'] or '(sin titulo)'),
                             html.escape(b['path']),
                             '<br>'.join(html.escape(labels.get(k, k))
                                         for k in b['issues'])))
        p.append('</tbody></table></div>')

    if skipped:
        p.append('<div class="card"><details><summary>{} libros no analizables'
                 '</summary>'.format(len(skipped)))

        # Busquedas pegables tambien para los NO analizables: son los que hay que
        # revisar a mano (ficheros danados, sin texto extraible...), asi que
        # conviene poder seleccionarlos en Calibre igual que las copias sobrantes.
        # Un id solo vale dentro de su biblioteca, de ahi una linea por cada una.
        # Y dentro de cada biblioteca se separa por MOTIVO, porque un fichero
        # corrupto y uno sin texto no se arreglan igual.
        skipped_by_lib = defaultdict(lambda: defaultdict(list))
        for b in skipped:
            motivo = (b.get('skip_reason') or '').split(':')[0].strip() or 'sin motivo'
            skipped_by_lib[b['library']][motivo].append(b['id'])

        p.append('<p class="meta">Pega estas lineas en la busqueda de Calibre '
                 '(cada biblioteca por separado) para revisarlos.</p>')
        for lib in libraries:
            per_reason = skipped_by_lib.get(lib)
            if not per_reason:
                continue
            all_ids = sorted(i for ids in per_reason.values() for i in ids)
            p.append('<p class="meta" style="margin:.6rem 0 0"><b>{}</b> '
                     '&mdash; {} libros</p>'.format(
                         html.escape(_short_lib(lib, libraries)), len(all_ids)))
            p.append('<span class="idsearch">{}</span>'.format(
                _id_search(all_ids)))
            if len(per_reason) > 1:
                for motivo, ids in sorted(per_reason.items()):
                    p.append('<p class="meta" style="margin:0">{} ({})</p>'.format(
                        html.escape(motivo), len(ids)))
                    p.append('<span class="idsearch">{}</span>'.format(
                        _id_search(sorted(ids))))

        p.append('<table><thead><tr><th>id</th><th>Biblioteca</th>'
                 '<th>Titulo</th><th>Motivo</th></tr></thead><tbody>')
        for b in sorted(skipped, key=lambda x: (x['lib_index'], x['id'])):
            p.append('<tr><td class="num">{}</td><td class="lib">{}</td>'
                     '<td>{}<br><span class="path">{}</span></td><td>{}</td></tr>'.format(
                         b['id'], html.escape(_short_lib(b['library'], libraries)),
                         html.escape(b['title'] or '(sin titulo)'),
                         html.escape(b['path']), html.escape(b['skip_reason'])))
        p.append('</tbody></table></details></div>')

    p.append('</body></html>')
    with codecs.open(out_path, 'w', 'utf-8') as fh:
        fh.write('\n'.join(p))
    return out_path


# ---------------------------------------------------------------------------
# Conversion de los registros que solo tienen AZW3
# ---------------------------------------------------------------------------
# Un registro con AZW3 y sin EPUB obliga a convertirlo con ebook-convert en CADA
# escaneo, y eso domina el tiempo: un EPUB se lee en milesimas, un AZW3 cuesta
# segundos.  Ademas la huella sale del EPUB que Calibre genera al vuelo, cuyo
# troceado puede no coincidir con el de una copia EPUB sana del mismo libro, asi
# que se pierden duplicados.
#
# Convertir una vez y anadir el EPUB al MISMO registro arregla las dos cosas.
# El AZW3 original se CONSERVA: el registro queda con AZW3+EPUB, de modo que la
# operacion es reversible borrando el formato EPUB si algo sale mal.
#
# Es un modo aparte, no parte del escaneo: escribe en la biblioteca (y por tanto
# exige Calibre cerrado), mientras el escaneo es de solo lectura.

CONVERT_FLAGS = ['--flow-size', '0', '--dont-split-on-page-breaks']


def _fmt_ratio(ratio):
    """Segundos por MB, con decimales solo cuando hacen falta."""
    if not ratio:
        return '?'
    return '{:.1f}'.format(ratio) if ratio < 10 else '{:.0f}'.format(ratio)


def azw3_only_books(books, only_ids=None):
    """
    Registros con AZW3 y SIN EPUB.

    Los que ya tienen ambos no se tocan: su EPUB es lo que se compara, asi que
    convertir de nuevo no aportaria nada.  Otros formatos (PDF, MOBI) no
    influyen: lo que importa es que no haya EPUB.
    """
    out = []
    for b in books:
        fmts = {f.upper() for f in (b.get('formats') or ())}
        if 'AZW3' not in fmts or 'EPUB' in fmts:
            continue
        if only_ids and b['id'] not in only_ids:
            continue
        if 'AZW3' not in (b.get('format_paths') or {}):
            continue
        out.append(b)
    out.sort(key=lambda b: (b['lib_index'], b['id']))
    return out


# Procesos de ebook-convert en marcha, para poder cortarlos con Ctrl-C.  Sin
# esto, al interrumpir quedaban hasta --jobs conversiones corriendo de fondo,
# consumiendo CPU y escribiendo en el directorio temporal que se intentaba
# borrar (en Windows no se puede eliminar un fichero en uso).
_RUNNING_PROCS = set()
_RUNNING_LOCK = threading.Lock()
# Bandera de aborto: cierra la carrera entre el barrido de procesos y un hilo que
# estaba a punto de lanzar el suyo.  Sin ella quedaban conversiones sueltas
# arrancadas justo despues del Ctrl-C.
_ABORTING = threading.Event()


def _terminate_running_converts():
    """
    Corta todas las conversiones en marcha.  Se llama al interrumpir.

    En Windows se usa 'taskkill /T' para llevarse tambien los procesos hijos:
    matar solo al padre dejaba conversiones vivas consumiendo CPU despues del
    Ctrl-C, que es justo lo que se quiere evitar.
    """
    _ABORTING.set()
    with _RUNNING_LOCK:
        procs = list(_RUNNING_PROCS)
    for proc in procs:
        try:
            if sys.platform == 'win32':
                subprocess.run(['taskkill', '/F', '/T', '/PID', str(proc.pid)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            else:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    proc.kill()
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    # Barridos sucesivos: entre que se mata un proceso y que otro hilo registra
    # el suyo hay una ventana (Popen ya ha devuelto, pero aun no se ha anotado en
    # el conjunto).  Se repasa hasta que no quede ninguno, con un tope de tiempo
    # para no quedarse aqui si algo se resiste.
    deadline = time.time() + 3.0
    matados = set(procs)
    while time.time() < deadline:
        time.sleep(0.2)
        with _RUNNING_LOCK:
            rest = [pr for pr in _RUNNING_PROCS if pr not in matados]
        if not rest:
            with _RUNNING_LOCK:
                if not _RUNNING_PROCS:
                    break
            continue
        for proc in rest:
            matados.add(proc)
            try:
                if sys.platform == 'win32':
                    subprocess.run(['taskkill', '/F', '/T', '/PID', str(proc.pid)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                else:
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except Exception:
                        proc.kill()
            except Exception:
                pass


def _convert_one(task):
    """
    Worker: convierte UN azw3 a epub.
    Devuelve (uid, epub_path, error, segundos, tamano_origen).

    Solo convierte; no toca la biblioteca.  Anadir el formato se hace en el hilo
    principal, en serie, porque calibredb escribe en metadata.db.
    """
    uid, azw3_path, out_path, timeout = task
    t0 = time.time()
    src_size = 0
    try:
        src_size = os.path.getsize(azw3_path)
    except Exception:
        pass
    try:
        from extractor import _find_ebook_convert
        converter = _find_ebook_convert()
    except Exception as exc:
        return (uid, None, 'no encuentro ebook-convert: {}'.format(exc),
                0.0, src_size)

    if _ABORTING.is_set():
        return uid, None, 'cancelado', 0.0, src_size

    cmd = [converter, azw3_path, out_path] + CONVERT_FLAGS
    kwargs = {}
    if sys.platform == 'win32':
        kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

    proc = None
    try:
        # Popen en lugar de subprocess.run: hace falta la referencia al proceso
        # para poder matarlo desde fuera al interrumpir.
        if sys.platform != 'win32':
            # Grupo propio, para poder matar el proceso y sus hijos de una vez.
            kwargs['start_new_session'] = True
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, **kwargs)
        with _RUNNING_LOCK:
            _RUNNING_PROCS.add(proc)
        try:
            _out, err_bytes = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            return (uid, None,
                    'CORTADO: paso de {} s (usa --convert-timeout para darle mas '
                    'margen)'.format(timeout),
                    time.time() - t0, src_size)
        rc = proc.returncode
    except Exception as exc:
        return (uid, None, '{}: {}'.format(type(exc).__name__, exc),
                time.time() - t0, src_size)
    finally:
        if proc is not None:
            with _RUNNING_LOCK:
                _RUNNING_PROCS.discard(proc)

    if rc != 0 or not os.path.exists(out_path):
        # La salida se captura en BYTES: ebook-convert imprime el titulo del
        # libro y con text=True saltaria UnicodeDecodeError en cp1252.
        err = (err_bytes or b'').decode('utf-8', 'replace').strip()
        low = err.lower()
        if 'drm' in low:
            err = 'protegido con DRM ({})'.format(err[-120:])
        return (uid, None, err[-300:] or 'ebook-convert devolvio {}'.format(rc),
                time.time() - t0, src_size)
    if os.path.getsize(out_path) == 0:
        return (uid, None, 'ebook-convert genero un EPUB vacio',
                time.time() - t0, src_size)
    return uid, out_path, None, time.time() - t0, src_size


def find_calibre_debug():
    """Localiza calibre-debug, que permite ejecutar codigo con la API de Calibre."""
    cand = [shutil.which('calibre-debug')]
    exe = 'calibre-debug.exe' if sys.platform == 'win32' else 'calibre-debug'
    cand.append(os.path.join(os.path.dirname(sys.executable), exe))
    if sys.platform == 'win32':
        for var in ('PROGRAMFILES', 'PROGRAMFILES(X86)'):
            base = os.environ.get(var)
            if base:
                cand.append(os.path.join(base, 'Calibre2', exe))
                cand.append(os.path.join(base, 'Calibre', exe))
    elif sys.platform == 'darwin':
        cand.append('/Applications/calibre.app/Contents/MacOS/calibre-debug')
    for c in cand:
        if c and os.path.exists(c):
            return c
    return None


# Script que se ejecuta DENTRO del interprete de Calibre para anadir muchos
# formatos de una sola vez.
#
# Motivo: 'calibredb add_format' arranca Calibre completo en cada llamada, unos
# 2 s por libro.  Con 1600 libros eso es mas de una hora dedicada solo a
# arrancar procesos, y era el verdadero cuello de botella: da igual convertir
# con 6 o con 20 trabajadores si despues cada anadido cuesta 2 s en serie.
# Aqui se paga UN arranque para todo el lote.
_ADDER_SCRIPT = r"""
import json, sys
payload = json.load(open(sys.argv[-1], 'rb'))
from calibre.library import db as _db
lib = _db(payload['library'])
api = getattr(lib, 'new_api', lib)
out = []
for book_id, path in payload['items']:
    try:
        with open(path, 'rb') as fh:
            api.add_format(int(book_id), 'EPUB', fh, replace=False)
        out.append([book_id, None])
    except Exception as exc:
        out.append([book_id, '{}: {}'.format(type(exc).__name__, exc)])
try:
    lib.close()
except Exception:
    pass
sys.stdout.write('DEDUPE_RESULT ' + json.dumps(out))
"""


def add_epub_formats_bulk(library_path, items, workdir):
    """
    Anade muchos EPUB de golpe usando la API de Calibre bajo calibre-debug.

    'items' es [(book_id, epub_path), ...].  Devuelve (dict id->error_o_None,
    error_global).  Si el error global no es None, el llamante debe recurrir al
    metodo de uno en uno.
    """
    exe = find_calibre_debug()
    if not exe:
        return {}, 'no encuentro calibre-debug'
    script = os.path.join(workdir, '_add_formats.py')
    payload = os.path.join(workdir, '_add_payload.json')
    try:
        with codecs.open(script, 'w', 'utf-8') as fh:
            fh.write(_ADDER_SCRIPT)
        with codecs.open(payload, 'w', 'utf-8') as fh:
            json.dump({'library': library_path,
                       'items': [[int(i), pth] for i, pth in items]}, fh)
    except Exception as exc:
        return {}, 'no pude preparar el script: {}'.format(exc)

    cmd = [exe, '-e', script, '--', payload]
    kwargs = {}
    if sys.platform == 'win32':
        kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=max(300, 10 * len(items)), **kwargs)
    except Exception as exc:
        return {}, '{}: {}'.format(type(exc).__name__, exc)

    out = (proc.stdout or b'').decode('utf-8', 'replace')
    marker = 'DEDUPE_RESULT '
    if marker not in out:
        err = (proc.stderr or b'').decode('utf-8', 'replace').strip()
        return {}, (err[-300:] or 'calibre-debug no devolvio resultados '
                                  '(codigo {})'.format(proc.returncode))
    try:
        pairs = json.loads(out.split(marker, 1)[1].strip())
    except Exception as exc:
        return {}, 'respuesta ilegible: {}'.format(exc)
    return {int(bid): err for bid, err in pairs}, None


def add_epub_format(library_path, book_id, epub_path):
    """Anade el EPUB al registro con calibredb add_format.  Es ADITIVO."""
    exe = find_calibredb()
    if not exe:
        return 'no encuentro calibredb'
    cmd = [exe, '--with-library', library_path, 'add_format',
           str(book_id), epub_path]
    kwargs = {}
    if sys.platform == 'win32':
        kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    if proc.returncode != 0:
        msg = (proc.stderr or b'').decode('utf-8', 'replace').strip()
        if 'another calibre' in msg.lower() or 'is running' in msg.lower():
            msg += ' -> cierra Calibre por completo y repite el comando.'
        return msg or 'calibredb add_format devolvio {}'.format(proc.returncode)
    return None


def run_convert_azw3(libraries, args):
    """
    Convierte a EPUB los registros que solo tienen AZW3 y anade el resultado al
    mismo registro, conservando el AZW3.

    Trabaja por LOTES: convierte varios en paralelo (ebook-convert son procesos
    externos, escalan con los nucleos) y luego anade los formatos en serie.  Por
    lotes y no todo de golpe para no acumular cientos de EPUB temporales en
    disco, y para que una interrupcion conserve lo ya hecho.
    """
    from concurrent.futures import ThreadPoolExecutor

    if calibre_maybe_running() and not args.force_running:
        print('\nParece que Calibre esta ABIERTO. No toco nada.')
        print('calibredb necesita escribir en la biblioteca: cierra Calibre y')
        print('repite el comando (o usa --force-running si estas segura).')
        return 1

    only_ids = None
    if args.ids:
        try:
            only_ids = {int(x) for x in re.split(r'[,\s]+', args.ids) if x.strip()}
        except ValueError:
            raise SystemExit('--ids espera numeros separados por comas: --ids 1,2,3')

    books, backend = load_all_books(libraries, None if args.backend == 'auto'
                                    else args.backend)
    targets = azw3_only_books(books, only_ids)

    fmt_counts = defaultdict(int)
    for b in books:
        fmts = {f.upper() for f in (b.get('formats') or ())}
        if 'AZW3' in fmts:
            fmt_counts['con EPUB' if 'EPUB' in fmts else 'solo AZW3'] += 1
    print('\nRegistros con AZW3: {} solo AZW3, {} que ya tienen EPUB '
          '(estos no se tocan).'.format(fmt_counts['solo AZW3'],
                                        fmt_counts['con EPUB']))
    if not targets:
        print('Nada que convertir.')
        return 0

    print('A convertir: {} registros.'.format(len(targets)))
    print('Se anadira un EPUB a cada uno y se CONSERVARA el AZW3.')
    if not args.yes:
        try:
            if input('Escribe CONVERTIR para continuar: ').strip() != 'CONVERTIR':
                print('Cancelado: no se ha tocado nada.')
                return 0
        except EOFError:
            print('Cancelado.')
            return 0
        except KeyboardInterrupt:
            print('\nCancelado: no se ha tocado nada.')
            return 0

    # Respaldo de metadata.db, una vez por biblioteca y antes de escribir.
    backups = {}
    if not args.no_backup:
        for lib in sorted({b['library'] for b in targets}):
            bk = backup_metadata_db(lib)
            backups[lib] = bk
            print('  copia de seguridad: {}'.format(bk or 'FALLIDA'))

    jobs = args.jobs or max(1, (os.cpu_count() or 2))
    batch = max(1, min(args.batch, len(targets)))
    done, failures, timings = [], [], []
    started = time.time()

    # TUBERIA CONTINUA, no por lotes.  Con lotes, mientras se anadian los
    # formatos en serie no se convertia nada: con 20 trabajadores eso deja la CPU
    # parada en cada tanda.  Aqui la reserva se mantiene alimentada y cada EPUB
    # se anade en cuanto esta listo, borrando su temporal al momento (asi el
    # disco no acumula mas de unos pocos ficheros a la vez).
    #
    # El directorio temporal se gestiona a mano y se borra con ignore_errors: al
    # interrumpir puede quedar algun fichero en uso, y en Windows eso hace
    # fallar el borrado.
    from concurrent.futures import FIRST_COMPLETED, wait as futures_wait

    interrupted = False
    tmpdir = tempfile.mkdtemp(prefix='dedupe_conv_')
    ex = ThreadPoolExecutor(max_workers=jobs)
    pending = {}
    remaining = iter(targets)
    processed = 0
    converted = [0]      # conversiones TERMINADAS (aunque aun no anadidas)
    to_add = defaultdict(list)
    add_seconds = [0.0]
    bulk_ok = [True]

    def _flush_adds(lib):
        """
        Anade a la biblioteca los EPUB acumulados.

        Primero intenta la via masiva (una sola invocacion de Calibre para todos)
        y, si no esta disponible o falla, cae al metodo de uno en uno con
        calibredb.  Devuelve cuantos se han procesado.
        """
        items = to_add.pop(lib, [])
        if not items:
            return 0
        t0 = time.time()
        pairs = [(b['id'], path) for b, path in items]
        errors, global_err = ({}, 'desactivado')
        if bulk_ok[0]:
            errors, global_err = add_epub_formats_bulk(lib, pairs, tmpdir)
            if global_err:
                bulk_ok[0] = False
                sys.stderr.write('\n')
                print('  (via rapida no disponible: {}; sigo de uno en uno, '
                      'sera mas lento)'.format(global_err))
        for b, path in items:
            if global_err:
                err = add_epub_format(b['library'], b['id'], path)
            else:
                err = errors.get(b['id'], 'sin respuesta para este id')
            if err:
                failures.append((b, 'convertido pero no anadido: {}'.format(err)))
            else:
                done.append(b)
            try:
                os.remove(path)
            except Exception:
                pass
        add_seconds[0] += time.time() - t0
        return len(items)

    def _submit_next():
        b = next(remaining, None)
        if b is None:
            return False
        out = os.path.join(tmpdir, 'conv_{}_{}.epub'.format(b['lib_index'], b['id']))
        fut = ex.submit(_convert_one,
                        (b['uid'], b['format_paths']['AZW3'], out,
                         args.convert_timeout))
        pending[fut] = b
        return True

    try:
        # Cola con algo de holgura sobre el numero de trabajadores, para que
        # ninguno se quede esperando mientras el hilo principal anade formatos.
        # No hace falta encolar mas: la ventana se realimenta sola.
        for _ in range(jobs + 2):
            if not _submit_next():
                break
        print('  (los EPUB se anaden a la biblioteca en bloques de {}, '
              'para no arrancar Calibre una vez por libro)'.format(batch))

        while pending:
            ready, _ = futures_wait(list(pending), return_when=FIRST_COMPLETED)
            for fut in ready:
                b = pending.pop(fut)
                try:
                    uid, epub, err, elapsed, src_size = fut.result()
                except Exception as exc:
                    failures.append((b, '{}: {}'.format(type(exc).__name__, exc)))
                    processed += 1
                    _submit_next()
                    continue
                timings.append((elapsed, src_size, uid))

                if err == 'cancelado':
                    processed += 1
                elif err:
                    failures.append((b, err))
                    processed += 1
                else:
                    converted[0] += 1
                    # No se anade de uno en uno: se acumula y se anade por
                    # tandas con una sola llamada a Calibre.  Es lo que evita
                    # pagar ~2 s de arranque por libro.
                    to_add[b['library']].append((b, epub))

                _submit_next()

            # Vaciar las tandas que ya han alcanzado el tamano de lote.
            for lib in [l for l, v in to_add.items() if len(v) >= batch]:
                processed += _flush_adds(lib)

            el = time.time() - started
            # El ritmo se mide con las conversiones TERMINADAS, no con las ya
            # anadidas: si no, el contador se queda en 0 hasta el primer bloque
            # de anadido y parece que el programa esta colgado.
            hechas = converted[0] + len(failures)
            rate = hechas / el if el else 0
            sys.stderr.write('\r  convertidos {}/{} (anadidos {})  ({:.2f}/s, '
                             'faltan ~{:.0f} min, fallos {})   '.format(
                                 hechas, len(targets), len(done), rate,
                                 ((len(targets) - hechas) / rate / 60.0) if rate else 0,
                                 len(failures)))
            sys.stderr.flush()

        # Ultima tanda, la que no llego al tamano de lote.
        for lib in list(to_add):
            processed += _flush_adds(lib)
        sys.stderr.write('\n')
    except KeyboardInterrupt:
        interrupted = True
        sys.stderr.write('\n')
        print('Interrumpido: corto las conversiones en marcha y conservo lo anadido.')
        for fut in list(pending):
            fut.cancel()
        _terminate_running_converts()
        ex.shutdown(wait=False)
        # Conservar lo ya convertido pero aun no anadido: son minutos de trabajo
        # que no hay motivo para tirar.  Los ficheros temporales existen todavia,
        # porque el borrado del directorio se hace despues, en el finally.
        pendientes_de_anadir = sum(len(v) for v in to_add.values())
        if pendientes_de_anadir:
            print('  anadiendo {} conversiones ya terminadas antes de salir...'
                  .format(pendientes_de_anadir))
            for lib in list(to_add):
                try:
                    processed += _flush_adds(lib)
                except Exception as exc:
                    print('  no pude anadirlas: {}'.format(exc))
    finally:
        if not interrupted:
            ex.shutdown(wait=True)
        # ignore_errors: en Windows un fichero aun en uso impediria el borrado y
        # reventaria justo al final, despues de una hora de trabajo bueno.
        shutil.rmtree(tmpdir, ignore_errors=True)

    print('\nConvertidos y anadidos: {} | fallos: {}'.format(len(done), len(failures)))

    # Reparto de tiempos. La pregunta util no es "cuanto tarda" sino "cuanto
    # tarda PARA SU TAMANO": un AZW3 de 30 MB con cientos de imagenes tarda
    # minutos y es normal, mientras que uno pequeno que tarda lo mismo es
    # sospechoso.  De ahi la columna s/MB y la marca de los que se salen de
    # escala frente a la mediana.
    if timings:
        import statistics
        ts = [t for t, _s, _u in timings if t > 0]
        if ts:
            print('Tiempo por libro: mediana {:.1f}s, media {:.1f}s, maximo {:.1f}s'
                  .format(statistics.median(ts), sum(ts) / len(ts), max(ts)))
        total_el = time.time() - started
        print('Reparto: {:.0f}s en total, de los cuales {:.0f}s anadiendo a la '
              'biblioteca ({:.0f} %).'.format(
                  total_el, add_seconds[0],
                  100.0 * add_seconds[0] / total_el if total_el else 0))
        ratios = [(t / (size / (1024.0 * 1024.0)), t, size, uid)
                  for t, size, uid in timings
                  if t > 0 and size and size > 64 * 1024]
        med_ratio = statistics.median([r for r, _t, _s, _u in ratios]) if ratios else 0
        uid_to_book = {b['uid']: b for b in targets}
        if len(timings) >= 3:
            print('\nLos mas lentos:')
            print('  {:>8} {:>10} {:>8}  libro'.format('tiempo', 'tamano', 's/MB'))
            for t, size, uid in sorted(timings, reverse=True)[:6]:
                b = uid_to_book.get(uid)
                mb = (size or 0) / (1024.0 * 1024.0)
                ratio = (t / mb) if mb > 0.0625 else None
                marca = ''
                if ratio and med_ratio and ratio > 3 * med_ratio:
                    marca = '  <-- lento para su tamano, revisalo'
                print('  {:7.1f}s {:>10} {:>8}  id={} {!r}{}'.format(
                    t, human_size(size),
                    _fmt_ratio(ratio),
                    b['id'] if b else '?',
                    ((b['title'] if b else '') or '')[:38], marca))
            if med_ratio:
                print('  Mediana: {} s/MB. Los que se acercan a esa cifra solo son '
                      'grandes;'.format(_fmt_ratio(med_ratio)))
                print('  los muy por encima suelen tener el fichero danado.')

    out_dir = args.out_dir or _DEFAULT_OUT_DIR
    try:
        os.makedirs(out_dir, exist_ok=True)
    except Exception:
        out_dir = os.getcwd()
    log = os.path.join(out_dir, 'conversion_azw3_{}.txt'.format(
        time.strftime('%Y%m%d_%H%M%S')))
    try:
        with codecs.open(log, 'w', 'utf-8') as fh:
            fh.write('Conversion AZW3 -> EPUB, {}\n'.format(
                time.strftime('%Y-%m-%d %H:%M:%S')))
            fh.write('Convertidos: {} | fallos: {}\n\n'.format(len(done), len(failures)))
            by_lib = defaultdict(list)
            for b in done:
                by_lib[b['library']].append(b['id'])
            for lib, ids in sorted(by_lib.items()):
                fh.write('{}\n  id:{}\n\n'.format(lib, ','.join(str(i) for i in sorted(ids))))
            if failures:
                fh.write('FALLOS\n')
                for b, err in failures:
                    fh.write('  [{}] id={} {!r}\n    {}\n'.format(
                        os.path.basename(b['library'].rstrip('/\\')),
                        b['id'], (b['title'] or '')[:60], err))
        print('Detalle: {}'.format(log))
    except Exception as exc:
        print('AVISO: no pude escribir el log: {}'.format(exc))

    if done:
        by_lib = defaultdict(list)
        for b in done:
            by_lib[b['library']].append(b['id'])
        print('\nPara revisarlos en Calibre (una linea por biblioteca):')
        for lib, ids in sorted(by_lib.items()):
            print('  {}'.format(lib))
            print('    id:{}'.format(','.join(str(i) for i in sorted(ids))))
    if failures:
        print('\nPrimeros fallos (el resto, en el log):')
        for b, err in failures[:10]:
            print('  id={} {!r}: {}'.format(b['id'], (b['title'] or '')[:45], err))
        print('\nLos AZW3 con DRM no se pueden convertir: son los fallos habituales.')
    if interrupted:
        pendientes = len(targets) - len(done) - len(failures)
        print('\nQuedaban ~{} registros por convertir.'.format(max(0, pendientes)))
        print('Repite el MISMO comando para continuar: los {} ya convertidos tienen'
              .format(len(done)))
        print('EPUB y quedan fuera del alcance, asi que no se repiten.')
        return 130

    print('\nAhora rescanea para aprovecharlo: los registros convertidos se leeran')
    print('como EPUB, mucho mas rapido, y compararan mejor.')
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(
        prog='dedupe_cli.py',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description='Duplicados EXACTOS al 100 % en una o muchas bibliotecas de '
                    'Calibre, sin usar la interfaz.',
        epilog='''Flujo en dos fases (no repite la parte lenta):

  1) ESCANEO (lento, solo lectura, puedes tener Calibre abierto)
       dedupe.cmd --root "D:\\Bibliotecas"
     -> informe HTML + plan JSON

  2) BORRADO (segundos, con Calibre cerrado)
       dedupe.cmd --apply "duplicados_20260726_101500.plan.json"

Otras formas de indicar las bibliotecas:
  dedupe.cmd -l "D:\\Lib A" -l "E:\\Lib B"
  dedupe.cmd --root "D:\\Bibliotecas" --prefer-library "D:\\Bibliotecas\\Principal"
''')
    g = p.add_argument_group('que bibliotecas')
    g.add_argument('--root', '-r', action='append', default=[], metavar='CARPETA',
                   help='Buscar todas las bibliotecas bajo esta carpeta. Repetible.')
    g.add_argument('--library', '-l', action='append', default=[], metavar='RUTA',
                   help='Biblioteca concreta. Repetible. Si no pasas ni --root ni '
                        '--library, se usa la que Calibre tiene abierta.')
    g.add_argument('--list-libraries', action='store_true',
                   help='Solo listar las bibliotecas que encontraria, y salir.')

    g = p.add_argument_group('escaneo')
    g.add_argument('--jobs', '-j', type=int, default=None,
                   help='Procesos/hilos en paralelo (por defecto: nucleos de la CPU).')
    g.add_argument('--keep', choices=KEEP_STRATEGIES, default='plugin',
                   help='Que copia conservar en cada grupo. Por defecto "plugin": '
                        'el mismo criterio que usa el plugin en Calibre (EPUB antes '
                        'que AZW3, edicion editorial antes que conversion casera, '
                        'y luego el fichero mas grande).')
    g.add_argument('--prefer-library', action='append', default=[], metavar='RUTA',
                   help='La copia se conserva en esta biblioteca siempre que exista '
                        'ahi. Repetible, en orden de preferencia.')
    g.add_argument('--backend', choices=('auto', 'calibre', 'sqlite'), default='auto',
                   help='Como leer las bibliotecas (por defecto: auto).')
    g.add_argument('--limit', type=int, default=0, metavar='N',
                   help='Analizar solo los N primeros libros de cada biblioteca (pruebas).')
    g.add_argument('--no-cache', action='store_true',
                   help='No usar la cache de huellas (releer todos los libros).')
    g.add_argument('--clear-cache', action='store_true',
                   help='Borrar la cache de huellas antes de escanear.')
    g.add_argument('--no-verify-formats', action='store_true',
                   help='No comprobar los formatos secundarios (p. ej. el AZW3) de '
                        'las copias a borrar. Mas rapido, pero podrias borrar un '
                        'registro cuyo AZW3 fuese en realidad otro libro.')
    g.add_argument('--epub-only', action='store_true',
                   help='Ignorar los AZW3. Util para una primera pasada rapida: '
                        'cada AZW3 hay que convertirlo con ebook-convert.')
    g.add_argument('--out-dir', metavar='CARPETA', default=None,
                   help='Donde dejar el informe y el plan (por defecto: '
                        'dedupe_out/ junto al repositorio).')
    g.add_argument('--report', '-o', metavar='FICHERO', help='Ruta del informe HTML.')
    g.add_argument('--plan', metavar='FICHERO', help='Ruta del plan JSON de borrado.')
    g.add_argument('--no-open', action='store_true',
                   help='No abrir el informe en el navegador al terminar.')

    g = p.add_argument_group('conversion de AZW3 (modo aparte, ESCRIBE en la biblioteca)')
    g.add_argument('--convert-azw3', action='store_true',
                   help='Convertir a EPUB los registros que solo tienen AZW3 y '
                        'anadir el EPUB al mismo registro, conservando el AZW3. '
                        'Requiere Calibre CERRADO. No escanea: hazlo despues.')
    g.add_argument('--ids', metavar='1,2,3',
                   help='Limitar la conversion a estos ids (para probar en pequeno).')
    g.add_argument('--convert-timeout', type=int, default=900, metavar='SEG',
                   help='Cortar una conversion que pase de estos segundos '
                        '(por defecto 900). Vale tambien para los AZW3 que se '
                        'convierten al vuelo durante el escaneo.')
    g.add_argument('--batch', type=int, default=100, metavar='N',
                   help='Cuantos EPUB se acumulan antes de anadirlos a la '
                        'biblioteca de una sola vez (por defecto 100). Mas alto '
                        'amortiza mejor el arranque de Calibre, pero mantiene mas '
                        'ficheros temporales en disco.')

    g = p.add_argument_group('borrado')
    g.add_argument('--apply', metavar='PLAN.JSON',
                   help='Ejecutar un plan de borrado ya generado. No vuelve a escanear.')
    g.add_argument('--delete', action='store_true',
                   help='Escanear y aplicar el plan en la misma pasada.')
    g.add_argument('--skip-cross', action='store_true',
                   help='No borrar copias que esten en una biblioteca distinta de la '
                        'que conserva el libro (solo informarlas).')
    g.add_argument('--yes', action='store_true', help='No pedir confirmacion.')
    g.add_argument('--no-export', action='store_true',
                   help='NO exportar una copia de los libros antes de borrarlos. '
                        'Desaconsejado: la copia exportada es la UNICA que '
                        'recupera los ficheros. La papelera de Calibre puede '
                        'quedar vacia tras un borrado por linea de comandos.')
    g.add_argument('--export-dir', metavar='CARPETA',
                   help='Donde exportar la copia previa (por defecto: '
                        'dedupe_out/exportadas_<fecha>).')
    g.add_argument('--no-backup', action='store_true',
                   help='No copiar metadata.db antes de borrar (no recomendado).')
    g.add_argument('--force-running', action='store_true',
                   help='Borrar aunque se detecte Calibre abierto (no recomendado).')
    g.add_argument('--tolerate-mtime', action='store_true',
                   help='Aceptar entradas cuyo fichero cambio de fecha pero no de '
                        'tamano ni de ruta.')

    p.add_argument('--inspect', metavar='FICHERO',
                   help='Diagnosticar UN libro: que capitulos se le extraen y '
                        'por que se descarta lo demas. Util para los que salen '
                        'como "sin contenido comparable".')
    p.add_argument('--cache-info', action='store_true',
                   help='Decir donde esta la cache y si es valida, sin escanear.')
    p.add_argument('--doctor', action='store_true',
                   help='Comprobar el entorno (interprete, lxml, calibredb) y salir.')
    p.add_argument('--verbose', '-v', action='store_true', help='Log detallado.')
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format='%(levelname)s %(name)s: %(message)s')

    # --- Fase 2 aislada: aplicar un plan ya calculado ---
    if args.inspect:
        check_lxml()
        return inspect_book(args.inspect)

    if args.doctor:
        doctor()
        return 0

    if args.cache_info:
        out_dir = args.out_dir or _DEFAULT_OUT_DIR
        cache_path = os.path.join(out_dir, CACHE_NAME)
        print('Firma actual del motor: {}'.format(engine_signature()))
        load_cache(cache_path)
        return 0

    # El tope vale para las dos vias: la conversion al vuelo del escaneo y la
    # de --convert-azw3.  Sin el, un AZW3 defectuoso cuelga un escaneo de horas.
    try:
        import extractor as _ex
        _ex.CONVERT_TIMEOUT = args.convert_timeout
    except Exception:
        pass

    if args.convert_azw3:
        check_lxml()
        libraries = resolve_libraries(args.library, args.root)
        if not libraries:
            raise SystemExit('Indica que bibliotecas: --root "..." o --library "..."')
        print('Bibliotecas: {}'.format(len(libraries)))
        for lib in libraries:
            print('  - {}'.format(lib))
        return run_convert_azw3(libraries, args)

    if args.apply:
        if not getattr(args, 'out_dir', None):
            args.out_dir = _DEFAULT_OUT_DIR
        plan = read_plan(args.apply)
        print('Plan: {}'.format(args.apply))
        print('Creado: {} | bibliotecas: {} | copias a borrar: {}'.format(
            plan.get('created'), len(plan.get('libraries', ())), plan.get('n_drop')))
        summary = apply_plan(plan, args)
        print('\nBorrados: {}'.format(summary['deleted']))
        return 0 if not summary['errors'] else 1

    # --- Fase 1: escaneo ---
    # Se comprueba ANTES de recorrer nada: si falta lxml, el error debe salir una
    # vez y claro, no como un fallo de extraccion repetido por cada libro.
    check_lxml()

    libraries = resolve_libraries(args.library, args.root)
    if not libraries:
        raise SystemExit(
            'No he encontrado ninguna biblioteca.\n'
            'Indica una carpeta raiz:  --root "D:\\Bibliotecas"\n'
            'o una biblioteca suelta:  --library "D:\\Calibre Library"')

    print('Bibliotecas encontradas: {}'.format(len(libraries)))
    for lib in libraries:
        print('  - {}'.format(lib))
    if args.list_libraries:
        return 0

    started = time.time()
    books, backend = load_all_books(libraries, None if args.backend == 'auto' else args.backend,
                                    limit_per_library=args.limit)
    print('Backend: {} | total de libros con EPUB/AZW3: {}'.format(backend, len(books)))
    if not books:
        raise SystemExit('No hay libros con formato EPUB o AZW3 que analizar.')

    # Reparto por formato: los AZW3 hay que convertirlos con ebook-convert, que
    # cuesta ordenes de magnitud mas que abrir un EPUB. Saberlo de antemano
    # explica la velocidad del escaneo.
    fmt_counts = defaultdict(int)
    for b in books:
        fmt_counts[b['format']] += 1
    print('Formatos: {}'.format(', '.join(
        '{} {}'.format(n, f) for f, n in sorted(fmt_counts.items()))))
    if fmt_counts.get('AZW3'):
        print('  ({} AZW3 requieren conversion con ebook-convert; '
              '--epub-only los omite)'.format(fmt_counts['AZW3']))

    if args.epub_only:
        before = len(books)
        books = [b for b in books if b['format'] != 'AZW3']
        print('  --epub-only: omito {} AZW3, quedan {} libros'.format(
            before - len(books), len(books)))
        if not books:
            raise SystemExit('No queda ningun EPUB que analizar.')

    out_dir = args.out_dir or _DEFAULT_OUT_DIR
    try:
        os.makedirs(out_dir, exist_ok=True)
    except Exception:
        out_dir = os.getcwd()

    # --- Cache: solo se leen los libros nuevos o modificados ---
    cache_path = None if args.no_cache else os.path.join(out_dir, CACHE_NAME)
    if args.clear_cache and cache_path and os.path.exists(cache_path):
        try:
            os.remove(cache_path)
            print('Cache borrada.')
        except Exception as exc:
            logger.warning('No se pudo borrar la cache: %s', exc)
    cache = load_cache(cache_path) if cache_path else {}
    hits, misses = split_cached(books, cache) if cache else ({}, list(books))
    if hits:
        print('Cache: {} libros ya conocidos, {} por leer.'.format(len(hits), len(misses)))

    fps = dict(hits)

    def _checkpoint(partial):
        """Va guardando la cache durante el escaneo."""
        if cache_path:
            save_cache(cache_path, update_cache(cache, misses, partial))

    if misses:
        try:
            # 'results=fps': los resultados se escriben directamente en el dict
            # del llamante, de modo que un Ctrl-C conserva lo ya leido.
            compute_fingerprints(
                misses, jobs=args.jobs,
                use_processes=not running_inside_calibre(),
                on_checkpoint=_checkpoint, results=fps)
        except KeyboardInterrupt:
            # Interrumpir un escaneo largo no debe perder lo ya calculado: se
            # guarda la cache y la siguiente pasada arranca donde se quedo.
            sys.stderr.write('\n')
            print('Interrumpido. Guardo la cache de lo ya leido...')
            _checkpoint(fps)
            print('Hecho. Repite el mismo comando y seguira donde lo dejo.')
            return 130
    if cache_path:
        entries = update_cache(cache, books, fps)
        save_cache(cache_path, entries)
        if os.path.exists(cache_path):
            print('Cache guardada: {} entradas ({:.1f} KB).'.format(
                len(entries), os.path.getsize(cache_path) / 1024.0))

    timing_summary(fps)
    groups, skipped = group_duplicates(books, fps)
    prefer_rank = build_prefer_rank(args.prefer_library)
    groups = [decide_group(g, args.keep, prefer_rank) for g in groups]

    # Antes de dar por buena ninguna copia a borrar, comprobar que TODOS sus
    # ficheros son el mismo libro, no solo el que se comparo.
    if not args.no_verify_formats:
        n_checked, n_moved = verify_all_formats(groups, cache, cache_path, jobs=args.jobs)
        if n_checked:
            print('  verificados {}; retirados del borrado por no coincidir: {}'.format(
                n_checked, n_moved))

    problem_books = books_with_issues(books, fps)
    if problem_books:
        print('Con problemas de formato (conviene reconvertirlos): {}'.format(
            len(problem_books)))

    n_drop = sum(len(g['drop']) for g in groups)
    n_blocked = sum(len(g['blocked']) for g in groups)
    n_cross = sum(1 for g in groups if g['cross'])
    reclaimable = sum(g['reclaimable'] for g in groups)

    print('\nGrupos duplicados: {} (entre bibliotecas: {})'.format(len(groups), n_cross))
    print('Copias sobrantes: {} | recuperable: {}'.format(n_drop, human_size(reclaimable)))
    if n_blocked:
        print('Protegidas (tienen formatos que la copia conservada no tiene): {}'.format(n_blocked))
    if skipped:
        print('No analizables: {}'.format(len(skipped)))

    stamp = time.strftime('%Y%m%d_%H%M%S')
    plan_path = args.plan or os.path.join(out_dir, 'duplicados_{}.plan.json'.format(stamp))
    plan = build_plan(groups, libraries, args.keep, skip_cross=args.skip_cross)
    write_plan(plan_path, plan)

    deleted = 0
    if args.delete and n_drop:
        summary = apply_plan(plan, args)
        deleted = summary['deleted']
    elif args.delete:
        print('Nada que borrar.')

    stats = {
        'libraries': libraries, 'backend': backend,
        'when': time.strftime('%Y-%m-%d %H:%M'), 'n_books': len(books),
        'n_drop': n_drop, 'n_cross': n_cross, 'reclaimable': reclaimable,
        'elapsed': time.time() - started, 'deleted': deleted > 0,
        'plan': plan_path, 'keep_strategy': args.keep,
        'problem_books': problem_books,
        'prefer_libraries': list(args.prefer_library or ()),
    }
    report = args.report or os.path.join(out_dir, 'duplicados_{}.html'.format(stamp))
    write_html_report(report, groups, skipped, stats)

    print('\nInforme: {}'.format(report))
    print('Plan   : {}'.format(plan_path))
    if not args.delete and n_drop:
        print('\nPara borrar, cierra Calibre y ejecuta:')
        print('  dedupe.cmd --apply "{}"'.format(plan_path))

    if not args.no_open:
        try:
            import webbrowser
            webbrowser.open('file://' + os.path.abspath(report).replace(os.sep, '/'))
        except Exception:
            pass
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('\nInterrumpido.')
        sys.exit(130)
