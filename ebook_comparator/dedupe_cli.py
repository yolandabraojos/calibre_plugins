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
sin --permanent, de modo que va a la papelera de la biblioteca.
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
import sqlite3
import subprocess
import sys
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
        for fmt in SUPPORTED_FORMATS:
            if fmt in fmts:
                try:
                    p = api.format_abspath(book_id, fmt)
                except Exception:
                    p = None
                if p and os.path.exists(p):
                    chosen_fmt, chosen_path = fmt, p
                    break
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
        for fmt in SUPPORTED_FORMATS:
            if fmt in fmts:
                name, usize = fmts[fmt]
                p = os.path.join(library_path,
                                 (bookpath or '').replace('/', os.sep),
                                 '{}.{}'.format(name, fmt.lower()))
                if os.path.exists(p):
                    chosen_fmt, chosen_path, chosen_size = fmt, p, usize
                    break
        if not chosen_fmt:
            continue
        books.append({
            'id': book_id, 'title': (title or '').strip(),
            'authors': ' & '.join(authors_by_book.get(book_id, ())),
            'format': chosen_fmt, 'path': chosen_path,
            'size': _safe_size(chosen_path) or (chosen_size or 0),
            'mtime': _safe_mtime(chosen_path),
            'formats': sorted(fmts.keys()), 'has_cover': bool(has_cover),
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
    """Devuelve {ruta: registro} valido, o {} si no sirve."""
    if not cache_path or not os.path.exists(cache_path):
        return {}
    try:
        with codecs.open(cache_path, 'r', 'utf-8') as fh:
            data = json.load(fh)
    except Exception as exc:
        logger.warning('Cache ilegible (%s): la ignoro.', exc)
        return {}
    if data.get('engine') != engine_signature():
        print('  (la cache es de otra version del motor de extraccion: la descarto)')
        return {}
    return data.get('books') or {}


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
        logger.warning('No se pudo guardar la cache: %s', exc)


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
           'cached': False, 'origin': 'desconocido', 'origin_reasons': []}
    try:
        import extractor
        import comparator
        out['sha1'] = extractor.file_sha1(path)
        # Procedencia (editorial vs conversion casera) en la misma pasada: el
        # fichero ya esta abierto, asi que no cuesta E/S adicional.
        origin, reasons = extractor.epub_provenance(path)
        out['origin'] = origin
        out['origin_reasons'] = reasons
        chapters, ignored = extractor.extract_book_chapters(path)
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
        sha1s = {m['sha1'] for m in members if m['sha1']}
        libs = {m['library'] for m in members}
        groups.append({
            'fingerprint': fp,
            'books': members,
            'binary': len(sha1s) == 1,
            'cross': len(libs) > 1,
            'libraries': sorted(libs),
        })
    # Primero los cruzados (mas informativos), luego por tamano de grupo.
    groups.sort(key=lambda g: (not g['cross'], -len(g['books']),
                               -sum(b['size'] for b in g['books'])))
    return groups, skipped


def _origin_rank(origin):
    """Rango de procedencia (menor gana), delegando en extractor.py."""
    try:
        import extractor
        return extractor.origin_rank(origin)
    except Exception:
        return 1


KEEP_STRATEGIES = ('plugin', 'best', 'largest', 'smallest', 'oldest', 'newest')


def _keep_sort_key(strategy, prefer_rank):
    """
    Clave de orden: el PRIMER libro tras ordenar es el que se conserva.

    'prefer_rank' mapea ruta de biblioteca -> prioridad (menor gana).  Cuando se
    han indicado bibliotecas preferidas con --prefer-library, esa preferencia
    manda sobre cualquier otro criterio: es lo que permite decir "la copia buena
    vive siempre en mi biblioteca principal".
    """
    def rank(b):
        return prefer_rank.get(os.path.realpath(b['library']), 10 ** 6)

    if strategy == 'largest':
        return lambda b: (rank(b), -b['size'], b['lib_index'], b['id'])
    if strategy == 'smallest':
        return lambda b: (rank(b), b['size'], b['lib_index'], b['id'])
    if strategy == 'oldest':
        return lambda b: (rank(b), b['lib_index'], b['id'])
    if strategy == 'newest':
        return lambda b: (rank(b), -b['lib_index'], -b['id'])

    # 'plugin' (= 'best'): EL MISMO criterio que usa el plugin al marcar
    # duplicados en Calibre, en este orden:
    #   1. Biblioteca preferida (--prefer-library). Solo existe en el CLI.
    #   2. EPUB antes que AZW3. Es la regla clara del plugin.
    #   3. Edicion editorial antes que conversion casera de Calibre.
    #   4. Fichero mas GRANDE. Es lo que hace el codigo del plugin (su docstring
    #      y su red de seguridad decian lo contrario: se corrigio en ui.py).
    #   5. Con portada antes que sin portada, y por ultimo id, para que el
    #      resultado sea estable y reproducible entre ejecuciones.
    return lambda b: (
        rank(b),
        0 if b['format'] == 'EPUB' else 1,
        _origin_rank(b.get('origin')),
        -b['size'],
        0 if b.get('has_cover') else 1,
        b['lib_index'],
        b['id'],
    )


def decide_group(group, strategy='best', prefer_rank=None):
    """
    Marca en el grupo cual se conserva ('keep') y cuales sobran ('drop').

    Salvaguarda: si un candidato a borrar tiene FORMATOS que la copia conservada
    no tiene (p. ej. tambien un PDF), borrarlo perderia ese fichero.  Se marca
    'blocked' y no se borra, aunque el EPUB sea identico.
    """
    prefer_rank = prefer_rank or {}
    members = sorted(group['books'], key=_keep_sort_key(strategy, prefer_rank))
    keep = members[0]
    keep_fmts = set(keep.get('formats') or ())
    drops, blocked = [], []
    for b in members[1:]:
        extra = sorted(set(b.get('formats') or ()) - keep_fmts)
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
    return group


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


def delete_ids(library_path, ids, batch=200):
    """
    Borra 'ids' de 'library_path' con calibredb (sin --permanent: papelera de la
    biblioteca, reversible).  Devuelve (n_borrados, errores).
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
        print('El borrado lo ejecuta Calibre (papelera de la biblioteca): es reversible.')
        try:
            answer = input('Escribe BORRAR para confirmar: ').strip()
        except EOFError:
            answer = ''
        if answer != 'BORRAR':
            print('Cancelado: no se ha borrado nada.')
            return {'deleted': 0, 'errors': [], 'rejected': rejected, 'backups': {}}

    deleted, errors, backups = 0, [], {}
    for lib, entries in sorted(ok_by_lib.items()):
        if not args.no_backup:
            bk = backup_metadata_db(lib)
            backups[lib] = bk
            print('  copia de seguridad: {}'.format(bk or 'FALLIDA'))
        n, errs = delete_ids(lib, [e['id'] for e in entries])
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


def _row(b, role, libraries, extra_tags=()):
    cls = {'keep': 'keep', 'blocked': 'blocked'}.get(role, '')
    lab = {'keep': ('keep', 'CONSERVAR'), 'drop': ('drop', 'borrar'),
           'blocked': ('blk', 'no se borra')}[role]
    extra = ''
    if b.get('extra_formats'):
        extra = ' <span class="tag blk">solo aqui: {}</span>'.format(
            html.escape(', '.join(b['extra_formats'])))
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
    why = ['EPUB' if keep['format'] == 'EPUB' else keep['format']]
    if (keep.get('origin') or '') == 'editorial':
        why.append('edicion editorial')
    elif (keep.get('origin') or '') == 'calibre':
        why.append('conversion de Calibre')
    why.append('el mayor de {} ({})'.format(len(g['books']), human_size(keep['size'])))
    parts.append('<p class="why">Se conserva id={} porque: {}.{}</p>'.format(
        keep['id'], html.escape(' > '.join(why)),
        ' Motivos de procedencia: ' + html.escape('; '.join(keep.get('origin_reasons') or []))
        if keep.get('origin_reasons') else ''))
    if g['blocked']:
        parts.append('<p class="meta">Las filas en naranja NO se borran: tienen '
                     'formatos que la copia conservada no tiene y se perderian.</p>')
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

    p.append('<header class="summary"><div class="stats">')
    for v, l in ((stats['n_books'], 'libros analizados'),
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
            p.append('<span class="idsearch">id:{}</span>'.format(
                ','.join(str(i) for i in sorted(ids))))
        p.append('</div>')

    if skipped:
        p.append('<div class="card"><details><summary>{} libros no analizables'
                 '</summary><table><thead><tr><th>id</th><th>Biblioteca</th>'
                 '<th>Titulo</th><th>Motivo</th></tr></thead><tbody>'.format(len(skipped)))
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

    g = p.add_argument_group('borrado')
    g.add_argument('--apply', metavar='PLAN.JSON',
                   help='Ejecutar un plan de borrado ya generado. No vuelve a escanear.')
    g.add_argument('--delete', action='store_true',
                   help='Escanear y aplicar el plan en la misma pasada.')
    g.add_argument('--skip-cross', action='store_true',
                   help='No borrar copias que esten en una biblioteca distinta de la '
                        'que conserva el libro (solo informarlas).')
    g.add_argument('--yes', action='store_true', help='No pedir confirmacion.')
    g.add_argument('--no-backup', action='store_true',
                   help='No copiar metadata.db antes de borrar (no recomendado).')
    g.add_argument('--force-running', action='store_true',
                   help='Borrar aunque se detecte Calibre abierto (no recomendado).')
    g.add_argument('--tolerate-mtime', action='store_true',
                   help='Aceptar entradas cuyo fichero cambio de fecha pero no de '
                        'tamano ni de ruta.')

    p.add_argument('--doctor', action='store_true',
                   help='Comprobar el entorno (interprete, lxml, calibredb) y salir.')
    p.add_argument('--verbose', '-v', action='store_true', help='Log detallado.')
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format='%(levelname)s %(name)s: %(message)s')

    # --- Fase 2 aislada: aplicar un plan ya calculado ---
    if args.doctor:
        doctor()
        return 0

    if args.apply:
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
        save_cache(cache_path, update_cache(cache, books, fps))

    timing_summary(fps)
    groups, skipped = group_duplicates(books, fps)
    prefer_rank = build_prefer_rank(args.prefer_library)
    groups = [decide_group(g, args.keep, prefer_rank) for g in groups]

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
        'plan': plan_path,
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
    sys.exit(main())
