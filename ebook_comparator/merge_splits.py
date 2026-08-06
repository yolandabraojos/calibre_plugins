# -*- coding: utf-8 -*-
"""
Une los fragmentos '..._split_NNN.html' que dejo una conversion de Calibre.

QUE PROBLEMA RESUELVE
---------------------
Al convertir a EPUB, Calibre trocea los ficheros HTML por dos motivos
(calibre/ebooks/oeb/transforms/split.py):

  1. Saltos de pagina (CSS page-break-*), que si corresponden a capitulos.
  2. TAMANO: si un fichero pasa de 'flow_size' (260 KB por defecto), lo parte
     por el punto "razonable" mas cercano a la MITAD -- probando h1..h6, div,
     pre, hr, p, div, br, li -- y repite sobre cada mitad hasta que todas bajan
     del limite.  Ese corte NO respeta capitulos.

Con decenas de fragmentos manda el motivo 2: un capitulo (o el libro entero)
partido por la mitad una y otra vez.  El informe de dedupe_cli.py lo marca como
'muy_troceado' (>= 20 ficheros con '_split_' en el nombre).

Reconvertir con --flow-size 0 NO lo arregla: el paso Split solo puede partir
mas los ficheros que ya existen, nunca junta dos.  Hay que fusionarlos.

CRITERIO DE FUSION (no hay que adivinar nada)
---------------------------------------------
Cuando Calibre parte un fichero, los trozos se llaman '<original>_split_NNN' y
quedan CONTIGUOS en el spine, en el sitio del original.  Asi que:

  - Se recorre el spine en orden.
  - Se agrupan los ficheros CONSECUTIVOS cuyo nombre, al quitarle los sufijos
    '_split_NNN' finales, coincide.
  - Cada grupo era un unico fichero: se fusiona en el primero (el master).

La fusion la hace la API del editor de Calibre
(calibre.ebooks.oeb.polish.split.merge), la misma que el boton "Combinar":
migra enlaces, renombra anclas repetidas, arrastra las hojas de estilo y
corrige el indice.  No se reimplementa nada de eso a mano.

RED DE SEGURIDAD
----------------
  - Exige Calibre cerrado (escribe en la biblioteca).
  - Copia el EPUB original a dedupe_out/fragmentos_unidos_<fecha>/ ANTES de nada.
  - Compara el TEXTO del EPUB original con el del fusionado (mismo extractor
    que usa el escaneo).  Si no coincide, ese libro NO se instala.
  - Solo entonces sustituye el formato con add_format(replace=True), que
    actualiza tambien tamano y fecha en metadata.db.
  - Sin --apply no toca nada: solo informa.

USO
---
    merge.cmd --root "D:\\Bibliotecas"              # informe, no toca nada
    merge.cmd --root "D:\\Bibliotecas" --apply      # fusiona (Calibre cerrado)
    merge.cmd --library "D:\\Lib" --ids 1,2 --apply # prueba con dos libros
"""

from __future__ import print_function

import argparse
import codecs
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import threading

import dedupe_cli as D
import extractor


# Las funciones de clasificacion de fragmentos (group_spine,
# classify_fragment_start, explain_tramos...) y los umbrales por defecto
# viven en extractor.py desde el 2026-08-06: asi el escaneo de dedupe_cli.py
# (extract_epub_chapters, al decidir 'muy_troceado') y la fusion de aqui usan
# EXACTAMENTE el mismo criterio, sin mantener dos copias que puedan discrepar.
from extractor import (
    DEFAULT_MIN_SPLITS,
    DEFAULT_MAX_MERGED_KB,
    split_base,
    is_split_name,
    group_spine,
    size_bounded_subgroups,
    classify_fragment_start,
    chapter_runs_from_kinds,
    explain_tramos,
    chapter_and_size_bounded_groups,
)


def count_splits(epub_path):
    """Cuantos ficheros '_split_' tiene el EPUB (sin abrirlo con Calibre)."""
    import zipfile
    try:
        with zipfile.ZipFile(epub_path) as zf:
            return sum(1 for n in zf.namelist() if '_split_' in n.lower())
    except Exception:
        return 0


def book_text(path):
    """
    Texto del CUERPO del libro entero, normalizado, para comprobar que la fusion
    no ha perdido ni movido nada.

    Se lee solo el <body> a proposito, y no se reutiliza extractor: su
    _html_to_text conserva el <title> de la cabecera, y cada fragmento
    '_split_NNN' lleva el suyo.  Al fusionar, las cabeceras de los ficheros
    absorbidos desaparecen (es lo correcto: sobra un <title> por trozo), asi que
    comparar incluyendo cabeceras marcaria como "texto cambiado" practicamente
    todos los libros y no se instalaria ninguno.  Comprobado con un EPUB de
    prueba: la unica diferencia eran los <title> repetidos.

    Tampoco se salta jackets ni ficheros de sistema: aqui no se busca una huella
    comparable entre libros distintos, sino que el MISMO libro siga diciendo lo
    mismo antes y despues.  Cuanto menos se filtre, mas estricta es la prueba.
    """
    import zipfile
    from lxml import etree

    parts = []
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        ordered = [n for n in extractor._get_spine_order(zf, names)
                   if n in names]
        resto = sorted(n for n in names
                       if n not in set(ordered) and extractor._is_html_file(n))
        for name in ordered + resto:
            try:
                raw = zf.read(name)
            except Exception:
                continue
            try:
                root = etree.fromstring(
                    raw, etree.HTMLParser(recover=True, encoding='utf-8'))
                if root is None:
                    continue
                bodies = root.xpath('//body')
                if not bodies:
                    continue
                for tag in root.iter('script', 'style'):
                    tag.text = tag.tail = None
                parts.append(' '.join(
                    t for body in bodies for t in body.itertext()))
            except Exception:
                continue
    return extractor._normalize(' '.join(parts))


# ---------------------------------------------------------------------------
# Script que corre DENTRO del interprete de Calibre
# ---------------------------------------------------------------------------
# Se paga UN arranque de Calibre para todo el lote, no uno por libro: arrancar
# Calibre cuesta ~2 s y con decenas de libros eso domina el tiempo total (misma
# leccion que con 'calibredb add_format' en --convert-azw3).
_MERGE_SCRIPT = r"""
import json, os, re, sys, traceback

payload = json.load(open(sys.argv[-1], 'rb'))
sys.path.insert(0, payload['module_dir'])
from merge_splits import group_spine, explain_tramos, classify_fragment_start

from calibre.ebooks.oeb.polish.container import get_container
from calibre.ebooks.oeb.polish.split import merge

max_size = payload['max_merged_bytes']
out = []
for item in payload['items']:
    rec = {'uid': item['uid'], 'error': None, 'groups': 0, 'tramos': 0,
           'before': 0, 'after': 0, 'out': None, 'reasons': {}}
    try:
        container = get_container(item['src'], tweak_mode=True)
        names = [n for n, linear in container.spine_names]
        rec['before'] = len(names)
        groups = group_spine(names)
        rec['groups'] = len(groups)
        if not groups:
            out.append(rec)
            continue
        merged_away = 0
        for g in groups:
            # Tamano de cada fragmento en bytes (red de seguridad para no
            # fusionar de golpe un grupo entero si eso da un fichero enorme) Y
            # como empieza cada uno -- titulo, texto tipo "Capitulo 5" o
            # "Agradecimientos" sin etiqueta, indice, o portadilla de imagen
            # (para NO cruzar un capitulo/indice real, que manda sobre el
            # tamano).  Ver explain_tramos: cada tramo trae SU MOTIVO, que se
            # cuenta en rec['reasons'] para poder explicar en el informe por
            # que estos ficheros no se fusionaron entre si.
            sizes = [len(container.raw_data(n, decode=False)) for n in g]
            kinds = [classify_fragment_start(container.parsed(n)) for n in g]
            for idxs, motivo in explain_tramos(sizes, kinds, max_size):
                clave = 'corte por tamano' if motivo.startswith('corte por tamano') else motivo
                rec['reasons'][clave] = rec['reasons'].get(clave, 0) + 1
                if len(idxs) < 2:
                    continue
                names_tramo = [g[i] for i in idxs]
                merge(container, 'text', names_tramo, names_tramo[0])
                merged_away += len(names_tramo) - 1
                rec['tramos'] += 1
        container.commit(item['dst'])
        rec['after'] = rec['before'] - merged_away
        rec['out'] = item['dst']
    except Exception as exc:
        rec['error'] = '{}: {}'.format(type(exc).__name__, exc)
        sys.stderr.write(traceback.format_exc())
    out.append(rec)

sys.stdout.write('MERGE_RESULT ' + json.dumps(out))
"""


# Instalacion del resultado: replace=True sustituye el EPUB del registro y
# actualiza tamano/fecha en metadata.db (copiar el fichero a mano los dejaria
# desincronizados).
_INSTALL_SCRIPT = r"""
import json, sys
payload = json.load(open(sys.argv[-1], 'rb'))
from calibre.library import db as _db

out = []
for library, items in payload['by_library'].items():
    lib = _db(library)
    api = getattr(lib, 'new_api', lib)
    for uid, book_id, path in items:
        try:
            with open(path, 'rb') as fh:
                api.add_format(int(book_id), 'EPUB', fh, replace=True)
            out.append([uid, None])
        except Exception as exc:
            out.append([uid, '{}: {}'.format(type(exc).__name__, exc)])
    try:
        lib.close()
    except Exception:
        pass
sys.stdout.write('INSTALL_RESULT ' + json.dumps(out))
"""


def _kill_proc_tree(proc):
    """
    Mata 'proc' Y SUS HIJOS.  Hace falta lo de "y sus hijos" a proposito: el
    proceso que se lanza aqui es un calibre-debug.exe que a su vez es OTRO
    proceso de Calibre por dentro (arranca su propio interprete), asi que
    matar solo al de arriba puede dejar corriendo al de verdad.  Mismo patron
    que '_terminate_running_converts' en dedupe_cli.py.
    """
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


# Proceso de calibre-debug en marcha, para poder matarlo si llega un Ctrl-C.
_RUNNING_PROC = None
_RUNNING_LOCK = threading.Lock()


def _run_calibre_script(script_text, payload_obj, workdir, marker, timeout):
    """
    Ejecuta un script bajo calibre-debug y devuelve (datos, error_global).

    OJO CON EL TIMEOUT LARGO: en Windows, 'subprocess.run(..., timeout=X)' (o
    'Popen.communicate(timeout=X)') con una X grande deja Ctrl-C sin efecto
    durante TODO ese tiempo.  La espera del proceso hijo es UNA sola llamada
    nativa (WaitForSingleObject) que no devuelve el control al interprete de
    Python hasta que el hijo termina o expira el timeout; y Python solo puede
    comprobar si ha llegado una senal (y lanzar KeyboardInterrupt) cuando ese
    control vuelve al bucle del interprete.  Con un timeout de media hora,
    Ctrl-C no hacia NADA durante media hora -- y como el hijo real es un
    calibre-debug.exe ANIDADO lanzado con CREATE_NO_WINDOW, seguia corriendo
    de fondo sin ninguna ventana visible aunque la consola volviera al prompt.

    Por eso aqui no se espera de una vez: se llama a 'communicate(timeout=1)'
    en un bucle.  Cada segundo se devuelve el control a Python, que es el
    hueco que necesita para atender un Ctrl-C.  Al interrumpir (o al superar
    el timeout total) se mata el arbol de procesos completo con
    '_kill_proc_tree', no solo el proceso de arriba.
    """
    exe = D.find_calibre_debug()
    if not exe:
        return None, ('no encuentro calibre-debug: anade la carpeta de Calibre '
                      'al PATH (suele ser "C:\\Program Files\\Calibre2")')
    script = os.path.join(workdir, '_merge_job.py')
    payload = os.path.join(workdir, '_merge_payload.json')
    try:
        with codecs.open(script, 'w', 'utf-8') as fh:
            fh.write(script_text)
        with codecs.open(payload, 'w', 'utf-8') as fh:
            json.dump(payload_obj, fh)
    except Exception as exc:
        return None, 'no pude preparar el script: {}'.format(exc)

    kwargs = {}
    if sys.platform == 'win32':
        kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    else:
        kwargs['start_new_session'] = True  # grupo propio, para poder matarlo entero

    global _RUNNING_PROC
    try:
        proc = subprocess.Popen([exe, '-e', script, '--', payload],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                **kwargs)
    except Exception as exc:
        return None, '{}: {}'.format(type(exc).__name__, exc)

    with _RUNNING_LOCK:
        _RUNNING_PROC = proc
    out_bytes = err_bytes = b''
    try:
        deadline = time.time() + timeout
        while True:
            try:
                out_bytes, err_bytes = proc.communicate(timeout=1)
                break
            except subprocess.TimeoutExpired:
                if time.time() >= deadline:
                    _kill_proc_tree(proc)
                    try:
                        out_bytes, err_bytes = proc.communicate()
                    except Exception:
                        pass
                    return None, 'calibre-debug paso de {} s y se ha cortado.'.format(timeout)
                continue
    except KeyboardInterrupt:
        print('\n  Cortando calibre-debug...')
        _kill_proc_tree(proc)
        try:
            proc.communicate()
        except Exception:
            pass
        raise
    finally:
        with _RUNNING_LOCK:
            if _RUNNING_PROC is proc:
                _RUNNING_PROC = None

    text = (out_bytes or b'').decode('utf-8', 'replace')
    if marker not in text:
        err = (err_bytes or b'').decode('utf-8', 'replace').strip()
        return None, (err[-500:] or 'calibre-debug no devolvio resultados '
                                    '(codigo {})'.format(proc.returncode))
    try:
        return json.loads(text.split(marker, 1)[1].strip()), None
    except Exception as exc:
        return None, 'respuesta ilegible: {}'.format(exc)


def find_targets(books, only_ids=None, min_splits=DEFAULT_MIN_SPLITS):
    """Registros con EPUB y suficientes fragmentos '_split_' como para molestar."""
    out = []
    for b in books:
        path = (b.get('format_paths') or {}).get('EPUB')
        if not path or not os.path.exists(path):
            continue
        if only_ids and b['id'] not in only_ids:
            continue
        n = count_splits(path)
        if n < min_splits:
            continue
        rec = dict(b)
        rec['epub'] = path
        rec['n_split'] = n
        out.append(rec)
    out.sort(key=lambda r: (r['lib_index'], r['id']))
    return out


def run(libraries, args):
    only_ids = None
    if args.ids:
        try:
            only_ids = {int(x) for x in re.split(r'[,\s]+', args.ids) if x.strip()}
        except ValueError:
            raise SystemExit('--ids espera numeros separados por comas: --ids 1,2,3')

    books, backend = D.load_all_books(libraries, None if args.backend == 'auto'
                                      else args.backend)
    targets = find_targets(books, only_ids, args.min_splits)
    print('\nRegistros con EPUB: {} | con >= {} fragmentos: {}'.format(
        sum(1 for b in books if (b.get('format_paths') or {}).get('EPUB')),
        args.min_splits, len(targets)))
    if not targets:
        print('Nada que fusionar.')
        return 0

    for r in targets[:40]:
        print('  [{}] {} fragmentos  id:{}  {}'.format(
            D._short_lib(r['library'], libraries), r['n_split'], r['id'],
            (r.get('title') or '')[:60]))
    if len(targets) > 40:
        print('  ... y {} mas'.format(len(targets) - 40))

    if not args.apply:
        print('\nEsto ha sido solo un INFORME: no se ha tocado nada.')
        print('Para fusionar de verdad, repite el comando con --apply')
        print('(con Calibre CERRADO).')
        return 0

    if D.calibre_maybe_running() and not args.force_running:
        print('\nParece que Calibre esta ABIERTO. No toco nada.')
        print('Hay que escribir en la biblioteca: cierra Calibre y repite')
        print('(o usa --force-running si estas segura).')
        return 1

    print('\nSe fusionaran los fragmentos de {} libro(s).'.format(len(targets)))
    print('Antes se guarda una copia del EPUB original, y un libro solo se')
    print('sustituye si su TEXTO sigue siendo identico despues de fusionar.')
    if not args.yes:
        try:
            if input('Escribe UNIR para continuar: ').strip() != 'UNIR':
                print('Cancelado: no se ha tocado nada.')
                return 0
        except EOFError:
            print('Cancelado.')
            return 0

    return _apply(targets, libraries, args)


def _apply(targets, libraries, args):
    stamp = time.strftime('%Y%m%d_%H%M%S')
    out_dir = args.out_dir or D._DEFAULT_OUT_DIR
    backup_dir = os.path.join(out_dir, 'fragmentos_unidos_{}'.format(stamp))
    try:
        os.makedirs(backup_dir, exist_ok=True)
    except Exception as exc:
        print('No puedo crear {}: {}'.format(backup_dir, exc))
        return 1

    # 1. Copia del EPUB original.  Es la unica forma de deshacer esto: add_format
    #    con replace=True sustituye el fichero y no deja rastro del anterior.
    print('\nCopia de los EPUB originales en:')
    print('  {}'.format(backup_dir))
    saved, failed_backup = [], []
    for r in targets:
        dest = os.path.join(backup_dir, '{}_{}_{}.epub'.format(
            r['lib_index'], r['id'],
            re.sub(r'[^\w.-]+', '_', (r.get('title') or 'libro'))[:60]))
        try:
            shutil.copy2(r['epub'], dest)
            r['backup'] = dest
            saved.append(r)
        except Exception as exc:
            failed_backup.append((r, str(exc)))
    for r, exc in failed_backup:
        print('  ! id:{} sin copia ({}), lo omito.'.format(r['id'], exc))
    if not saved:
        print('No he podido copiar ningun original. No sigo.')
        return 1
    print('  {} copias guardadas.'.format(len(saved)))

    # 2. Respaldo de metadata.db, una vez por biblioteca.
    if not args.no_backup:
        for lib in sorted({r['library'] for r in saved}):
            bk = D.backup_metadata_db(lib)
            print('  copia de metadata.db: {}'.format(bk or 'FALLIDA'))

    workdir = tempfile.mkdtemp(prefix='merge_splits_')
    try:
        return _merge_and_install(saved, libraries, workdir, args, stamp, out_dir)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _format_reasons(reasons):
    """
    Convierte el histograma {motivo: cuantos tramos} que trae cada libro en
    rec['reasons'] (ver _MERGE_SCRIPT/explain_tramos) en una frase para el
    informe, de mas a menos frecuente.  Sirve tanto para explicar por que NO
    se fusiono nada (cada tramo es su propio capitulo/indice/portadilla) como
    para detallar, en los libros que si se fusionaron, por que quedan varios
    ficheros en vez de uno solo.
    """
    if not reasons:
        return 'sin datos'
    partes = sorted(reasons.items(), key=lambda kv: -kv[1])
    return ', '.join('{}: {}'.format(motivo, n) for motivo, n in partes)


def _merge_and_install(targets, libraries, workdir, args, stamp, out_dir):
    # 3. Fusion, en un solo arranque de Calibre para todo el lote.
    items = []
    for r in targets:
        dst = os.path.join(workdir, 'merged_{}_{}.epub'.format(r['lib_index'], r['id']))
        r['merged'] = dst
        items.append({'uid': r['uid'], 'src': r['epub'], 'dst': dst})

    print('\nFusionando fragmentos (un solo arranque de Calibre, ficheros de '
          'hasta {} KB)...'.format(args.max_merged_kb))
    print('  Un fragmento que empieza un capitulo, una seccion (agradecimientos,')
    print('  sobre la autora...), el indice o una portadilla de imagen NO se')
    print('  fusiona con el de al lado: el detalle de por que sale en cada')
    print('  fichero va en el informe.')
    results, err = _run_calibre_script(
        _MERGE_SCRIPT,
        {'module_dir': _HERE, 'items': items,
         'max_merged_bytes': args.max_merged_kb * 1024},
        workdir, 'MERGE_RESULT ', max(600, 30 * len(items)))
    if err:
        print('  ! la fusion fallo: {}'.format(err))
        print('  No se ha modificado ninguna biblioteca; tus originales siguen')
        print('  en su sitio y ademas hay copia en la carpeta de respaldo.')
        return 1

    by_uid = {r['uid']: r for r in targets}
    merged_ok, problems = [], []
    for rec in results:
        r = by_uid.get(rec['uid'])
        if r is None:
            continue
        if rec['error']:
            problems.append((r, rec['error']))
            continue
        r['reasons'] = rec.get('reasons') or {}
        if not rec['tramos']:
            # Puede haber grupos detectados y aun asi cero fusiones: pasa si
            # cada fragmento YA es su propio capitulo/seccion/indice/portadilla
            # (nada que fusionar de verdad) o si cada uno por separado ya
            # supera --max-merged-kb.  rec['reasons'] trae el desglose exacto
            # -- se lo explicamos al informe en vez de dar un motivo generico.
            problems.append((r, 'nada que fusionar ({})'.format(
                _format_reasons(r['reasons']))))
            continue
        r['groups'] = rec['groups']
        r['tramos'] = rec['tramos']
        r['before'] = rec['before']
        r['after'] = rec['after']
        r['max_merged_kb'] = args.max_merged_kb
        merged_ok.append(r)

    print('  fusionados: {} | sin cambios o con error: {}'.format(
        len(merged_ok), len(problems)))
    if not merged_ok:
        _write_report(targets, [], problems, out_dir, stamp, applied=False)
        return 1

    # 4. Comprobacion de TEXTO.  Es la verificacion que de verdad importa: la
    #    fusion mueve nodos entre ficheros, asi que el texto resultante tiene
    #    que ser exactamente el mismo.  Si no lo es, ese libro no se instala.
    print('\nComprobando que el texto no ha cambiado...')
    verified = []
    for i, r in enumerate(merged_ok, 1):
        try:
            before = book_text(r['epub'])
            after = book_text(r['merged'])
        except Exception as exc:
            problems.append((r, 'no he podido releer el libro: {}'.format(exc)))
            continue
        if not after:
            problems.append((r, 'el EPUB fusionado no da texto: lo descarto'))
            continue
        if before != after:
            problems.append((r, 'el texto CAMBIA al fusionar ({} -> {} caracteres): '
                                'lo descarto'.format(len(before), len(after))))
            continue
        verified.append(r)
        if i % 10 == 0 or i == len(merged_ok):
            print('  {}/{}'.format(i, len(merged_ok)))
    print('  con el texto intacto: {} de {}'.format(len(verified), len(merged_ok)))
    if not verified:
        _write_report(targets, [], problems, out_dir, stamp, applied=False)
        return 1

    if args.dry_run:
        print('\n--dry-run: la fusion se ha hecho y verificado, pero NO se instala.')
        print('Los EPUB fusionados estaban en un temporal y se descartan.')
        _write_report(targets, verified, problems, out_dir, stamp, applied=False)
        return 0

    # 5. Instalacion: sustituye el formato EPUB del registro.
    by_library = {}
    for r in verified:
        by_library.setdefault(r['library'], []).append(
            [r['uid'], r['id'], r['merged']])
    print('\nInstalando en las bibliotecas...')
    installed, err = _run_calibre_script(
        _INSTALL_SCRIPT, {'by_library': by_library},
        workdir, 'INSTALL_RESULT ', max(600, 20 * len(verified)))
    if err:
        print('  ! la instalacion fallo: {}'.format(err))
        print('  Las bibliotecas NO se han modificado.')
        _write_report(targets, verified, problems, out_dir, stamp, applied=False)
        return 1

    done = []
    for uid, msg in installed:
        r = by_uid.get(uid)
        if r is None:
            continue
        if msg:
            problems.append((r, 'no se pudo instalar: {}'.format(msg)))
        else:
            done.append(r)
    print('  sustituidos: {}'.format(len(done)))

    report = _write_report(targets, done, problems, out_dir, stamp, applied=True)
    print('\nResumen:')
    print('  libros con los fragmentos unidos: {}'.format(len(done)))
    if done:
        tot_before = sum(r.get('before', 0) for r in done)
        tot_after = sum(r.get('after', 0) for r in done)
        print('  ficheros HTML: {} -> {}'.format(tot_before, tot_after))
    if problems:
        print('  no tocados: {} (motivos en el informe)'.format(len(problems)))
    print('  copias de los EPUB originales: {}'.format(
        os.path.join(out_dir, 'fragmentos_unidos_{}'.format(stamp))))
    print('  informe: {}'.format(report))
    print('\nPara deshacer un libro: vuelve a anadir su EPUB de la carpeta de')
    print('copias al mismo registro (Calibre: Anadir formato a este libro).')
    return 0 if not problems else 1


def _write_report(targets, done, problems, out_dir, stamp, applied):
    """Informe de texto: que se unio, que no y por que."""
    path = os.path.join(out_dir, 'fragmentos_unidos_{}.txt'.format(stamp))
    try:
        os.makedirs(out_dir, exist_ok=True)
        with codecs.open(path, 'w', 'utf-8') as fh:
            fh.write('Fusion de fragmentos _split_  ({})\n'.format(stamp))
            fh.write('Estado: {}\n\n'.format(
                'APLICADO' if applied else 'NO aplicado (nada se ha sustituido)'))
            fh.write('Candidatos examinados: {}\n'.format(len(targets)))
            fh.write('Unidos: {}\n'.format(len(done)))
            fh.write('No tocados: {}\n\n'.format(len(problems)))
            if done:
                fh.write('--- UNIDOS ---\n')
                by_lib = {}
                for r in done:
                    by_lib.setdefault(r['library'], []).append(r)
                for lib, rows in sorted(by_lib.items()):
                    fh.write('\n{}\n'.format(lib))
                    fh.write('  {}\n'.format(' or '.join(
                        'id:{}'.format(r['id']) for r in sorted(rows, key=lambda x: x['id']))))
                    for r in sorted(rows, key=lambda x: x['id']):
                        fh.write('    id:{}  {} -> {} ficheros  '
                                 '({} grupo(s) de fragmentos -> {} fusion(es), '
                                 'tope {} KB)  {}\n'.format(
                            r['id'], r.get('before', '?'), r.get('after', '?'),
                            r.get('groups', '?'), r.get('tramos', '?'),
                            r.get('max_merged_kb', '?'), (r.get('title') or '')[:60]))
                        if r.get('reasons'):
                            fh.write('        por que quedan separados: {}\n'.format(
                                _format_reasons(r['reasons'])))
            if problems:
                fh.write('\n--- NO TOCADOS ---\n')
                for r, why in problems:
                    fh.write('  id:{}  {}\n      {}\n'.format(
                        r['id'], (r.get('title') or '')[:60], why))
    except Exception as exc:
        print('  ! no pude escribir el informe: {}'.format(exc))
        return '(sin informe)'
    return path


def build_parser():
    p = argparse.ArgumentParser(
        prog='merge.cmd',
        description='Une los fragmentos "_split_NNN" que dejo una conversion de Calibre.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Sin --apply solo informa. Con --apply, Calibre debe estar CERRADO.')
    p.add_argument('--root', '-r', action='append', default=[], metavar='CARPETA',
                   help='Carpeta raiz bajo la que buscar bibliotecas.')
    p.add_argument('--library', '-l', action='append', default=[], metavar='RUTA',
                   help='Biblioteca concreta (repetible).')
    p.add_argument('--ids', metavar='1,2,3',
                   help='Limitar a estos ids (util para probar).')
    p.add_argument('--min-splits', type=int, default=DEFAULT_MIN_SPLITS, metavar='N',
                   help='Fragmentos minimos para considerar el libro '
                        '(por defecto {}, el mismo umbral del informe).'.format(
                            DEFAULT_MIN_SPLITS))
    p.add_argument('--max-merged-kb', type=int, default=DEFAULT_MAX_MERGED_KB, metavar='KB',
                   help='Tamano maximo de un fichero fusionado, en KB (por defecto '
                        '{}, el mismo "flow_size" que usa Calibre). Un grupo largo '
                        'se fusiona en varios tramos en vez de uno solo para no '
                        'superarlo.'.format(DEFAULT_MAX_MERGED_KB))
    p.add_argument('--apply', action='store_true',
                   help='Fusionar de verdad. Sin esto solo se informa.')
    p.add_argument('--dry-run', action='store_true',
                   help='Con --apply: fusiona y verifica, pero NO sustituye nada.')
    p.add_argument('--yes', action='store_true', help='No pedir confirmacion.')
    p.add_argument('--no-backup', action='store_true',
                   help='No respaldar metadata.db (la copia del EPUB se hace igual).')
    p.add_argument('--force-running', action='store_true',
                   help='Seguir aunque parezca que Calibre esta abierto.')
    p.add_argument('--backend', choices=('auto', 'calibre', 'sqlite'), default='auto')
    p.add_argument('--out-dir', metavar='CARPETA', default=None,
                   help='Donde dejar copias e informe (por defecto dedupe_out/).')
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    D.check_lxml()
    libraries = D.resolve_libraries(args.library, args.root)
    if not libraries:
        raise SystemExit('Indica que bibliotecas: --root "..." o --library "..."')
    print('Bibliotecas: {}'.format(len(libraries)))
    for lib in libraries:
        print('  - {}'.format(lib))
    return run(libraries, args)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('\nInterrumpido. Nada a medias: un libro solo se sustituye tras '
              'verificarse por completo.')
        sys.exit(130)
