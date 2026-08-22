#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
convert_column.py -- cambia el TIPO de una columna personalizada de Calibre
CONSERVANDO los valores.

Caso tipico: '#subtitle' se creo como "Long text, like comments" y se quiere
como "Text, column shown in the Tag browser", para que el dialogo de revision
de Fix Metadata muestre una caja de texto normal y no un editor enorme.

Calibre NO permite cambiar el tipo de una columna existente (ni desde la
interfaz ni desde la API), asi que este script hace la unica secuencia posible:

    1. EXPORTA los valores actuales a un JSON (id, uuid, titulo, autores, valor).
    2. RESPALDA metadata.db.
    3. BORRA la columna.
    4. La RECREA con el tipo pedido, conservando el nombre visible.
    5. REESCRIBE los valores, convirtiendo el HTML de comments a texto plano.
    6. VERIFICA releyendo la biblioteca y comparando valor a valor.

Si algo sale mal despues del paso 3, el JSON del paso 1 permite reintentar la
reimportacion sola con --restore, y metadata.db.bak-* deja la biblioteca como
estaba.

Requiere el interprete de Calibre (necesita su API):

    calibre-debug -e convert_column.py -- --list
    calibre-debug -e convert_column.py -- --column subtitle --dry-run
    calibre-debug -e convert_column.py -- --column subtitle
    calibre-debug -e convert_column.py -- -l "Mi Biblioteca" --column subtitle

La biblioteca se puede dar por NOMBRE (el que muestra Calibre en "Cambiar
biblioteca") o por ruta; --list-libraries dice cuales conoce.

En Windows usa el lanzador 'convertir_columna.cmd', que ya lo localiza.

CALIBRE DEBE ESTAR CERRADO: el script ESCRIBE en la biblioteca.
"""

from __future__ import unicode_literals, division, absolute_import, print_function

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

try:
    from html import unescape as _unescape
except ImportError:                                    # Python 2
    from HTMLParser import HTMLParser
    _unescape = HTMLParser().unescape


VERSION = '1.4.0'

# Tipos que este script sabe crear.  Son los unicos con sentido para un valor
# corto de una sola linea (text) o un texto largo con formato (comments).
TIPOS = ('text', 'comments')


# ---------------------------------------------------------------------------
#  Entorno
# ---------------------------------------------------------------------------

def running_inside_calibre():
    try:
        import calibre  # noqa: F401
        return True
    except Exception:
        return False


def procesos_calibre():
    """
    Mejor esfuerzo: cuenta procesos de Calibre por tipo.

    Devuelve {'gui': n, 'workers': n}.  La distincion importa: solo la interfaz
    ('calibre.exe') tiene la biblioteca abierta y puede pisar el cambio.  Los
    'calibre worker process' ('calibre-parallel.exe') son trabajadores sueltos
    que Calibre deja atras al cerrarse o al terminar una conversion; no tocan
    metadata.db, asi que bloquear por ellos impedia trabajar sin motivo.
    No se cuenta 'calibre-debug', que es el interprete que ejecuta este script.
    """
    out = {'gui': 0, 'workers': 0}
    try:
        if sys.platform == 'win32':
            proc = subprocess.run(['tasklist', '/FO', 'CSV', '/NH'],
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            texto = (proc.stdout or b'').decode('utf-8', 'replace').lower()
            nombres = [l.split('","')[0].lstrip('"') for l in texto.splitlines() if l]
        else:
            proc = subprocess.run(['ps', '-eo', 'comm='], stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL)
            texto = (proc.stdout or b'').decode('utf-8', 'replace').lower()
            nombres = [l.strip().rsplit('/', 1)[-1] for l in texto.splitlines() if l.strip()]
        for n in nombres:
            base = n[:-4] if n.endswith('.exe') else n
            if base == 'calibre':
                out['gui'] += 1
            elif base in ('calibre-parallel', 'calibre-server'):
                out['workers'] += 1
    except Exception:
        pass
    return out


def aviso_calibre_abierto(force):
    """True si hay que abortar.  Informa de los workers sueltos sin bloquear."""
    procs = procesos_calibre()
    if procs['workers']:
        print('AVISO: hay {} "calibre worker process" (calibre-parallel.exe) '
              'sueltos.'.format(procs['workers']))
        print('       No tienen la biblioteca abierta y no estorban; suelen ser '
              'restos de')
        print('       una sesion anterior. Si te molestan, cierralos desde el '
              'Administrador de tareas.')
    if not procs['gui']:
        return False
    print('Parece que la INTERFAZ de Calibre esta abierta (calibre.exe) y este '
          'cambio ESCRIBE')
    print('en la biblioteca. Cierrala y repite el comando (o usa --force-running).')
    return not force


def calibre_current_library():
    """La biblioteca que Calibre tiene/tuvo abierta, o None."""
    try:
        from calibre.utils.config import prefs
        if prefs['library_path']:
            return os.path.abspath(prefs['library_path'])
    except Exception:
        pass
    return None


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


def limpiar_ruta(texto):
    """
    Quita los espacios y comillas sobrantes de una ruta escrita a mano.

    En PowerShell es facil teclear --root " C:\\Libros\\..." con un espacio
    dentro de las comillas; sin limpiarlo la ruta deja de ser absoluta y acaba
    resolviendose contra la carpeta actual, con un error desconcertante.
    """
    r = (texto or '').strip().strip('"').strip("'").strip()
    # Una barra final tampoco estorba, salvo en la raiz de una unidad ("C:\\")
    while len(r) > 3 and r[-1] in '\\/':
        r = r[:-1]
    return r


def es_biblioteca(path):
    return bool(path) and os.path.exists(os.path.join(path, 'metadata.db'))


def nombre_biblioteca(path):
    """El nombre que Calibre muestra: el de la ultima carpeta de la ruta."""
    return os.path.basename(os.path.abspath(path).rstrip(os.sep))


def bibliotecas_conocidas():
    """
    Las bibliotecas que Calibre recuerda, de mas a menos usada.

    Salen de 'library_usage_stats' en gui.json (lo que llena el menu "Cambiar
    biblioteca"), mas la que esta abierta ahora.  Es lo que permite escribir
    --library "Mi Biblioteca" en vez de la ruta entera.
    """
    paths = []
    try:
        with open(os.path.join(_calibre_config_dir(), 'gui.json'),
                  'r', encoding='utf-8') as fh:
            stats = (json.load(fh) or {}).get('library_usage_stats') or {}
        paths = [p for p, _n in sorted(stats.items(), key=lambda kv: -kv[1])]
    except Exception:
        paths = []
    actual = calibre_current_library()
    if actual:
        paths.append(actual)
    vistas, out = set(), []
    for p in paths:
        p = os.path.abspath(os.path.expanduser(p))
        clave = os.path.normcase(p)
        if clave in vistas or not es_biblioteca(p):
            continue
        vistas.add(clave)
        out.append(p)
    return out


def descubrir_bibliotecas(roots, max_depth=6):
    """Busca carpetas con metadata.db bajo cada raiz, sin entrar en las ya halladas."""
    out, vistas = [], set()
    for root in roots:
        crudo = limpiar_ruta(root)
        root = os.path.abspath(os.path.expanduser(crudo))
        if not os.path.isdir(root):
            print('No es una carpeta: {}'.format(root))
            if not os.path.isabs(crudo):
                print('  Ojo a las comillas: un espacio delante de la ruta la '
                      'convierte en relativa.')
            continue
        base_depth = root.rstrip(os.sep).count(os.sep)
        for dirpath, dirnames, _files in os.walk(root):
            if dirpath.rstrip(os.sep).count(os.sep) - base_depth >= max_depth:
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames if not d.startswith('.')]
            if es_biblioteca(dirpath):
                clave = os.path.normcase(os.path.abspath(dirpath))
                if clave not in vistas:
                    vistas.add(clave)
                    out.append(os.path.abspath(dirpath))
                dirnames[:] = []
    return out


def resolver_biblioteca(texto, candidatas):
    """
    Acepta una RUTA o un NOMBRE de biblioteca.

    Con nombre se busca entre las bibliotecas conocidas: primero coincidencia
    exacta (sin distinguir mayusculas), luego 'empieza por' y luego 'contiene'.
    Si hay mas de una candidata se aborta en vez de elegir por ti.
    Devuelve (ruta, error).
    """
    texto = limpiar_ruta(texto)
    bruto = os.path.expanduser(texto)
    if es_biblioteca(bruto):
        return os.path.abspath(bruto), None
    if os.path.isdir(bruto):
        return None, ('la carpeta existe pero no es una biblioteca de Calibre '
                      '(falta metadata.db): {}'.format(os.path.abspath(bruto)))
    if os.sep in texto or (os.altsep and os.altsep in texto):
        return None, 'no existe la carpeta: {}'.format(texto)

    objetivo = texto.strip().lower()
    for prueba in (lambda n: n == objetivo,
                   lambda n: n.startswith(objetivo),
                   lambda n: objetivo in n):
        hits = [p for p in candidatas if prueba(nombre_biblioteca(p).lower())]
        if len(hits) == 1:
            return hits[0], None
        if len(hits) > 1:
            return None, ('"{}" coincide con varias bibliotecas:\n    {}'.format(
                texto, '\n    '.join(hits)))
    if not candidatas:
        return None, ('no hay ninguna biblioteca conocida; pasa la ruta completa '
                      'o usa --root "D:\\Bibliotecas"')
    return None, ('no encuentro ninguna biblioteca llamada "{}".\n'
                  '  Conocidas: {}'.format(
                      texto, ', '.join(nombre_biblioteca(p) for p in candidatas)))


def open_library(path):
    """Abre la biblioteca y devuelve (db_legacy, new_api)."""
    from calibre.library import db as calibre_db
    legacy = calibre_db(path)
    return legacy, getattr(legacy, 'new_api', legacy)


def close_library(legacy):
    for obj in (getattr(legacy, 'new_api', None), legacy):
        if obj is None:
            continue
        try:
            obj.close()
            return
        except Exception:
            continue


def backup_metadata_db(library_path):
    """Copia metadata.db (y WAL/SHM) antes de tocar nada.  Devuelve la ruta."""
    src = os.path.join(library_path, 'metadata.db')
    if not os.path.exists(src):
        return None
    dst = os.path.join(library_path,
                       'metadata.db.bak-{}'.format(time.strftime('%Y%m%d_%H%M%S')))
    try:
        shutil.copy2(src, dst)
    except Exception as exc:
        print('AVISO: no se pudo respaldar {}: {}'.format(src, exc))
        return None
    for suffix in ('-wal', '-shm'):
        if os.path.exists(src + suffix):
            try:
                shutil.copy2(src + suffix, dst + suffix)
            except Exception:
                pass
    return dst


# ---------------------------------------------------------------------------
#  HTML -> texto plano
# ---------------------------------------------------------------------------

_RE_DROP = re.compile(r'(?is)<(script|style)[^>]*>.*?</\1\s*>')
_RE_BR = re.compile(r'(?i)<\s*br\s*/?\s*>')
_RE_BLOCK = re.compile(r'(?i)</\s*(p|div|li|tr|h[1-6]|blockquote|pre)\s*>')
_RE_TAG = re.compile(r'<[^>]+>')
_RE_WS = re.compile(r'[ \t\r\f\v\u00a0]+')


def html_a_texto(valor, sep=' '):
    """
    Pasa el HTML que guarda una columna 'comments' a texto plano de UNA linea.

    No trunca: si el valor era un parrafo entero, sale entero.  Los saltos de
    linea y los finales de parrafo se sustituyen por 'sep' porque una columna
    'text' es de una sola linea; con sep=' ' el resultado se lee como una frase.
    """
    if valor is None:
        return ''
    s = valor if isinstance(valor, str) else str(valor)
    s = _RE_DROP.sub(' ', s)
    s = _RE_BR.sub('\n', s)
    s = _RE_BLOCK.sub('\n', s)
    s = _RE_TAG.sub('', s)
    s = _unescape(s)
    s = _RE_WS.sub(' ', s)
    # Colapsa los saltos (y los espacios que los rodean) en el separador
    partes = [p.strip() for p in s.split('\n')]
    partes = [p for p in partes if p]
    s = sep.join(partes)
    return _RE_WS.sub(' ', s).strip()


def texto_a_html(valor):
    """Texto plano -> el HTML minimo que espera una columna 'comments'."""
    if not valor:
        return ''
    esc = (valor.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))
    return '<div><p>{}</p></div>'.format(esc)


# ---------------------------------------------------------------------------
#  Columnas personalizadas
# ---------------------------------------------------------------------------

def columnas_personalizadas(new_api):
    """{'#subtitle': {'label','name','datatype','is_multiple','display'}, ...}"""
    fm = new_api.field_metadata
    out = {}
    for key in fm.custom_field_keys():
        meta = fm[key]
        out[key] = {
            'label': meta.get('label'),
            'name': meta.get('name'),
            'datatype': meta.get('datatype'),
            'is_multiple': meta.get('is_multiple'),
            'display': dict(meta.get('display') or {}),
        }
    return out


def _metodo(new_api, nombre):
    """Busca 'nombre' en el new_api y, si no, en su backend (segun version)."""
    fn = getattr(new_api, nombre, None)
    if fn is not None:
        return fn
    backend = getattr(new_api, 'backend', None)
    return getattr(backend, nombre, None) if backend is not None else None


def borrar_columna(new_api, label):
    fn = _metodo(new_api, 'delete_custom_column')
    if fn is None:
        raise RuntimeError('Esta version de Calibre no expone delete_custom_column')
    fn(label=label)


def crear_columna(new_api, label, name, datatype, display=None):
    fn = _metodo(new_api, 'create_custom_column')
    if fn is None:
        raise RuntimeError('Esta version de Calibre no expone create_custom_column')
    try:
        fn(label, name, datatype, False, display=display or {})
    except TypeError:
        fn(label, name, datatype, False)


def leer_valores(new_api, key, book_ids):
    """{book_id: valor bruto} solo con los libros que tienen valor."""
    valores = {}
    try:
        crudos = new_api.all_field_for(key, book_ids)
    except Exception:
        crudos = {bid: new_api.field_for(key, bid) for bid in book_ids}
    for bid, v in crudos.items():
        if v is None:
            continue
        if isinstance(v, (list, tuple)):
            v = ', '.join(str(x) for x in v)
        if str(v).strip():
            valores[bid] = v
    return valores


# ---------------------------------------------------------------------------
#  Fases
# ---------------------------------------------------------------------------

def exportar(new_api, key, sep):
    """Lee la columna y devuelve la lista de registros lista para el JSON."""
    book_ids = list(new_api.all_book_ids())
    crudos = leer_valores(new_api, key, book_ids)
    registros = []
    for bid in sorted(crudos):
        bruto = crudos[bid]
        try:
            titulo = new_api.field_for('title', bid) or ''
            autores = list(new_api.field_for('authors', bid) or ())
            uuid = new_api.field_for('uuid', bid) or ''
        except Exception:
            titulo, autores, uuid = '', [], ''
        registros.append({
            'id': bid,
            'uuid': uuid,
            'title': titulo,
            'authors': autores,
            'raw': bruto if isinstance(bruto, str) else str(bruto),
            'text': html_a_texto(bruto, sep=sep),
        })
    return registros


def elegir_grafia(registros):
    """
    Una columna 'text' guarda cada valor UNA sola vez y sin distinguir
    mayusculas (su tabla es UNIQUE ... COLLATE NOCASE, igual que las
    etiquetas), y los libros APUNTAN a esa fila.  Asi que 'A Novel', 'A novel'
    y 'a Novel' no son tres valores: son una unica fila a la que enlazan todos
    esos libros, y esa fila lleva un solo texto.

    Como solo cabe una grafia, aqui se decide cual: la del PRIMER libro que la
    tenia (los registros vienen ordenados por id), que es estable y facil de
    predecir.  Sin esto ganaba la primera que se escribiese, que dependia del
    orden de recorrido.

    Devuelve (elegida_por_clave_en_minusculas, conflictos).
    """
    elegidos, variantes = {}, {}
    for reg in registros:
        texto = reg.get('text') or ''
        if not texto:
            continue
        clave = texto.lower()
        elegidos.setdefault(clave, texto)
        cuenta = variantes.setdefault(clave, {})
        cuenta[texto] = cuenta.get(texto, 0) + 1
    conflictos = [(elegidos[c], dict(v)) for c, v in variantes.items() if len(v) > 1]
    return elegidos, conflictos


def forzar_mayusculas(new_api, key, elegidos):
    """
    Renombra los valores ya guardados para que tengan la grafia elegida.

    Hace falta porque set_field() no cambia la grafia de un valor que ya existe:
    lo reutiliza tal cual estaba.  rename_items() si toca la fila.
    """
    try:
        id_map = new_api.get_id_map(key)
    except Exception:
        return 0
    cambios = {}
    for item_id, nombre in (id_map or {}).items():
        quiere = elegidos.get((nombre or '').lower())
        if quiere and quiere != nombre:
            cambios[item_id] = quiere
    if not cambios:
        return 0
    try:
        new_api.rename_items(key, cambios)
    except Exception as exc:
        print('     AVISO: no se pudo unificar la grafia: {}'.format(exc))
        return 0
    return len(cambios)


def escribir_valores(new_api, key, registros, datatype, avisar=True):
    """Reescribe los valores en la columna ya recreada.  Devuelve (escritos, perdidos)."""
    ids_validos = set(new_api.all_book_ids())
    elegidos, conflictos = ({}, [])
    if datatype == 'text':
        elegidos, conflictos = elegir_grafia(registros)
        if conflictos and avisar:
            print('     {} valores que solo se diferencian en mayusculas se '
                  'unifican'.format(len(conflictos)))
            print('     (una columna de texto no distingue mayusculas, como las '
                  'etiquetas).')
            print('     Se conserva la grafia del primer libro que la tenia:')
            for mejor, variantes in sorted(conflictos)[:10]:
                detalle = ', '.join('{} x{}'.format(v, n)
                                    for v, n in sorted(variantes.items(),
                                                       key=lambda kv: -kv[1]))
                print('       {}  <-  {}'.format(mejor, detalle))
            if len(conflictos) > 10:
                print('       ... y {} mas'.format(len(conflictos) - 10))
    cambios, perdidos = {}, []
    for reg in registros:
        bid = reg['id']
        if bid not in ids_validos:
            perdidos.append(reg)
            continue
        valor = reg['text']
        if not valor:
            continue
        if datatype == 'text':
            valor = elegidos.get(valor.lower(), valor)
            reg['text'] = valor
        cambios[bid] = texto_a_html(valor) if datatype == 'comments' else valor
    if cambios:
        new_api.set_field(key, cambios)
    if datatype == 'text' and elegidos:
        n = forzar_mayusculas(new_api, key, elegidos)
        if n and avisar:
            print('     Grafia unificada en {} valores'.format(n))
    return cambios, perdidos


def verificar(library_path, key, registros, datatype, sep):
    """Reabre la biblioteca y compara lo escrito con lo exportado."""
    legacy, new_api = open_library(library_path)
    try:
        cols = columnas_personalizadas(new_api)
        info = cols.get(key)
        if info is None:
            return False, ['la columna {} no existe tras la conversion'.format(key)]
        problemas, solo_mayusculas = [], []
        if info['datatype'] != datatype:
            problemas.append('el tipo es {} y se pidio {}'.format(
                info['datatype'], datatype))
        actuales = leer_valores(new_api, key, list(new_api.all_book_ids()))
        for reg in registros:
            esperado = reg['text']
            if not esperado:
                continue
            leido = actuales.get(reg['id'])
            leido = html_a_texto(leido, sep=sep) if datatype == 'comments' \
                else ('' if leido is None else str(leido))
            if leido == esperado:
                continue
            if (leido or '').lower() == esperado.lower():
                # Una columna 'text' no distingue mayusculas: no es una perdida
                # de datos, solo la grafia unificada.  Se informa, no se falla.
                solo_mayusculas.append((reg['id'], esperado, leido))
                continue
            problemas.append('id {}: se esperaba {!r} y hay {!r}'.format(
                reg['id'], esperado[:60], (leido or '')[:60]))
            if len(problemas) > 20:
                problemas.append('... (mas diferencias omitidas)')
                break
        if solo_mayusculas:
            print('     {} valores quedaron con otra grafia (la columna de texto '
                  'no distingue'.format(len(solo_mayusculas)))
            print('     mayusculas y unifica los valores iguales). Ejemplos:')
            for bid, esp, leido in solo_mayusculas[:5]:
                print('       id {}: {!r} -> {!r}'.format(bid, esp, leido))
        return (not problemas), problemas
    finally:
        close_library(legacy)


# ---------------------------------------------------------------------------
#  Informe
# ---------------------------------------------------------------------------

def resumen_export(registros, muestra=8):
    print('  Libros con valor: {}'.format(len(registros)))
    if not registros:
        return
    largos = [r for r in registros if len(r['text']) > 200]
    vacios = [r for r in registros if not r['text'].strip()]
    if largos:
        print('  Valores de mas de 200 caracteres: {} (se conservan enteros)'
              .format(len(largos)))
        r = max(largos, key=lambda x: len(x['text']))
        print('    el mas largo, id {}: {} caracteres'.format(r['id'], len(r['text'])))
    if vacios:
        print('  Valores que quedan vacios al quitar el HTML: {} (no se escriben)'
              .format(len(vacios)))
    print('  Muestra:')
    for r in registros[:muestra]:
        txt = r['text']
        if len(txt) > 90:
            txt = txt[:87] + '...'
        print('    id {:>6}  {}'.format(r['id'], txt))


def listar(new_api):
    cols = columnas_personalizadas(new_api)
    if not cols:
        print('Esta biblioteca no tiene columnas personalizadas.')
        return
    print('{:<20} {:<12} {:<8} {}'.format('LOOKUP', 'TIPO', 'MULTI', 'NOMBRE'))
    for key in sorted(cols):
        c = cols[key]
        print('{:<20} {:<12} {:<8} {}'.format(
            key, c['datatype'] or '?', 'si' if c['is_multiple'] else 'no',
            c['name'] or ''))


# ---------------------------------------------------------------------------
#  main
# ---------------------------------------------------------------------------

def parse_args(argv):
    p = argparse.ArgumentParser(
        prog='convert_column.py',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description='Cambia el tipo de una columna personalizada de Calibre '
                    'conservando los valores.',
        epilog='Ejemplos:\n'
               '  --list-libraries\n'
               '  --library "Mi Biblioteca" --list\n'
               '  --column subtitle --dry-run\n'
               '  --column subtitle\n'
               '  --column subtitle --to comments        (vuelta atras)\n'
               '  --restore columnas_out/subtitle_20260810_120000.json\n')
    p.add_argument('--library', '-l', action='append', default=[],
                   help='NOMBRE o ruta de la biblioteca (por defecto, la ultima que '
                        'abrio Calibre). El nombre es el que muestra Calibre en '
                        '"Cambiar biblioteca". Se puede repetir.')
    p.add_argument('--root', action='append', default=[],
                   help='Carpeta bajo la que buscar bibliotecas, para poder darles '
                        'nombre aunque Calibre no las recuerde. Se puede repetir.')
    p.add_argument('--all-libraries', action='store_true',
                   help='Aplicarlo a TODAS las bibliotecas conocidas (o a las que '
                        'haya bajo --root)')
    p.add_argument('--list-libraries', action='store_true',
                   help='Listar las bibliotecas que conozco, con su nombre y ruta')
    p.add_argument('--column', '-c', help="Lookup name, con o sin '#': subtitle")
    p.add_argument('--to', default='text', choices=TIPOS,
                   help="Tipo destino (por defecto text)")
    p.add_argument('--name', help='Nombre visible de la columna nueva '
                                  '(por defecto, el que ya tenia)')
    p.add_argument('--sep', default=' ',
                   help="Con que se unen los saltos de linea al pasar a texto "
                        "(por defecto un espacio)")
    p.add_argument('--out-dir', help='Donde dejar el JSON exportado '
                                     '(por defecto columnas_out/ junto al script)')
    p.add_argument('--list', action='store_true',
                   help='Solo listar las columnas personalizadas y salir')
    p.add_argument('--dry-run', action='store_true',
                   help='Exporta y muestra que haria, sin tocar la biblioteca')
    p.add_argument('--restore', metavar='JSON',
                   help='Solo reimportar un JSON ya exportado (la columna debe '
                        'existir ya con el tipo destino)')
    p.add_argument('--force-running', action='store_true',
                   help='No abortar aunque parezca que Calibre esta abierto')
    p.add_argument('--version', action='version', version=VERSION)
    return p.parse_args(argv)


def resolver_bibliotecas(args):
    """Convierte lo que pidio el usuario en rutas de biblioteca.  [] si falla."""
    candidatas = bibliotecas_conocidas()
    halladas = descubrir_bibliotecas(args.root) if args.root else []
    for p in halladas:
        if os.path.normcase(p) not in {os.path.normcase(c) for c in candidatas}:
            candidatas.append(p)

    if args.all_libraries:
        if not candidatas:
            print('No conozco ninguna biblioteca. Usa --root o pasa la ruta.')
        return candidatas

    if not args.library:
        if args.root:
            if len(halladas) == 1:
                return halladas
            if len(halladas) > 1:
                print('Bajo --root hay {} bibliotecas. Elige una con -l "Nombre" '
                      'o usa --all-libraries:'.format(len(halladas)))
                for p in halladas:
                    print('  {:<28}  {}'.format(nombre_biblioteca(p), p))
                return []
            print('No hay ninguna biblioteca de Calibre bajo --root.')
            return []
        actual = calibre_current_library()
        if es_biblioteca(actual):
            return [actual]
        print('No se que biblioteca usar. Pasa --library "Nombre" o la ruta.')
        if candidatas:
            print('Conocidas: {}'.format(
                ', '.join(nombre_biblioteca(p) for p in candidatas)))
        return []

    validas, fallo = [], False
    for texto in args.library:
        ruta, error = resolver_biblioteca(texto, candidatas)
        if error:
            print('ERROR: {}'.format(error))
            fallo = True
            continue
        if os.path.normcase(ruta) not in {os.path.normcase(v) for v in validas}:
            validas.append(ruta)
    return [] if fallo else validas


def listar_bibliotecas(args):
    candidatas = bibliotecas_conocidas()
    for p in descubrir_bibliotecas(args.root) if args.root else []:
        if os.path.normcase(p) not in {os.path.normcase(c) for c in candidatas}:
            candidatas.append(p)
    if not candidatas:
        print('No conozco ninguna biblioteca. Prueba con --root "D:\\Bibliotecas".')
        return 1
    actual = calibre_current_library()
    ancho = max(len(nombre_biblioteca(p)) for p in candidatas)
    for p in candidatas:
        marca = ' <- abierta ahora' if actual and \
            os.path.normcase(p) == os.path.normcase(actual) else ''
        print('  {:<{w}}  {}{}'.format(nombre_biblioteca(p), p, marca, w=ancho))
    return 0


def out_dir_por_defecto(args):
    if args.out_dir:
        d = os.path.abspath(os.path.expanduser(args.out_dir))
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        d = os.path.join(base, 'columnas_out')
    if not os.path.isdir(d):
        os.makedirs(d)
    return d


def procesar(library_path, args):
    """Convierte la columna en UNA biblioteca.  Devuelve True si todo fue bien."""
    key = '#' + args.column.lstrip('#')
    label = key[1:]
    destino = args.to

    print('')
    print('=' * 72)
    print('Biblioteca: {}  ({})'.format(nombre_biblioteca(library_path),
                                          library_path))
    print('=' * 72)

    legacy, new_api = open_library(library_path)
    try:
        cols = columnas_personalizadas(new_api)
        info = cols.get(key)
        if info is None:
            print('ERROR: no existe la columna {} en esta biblioteca.'.format(key))
            print('       Columnas disponibles: {}'.format(
                ', '.join(sorted(cols)) or '(ninguna)'))
            return False
        origen = info['datatype']
        nombre = args.name or info['name'] or label
        print('Columna {}  "{}"'.format(key, nombre))
        print('  tipo actual : {}'.format(origen))
        print('  tipo destino: {}'.format(destino))
        if origen == destino:
            print('Ya es del tipo pedido: no hay nada que hacer.')
            return True
        if info['is_multiple']:
            print('ERROR: {} es una columna de valores multiples; este script solo '
                  'convierte columnas de un solo valor.'.format(key))
            return False

        print('')
        print('1/6  Exportando los valores actuales...')
        registros = exportar(new_api, key, args.sep)
        resumen_export(registros)
    finally:
        close_library(legacy)

    destino_dir = out_dir_por_defecto(args)
    marca = time.strftime('%Y%m%d_%H%M%S')
    json_path = os.path.join(destino_dir, '{}_{}.json'.format(label, marca))
    payload = {
        'version': VERSION,
        'library': library_path,
        'column': key,
        'name': nombre,
        'from': origen,
        'to': destino,
        'sep': args.sep,
        'exported_at': marca,
        'records': registros,
    }
    with open(json_path, 'w', encoding='utf-8') as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    print('     Copia de seguridad de los valores: {}'.format(json_path))

    if args.dry_run:
        print('')
        print('--dry-run: no se ha tocado la biblioteca.')
        print('Repite el comando sin --dry-run para hacer el cambio.')
        return True

    print('2/6  Respaldando metadata.db...')
    bak = backup_metadata_db(library_path)
    print('     {}'.format(bak or 'AVISO: sin respaldo'))

    print('3/6  Borrando la columna {}...'.format(key))
    legacy, new_api = open_library(library_path)
    try:
        borrar_columna(new_api, label)
    finally:
        close_library(legacy)

    print('4/6  Creando {} como "{}"...'.format(key, destino))
    legacy, new_api = open_library(library_path)
    try:
        crear_columna(new_api, label, nombre, destino)
    finally:
        close_library(legacy)

    print('5/6  Reescribiendo {} valores...'.format(len(registros)))
    legacy, new_api = open_library(library_path)
    try:
        escritos, perdidos = escribir_valores(new_api, key, registros, destino)
    finally:
        close_library(legacy)
    print('     Escritos: {}'.format(len(escritos)))
    if perdidos:
        print('     AVISO: {} libros del export ya no existen en la biblioteca'
              .format(len(perdidos)))

    print('6/6  Verificando...')
    ok, problemas = verificar(library_path, key, registros, destino, args.sep)
    if ok:
        print('     CORRECTO: la columna es "{}" y todos los valores coinciden.'
              .format(destino))
    else:
        print('     PROBLEMAS:')
        for p in problemas:
            print('       - {}'.format(p))
        print('     El JSON con los valores originales sigue en:')
        print('       {}'.format(json_path))
        print('     Y metadata.db sin tocar en: {}'.format(bak))
    return ok


def restaurar(args):
    with open(args.restore, 'r', encoding='utf-8') as fh:
        payload = json.load(fh)
    library_path = payload['library']
    key = payload['column']
    destino = payload['to']
    registros = payload['records']
    sep = payload.get('sep', ' ')
    print('Reimportando {} valores de {} en {}'.format(
        len(registros), key, library_path))

    legacy, new_api = open_library(library_path)
    try:
        cols = columnas_personalizadas(new_api)
        if key not in cols:
            print('ERROR: la columna {} no existe. Creala primero (o repite la '
                  'conversion completa).'.format(key))
            return False
        if cols[key]['datatype'] != destino:
            print('AVISO: la columna es "{}" y el JSON esperaba "{}".'.format(
                cols[key]['datatype'], destino))
        backup_metadata_db(library_path)
        escritos, perdidos = escribir_valores(new_api, key, registros, destino)
    finally:
        close_library(legacy)
    print('Escritos: {}{}'.format(
        len(escritos),
        '  (perdidos {})'.format(len(perdidos)) if perdidos else ''))
    ok, problemas = verificar(library_path, key, registros, destino, sep)
    print('Verificacion: {}'.format('CORRECTO' if ok else 'CON PROBLEMAS'))
    for p in problemas:
        print('  - {}'.format(p))
    return ok


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])

    if not running_inside_calibre():
        print('Este script necesita la API de Calibre.  Ejecutalo asi:')
        print('  calibre-debug -e "{}" -- --list'.format(os.path.abspath(__file__)))
        print('(en Windows, usa convertir_columna.cmd)')
        return 2

    if args.restore:
        if aviso_calibre_abierto(args.force_running):
            return 1
        return 0 if restaurar(args) else 1

    if args.list_libraries:
        return listar_bibliotecas(args)

    libs = resolver_bibliotecas(args)
    if not libs:
        return 1

    if args.list:
        for lib in libs:
            print('')
            print('Biblioteca: {}  ({})'.format(nombre_biblioteca(lib), lib))
            legacy, new_api = open_library(lib)
            try:
                listar(new_api)
            finally:
                close_library(legacy)
        return 0

    if not args.column:
        print('Falta --column.  Usa --list para ver las columnas disponibles.')
        return 1

    if not args.dry_run and aviso_calibre_abierto(args.force_running):
        return 1

    todo_ok = True
    for lib in libs:
        try:
            if not procesar(lib, args):
                todo_ok = False
        except Exception as exc:
            todo_ok = False
            print('ERROR en {}: {}'.format(lib, exc))
            import traceback
            traceback.print_exc()
    return 0 if todo_ok else 1


if __name__ == '__main__':
    sys.exit(main())
