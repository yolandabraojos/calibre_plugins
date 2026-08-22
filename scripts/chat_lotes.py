#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
chat_lotes.py -- Clasificar por el CHAT WEB en vez de por la API
================================================================

Ciclo de ida y vuelta para usar los creditos de una IA de web:

    1) exportar  -> genera lote_NNN.csv (los libros) y lote_NNN.txt (las
                    instrucciones, con las MISMAS reglas que usa el plugin).
    2) tu        -> adjuntas el .csv en el chat, pegas el .txt como mensaje y
                    guardas la respuesta como respuesta_NNN.csv.
    3) importar  -> valida lo que devolvio el modelo contra el catalogo de
                    librerias y el vocabulario de temas, deja un fichero de
                    revision y, con --aplicar, lo escribe en Calibre.

Las reglas, el catalogo y los normalizadores se IMPORTAN de
book_classifier/llm_rescue_engine.py: este script no tiene una copia propia
del prompt, asi que no puede quedarse desfasado (que es justo lo que paso con
scripts/llm_rescue.py cuando cambiaron las estanterias).

El CSV de entrada es un catalogo CSV de Calibre. **Incluye la columna `id`**
al generarlo (Catalogo -> CSV -> elige los campos): sin ella hay que casar por
titulo+autor y los libros con el mismo titulo quedan sin resolver.

Uso tipico:

    python3 scripts/chat_lotes.py exportar --in biblioteca.csv --lote 40
    ... pegas cada lote en el chat ...
    python3 scripts/chat_lotes.py importar --in chat_out/ --revision revision.csv
    calibre-debug -e scripts/chat_lotes.py -- importar --in chat_out/ --aplicar

Solo libreria estandar salvo para --aplicar, que necesita el interprete de
Calibre (va por calibre-debug, como convertir_columna.cmd).
"""
from __future__ import unicode_literals, division, absolute_import, print_function

import argparse
import csv
import io
import json
import os
import re
import sys
import unicodedata

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)


# ---------------------------------------------------------------------------
#  Motor del plugin: unica fuente de verdad del prompt y del catalogo
# ---------------------------------------------------------------------------
def cargar_motor():
    import importlib.util
    ruta = os.path.join(RAIZ, 'book_classifier', 'llm_rescue_engine.py')
    if not os.path.exists(ruta):
        sys.exit('No encuentro el motor del plugin en:\n  %s' % ruta)
    spec = importlib.util.spec_from_file_location('llm_rescue_engine', ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def cargar_temas():
    """{nombre: descripcion} del vocabulario actual."""
    ruta = os.path.join(RAIZ, 'book_classifier', 'mood_rules.json')
    try:
        with open(ruta, encoding='utf-8') as fh:
            crudo = json.load(fh)
    except Exception:
        return {}
    return {n: ((r.get('desc') or '') if isinstance(r, dict) else '')
            for n, r in crudo.items()}


ENG = cargar_motor()
TEMAS = cargar_temas()

CAMPOS_SALIDA = ['ref', 'libreria', 'confianza', 'temas', 'serie', 'motivo']


# ---------------------------------------------------------------------------
#  Utilidades
# ---------------------------------------------------------------------------
def leer_csv(path):
    """Lee un CSV tolerando bytes nulos (corrupcion de sincronizacion en la
    nube al exportar). Devuelve (fieldnames, filas)."""
    with open(path, 'rb') as fb:
        raw = fb.read()
    if b'\x00' in raw:
        print('AVISO: %s tenia bytes nulos (exportacion truncada); se ignoran.'
              % os.path.basename(path))
        raw = raw.replace(b'\x00', b'')
    r = csv.DictReader(io.StringIO(raw.decode('utf-8-sig', 'replace')))
    return (r.fieldnames or []), list(r)


def clave(v):
    s = unicodedata.normalize('NFKD', str(v or ''))
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r'[^\w\s]', ' ', s, flags=re.UNICODE)
    return ' '.join(s.lower().split())


def es_residuo(v):
    v = str(v or '').strip()
    return (not v) or ('[REVISAR]' in v) or v.endswith('(sin datos)') \
        or clave(v) == clave(ENG.REVISAR)


def limpiar_sinopsis(txt, tope=1200):
    txt = re.sub(r'<[^>]+>', ' ', txt or '')
    return re.sub(r'\s+', ' ', txt).strip()[:tope]


def limpiar_tags(crudo, tope=25):
    """Mismo criterio que el plugin: fuera los tags que codifican la propia
    clase y el ruido de estanteria de Goodreads."""
    tags = [t.strip() for t in str(crudo or '').split(',') if t.strip()]
    fuera = ('Biblioteca: ', 'Tema: ', 'Biblioteca IA: ', 'Tema IA: ',
             'Genero · ', 'Genero.', 'Biblioteca.', 'Libreria.')
    ruido = {'to read', 'tbr', 'owned', 'kindle', 'ebook', 'audiobook',
             'favorites', 'favoritos', 'dnf', 'leidos', 'leido', 'por leer',
             'currently reading', 'read', 'wishlist', 'pendiente'}
    out = []
    for t in tags:
        if any(t.startswith(p) for p in fuera):
            continue
        k = clave(t).replace('-', ' ')
        if k in ruido or re.match(r'^\d{1,4}$', k) or re.match(r'^\d ?(stars?|estrellas?)$', k):
            continue
        if '·' in t:
            t = t.split('·', 1)[1].strip()
        out.append(t)
    return out[:tope]


# ---------------------------------------------------------------------------
#  exportar
# ---------------------------------------------------------------------------
def instrucciones(n_libros, pedir_serie):
    """Las reglas del plugin + como devolver el resultado en CSV.

    Se reutiliza `build_system_prompt`, que es literalmente el mensaje
    `system` que el plugin manda al modelo: reglas, mapa de subgeneros y
    vocabulario de temas EXACTAMENTE los mismos.
    """
    reglas = ENG.build_system_prompt(TEMAS, None, pedir_serie).rstrip()
    col_serie = ',serie' if pedir_serie else ''
    return (
        "Te adjunto un CSV con %d libros (columnas: ref, titulo, autor, "
        "sinopsis, tags).\n"
        "Clasifica CADA UNO siguiendo las reglas de abajo.\n\n"
        "%s\n\n"
        "FORMATO DE RESPUESTA (esto es lo importante):\n"
        "  - Devuelve SOLO un CSV, sin texto antes ni despues, dentro de un "
        "bloque de codigo.\n"
        "  - Cabecera exacta: ref,libreria,confianza,temas%s,motivo\n"
        "  - UNA fila por libro del adjunto, en el mismo orden, con su 'ref' "
        "tal cual.\n"
        "  - 'confianza': numero de 0 a 100.\n"
        "  - 'temas': los que apliques separados por punto y coma (;), "
        "copiados TAL CUAL de la lista; vacio si ninguno.\n"
        "  - 'motivo': una linea breve.\n"
        "  - Si un campo lleva comas, entrecomillalo.\n"
        "  - NO resumas ni agrupes: quiero las %d filas.\n"
        % (n_libros, reglas, col_serie, n_libros))


def exportar(args):
    campos, filas = leer_csv(args.inp)
    col_lib = args.col_libreria
    tiene_id = 'id' in campos
    if not tiene_id:
        print('AVISO: el CSV no trae columna "id"; se usara titulo+autor para '
              'volver a casar los libros y los titulos repetidos quedaran sin '
              'resolver. Vuelve a exportar el catalogo incluyendo "id".')

    candidatos, vistos, saltados = [], set(), 0
    for f in filas:
        if not args.todos and col_lib in campos and not es_residuo(f.get(col_lib)):
            saltados += 1
            continue
        titulo = (f.get('title') or '').strip()
        autor = (f.get('authors') or '').strip()
        k = (clave(titulo), clave(autor))
        if k in vistos:          # copias del mismo libro: una sola pregunta
            continue
        vistos.add(k)
        ref = (f.get('id') or '').strip() if tiene_id else ('%s|%s' % k)
        candidatos.append({
            'ref': ref, 'titulo': titulo, 'autor': autor or '(desconocido)',
            'sinopsis': limpiar_sinopsis(f.get('comments'), args.sinopsis),
            'tags': ', '.join(limpiar_tags(f.get('tags'))),
        })
    if args.limite:
        candidatos = candidatos[:args.limite]
    if not candidatos:
        sys.exit('No hay libros que preguntar (todos tienen libreria firme). '
                 'Usa --todos para exportarlos igualmente.')

    os.makedirs(args.out, exist_ok=True)
    n = args.lote
    total = len(candidatos)
    nlotes = (total + n - 1) // n
    for i in range(nlotes):
        parte = candidatos[i * n:(i + 1) * n]
        base = os.path.join(args.out, 'lote_%03d' % (i + 1))
        with open(base + '.csv', 'w', encoding='utf-8-sig', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=['ref', 'titulo', 'autor',
                                               'sinopsis', 'tags'])
            w.writeheader()
            w.writerows(parte)
        with open(base + '.txt', 'w', encoding='utf-8') as fh:
            fh.write(instrucciones(len(parte), args.serie))
    print('Libros sin clasificar encontrados: %d  (con libreria firme: %d)'
          % (total, saltados))
    print('Lotes escritos en %s: %d de hasta %d libros' % (args.out, nlotes, n))
    print()
    print('Ahora, por cada lote:')
    print('  1. adjunta lote_001.csv en el chat')
    print('  2. pega lote_001.txt como mensaje')
    print('  3. guarda la respuesta como %s' % os.path.join(args.out, 'respuesta_001.csv'))
    print('y cuando tengas varias, pasa a: chat_lotes.py importar --in %s' % args.out)


# ---------------------------------------------------------------------------
#  importar
# ---------------------------------------------------------------------------
_BLOQUE = re.compile(r'```[a-z]*\s*\n(.*?)```', re.DOTALL | re.IGNORECASE)
_CERCA = re.compile(r'^```[a-z]*\s*|\s*```$', re.IGNORECASE | re.MULTILINE)


def leer_respuesta(path):
    """Lee la respuesta del chat: CSV a secas, CSV dentro de un bloque de
    codigo, o incluso un array JSON (algunos modelos lo devuelven asi por
    costumbre). Devuelve lista de dicts."""
    with open(path, 'rb') as fb:
        txt = fb.read().replace(b'\x00', b'').decode('utf-8-sig', 'replace')
    # Si el modelo puso el CSV en un bloque de codigo, se coge SOLO eso: asi
    # la cortesia de antes y de despues ("Aqui tienes...", "Espero que te
    # sirva") no se cuela como una fila mas.
    bloque = _BLOQUE.search(txt)
    limpio = (bloque.group(1) if bloque else _CERCA.sub('', txt)).strip()
    if limpio.lstrip().startswith('['):
        try:
            return [{'ref': str(o.get('ref') or o.get('n') or ''),
                     'libreria': o.get('libreria') or '',
                     'confianza': o.get('confianza') or '',
                     'temas': ';'.join(o.get('temas') or []),
                     'serie': o.get('serie') or '',
                     'motivo': o.get('motivo') or ''}
                    for o in ENG.parse_array(limpio)]
        except Exception as exc:
            print('  (parecia JSON pero no se pudo leer: %s)' % exc)
    # buscar la cabecera del CSV aunque el modelo haya escrito algo antes
    lineas = limpio.splitlines()
    inicio = 0
    for i, l in enumerate(lineas):
        if l.lower().replace(' ', '').startswith('ref,libreria'):
            inicio = i
            break
    return list(csv.DictReader(io.StringIO('\n'.join(lineas[inicio:]))))


def importar(args):
    entradas = []
    if os.path.isdir(args.inp):
        for nombre in sorted(os.listdir(args.inp)):
            if nombre.lower().startswith('respuesta') and \
                    nombre.lower().endswith(('.csv', '.txt', '.json')):
                entradas.append(os.path.join(args.inp, nombre))
    else:
        entradas = [args.inp]
    if not entradas:
        sys.exit('No encuentro ficheros respuesta_*.csv en %s' % args.inp)

    filas, diag = [], {'leidas': 0, 'sin_ref': 0, 'libreria_mala': 0,
                       'temas_descartados': 0, 'duplicadas': 0, 'declarado': 0}
    nombres_malos, vistos = {}, set()
    for path in entradas:
        crudas = leer_respuesta(path)
        print('%-28s %d filas' % (os.path.basename(path), len(crudas)))
        for c in crudas:
            diag['leidas'] += 1
            ref = str(c.get('ref') or '').strip()
            if not ref:
                diag['sin_ref'] += 1
                continue
            if ref in vistos:
                diag['duplicadas'] += 1
                continue
            vistos.add(ref)
            bruto = str(c.get('libreria') or '').strip()
            lib = ENG.norm_libreria(bruto)
            if lib == ENG.REVISAR and bruto:
                # Que la IA diga '(revisar)' es una respuesta legitima; que
                # devuelva un nombre que no existe es otra cosa y pide accion.
                if clave(bruto) == clave(ENG.REVISAR):
                    diag['declarado'] += 1
                else:
                    diag['libreria_mala'] += 1
                    nombres_malos[bruto[:40]] = nombres_malos.get(bruto[:40], 0) + 1
            crudos_temas = [t.strip() for t in
                            re.split(r'[;|]', str(c.get('temas') or '')) if t.strip()]
            temas = ENG.norm_temas(crudos_temas, TEMAS)
            diag['temas_descartados'] += max(0, len(crudos_temas) - len(temas))
            try:
                conf = int(round(float(str(c.get('confianza') or '0').replace('%', ''))))
            except (TypeError, ValueError):
                conf = 0
            filas.append({'ref': ref, 'libreria': lib,
                          'libreria_bruta': bruto, 'confianza': conf,
                          'temas': '; '.join(temas),
                          'serie': str(c.get('serie') or '').strip(),
                          'motivo': str(c.get('motivo') or '').strip()[:300]})

    print('\nFilas leidas: %d   utiles: %d' % (diag['leidas'], len(filas)))
    if diag['sin_ref']:
        print('  sin ref (descartadas): %d' % diag['sin_ref'])
    if diag['duplicadas']:
        print('  refs repetidas (se queda la primera): %d' % diag['duplicadas'])
    if diag['declarado']:
        print('  la IA dice que no tiene base ((revisar)): %d' % diag['declarado'])
    if diag['libreria_mala']:
        print('  libreria fuera del catalogo: %d  -> %s' % (
            diag['libreria_mala'],
            ', '.join('"%s" x%d' % (n, v) for n, v in
                      sorted(nombres_malos.items(), key=lambda kv: -kv[1])[:6])))
    if diag['temas_descartados']:
        print('  temas fuera del vocabulario (descartados): %d'
              % diag['temas_descartados'])
    resueltas = [f for f in filas if f['libreria'] != ENG.REVISAR]
    print('  con libreria valida: %d' % len(resueltas))

    if args.revision:
        with open(args.revision, 'w', encoding='utf-8-sig', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=['ref', 'libreria', 'libreria_bruta',
                                               'confianza', 'temas', 'serie', 'motivo'])
            w.writeheader()
            w.writerows(filas)
        print('\nRevision escrita en %s (abrelo, corrige lo que quieras y '
              'vuelve a pasar --aplicar sobre ese mismo fichero).' % args.revision)

    if args.aplicar:
        aplicar(filas, args)


def aplicar(filas, args):
    """Escribe en Calibre. Necesita el interprete de Calibre (calibre-debug)."""
    try:
        from calibre.library import db as calibre_db
    except ImportError:
        sys.exit('--aplicar necesita el interprete de Calibre:\n'
                 '  calibre-debug -e scripts/chat_lotes.py -- importar '
                 '--in <carpeta> --aplicar')
    sys.path.insert(0, AQUI)
    from convert_column import (aviso_calibre_abierto, backup_metadata_db,
                                bibliotecas_conocidas, resolver_biblioteca)
    if aviso_calibre_abierto(args.force_running):
        sys.exit(1)
    ruta = resolver_biblioteca(args.library, bibliotecas_conocidas()) \
        if args.library else (bibliotecas_conocidas() or [None])[0]
    if not ruta:
        sys.exit('No se que biblioteca usar: pasa --library "Nombre o ruta".')
    print('\nBiblioteca: %s' % ruta)
    copia = backup_metadata_db(ruta)
    if copia:
        print('Respaldo: %s' % os.path.basename(copia))
    legacy = calibre_db(ruta)
    api = getattr(legacy, 'new_api', legacy)
    ids_validos = set(api.all_book_ids())
    escrituras = {args.col_libreria_ia: {}, args.col_temas_ia: {},
                  args.col_conf: {}, args.col_motivo: {}}
    sin_id = 0
    for f in filas:
        try:
            bid = int(f['ref'])
        except (TypeError, ValueError):
            sin_id += 1
            continue
        if bid not in ids_validos or f['libreria'] == ENG.REVISAR:
            sin_id += 1
            continue
        escrituras[args.col_libreria_ia][bid] = f['libreria']
        if f['temas']:
            escrituras[args.col_temas_ia][bid] = [t.strip() for t in
                                                  f['temas'].split(';') if t.strip()]
        escrituras[args.col_conf][bid] = f['confianza']
        if f['motivo']:
            escrituras[args.col_motivo][bid] = f['motivo']
    for campo, mapa in escrituras.items():
        if not campo or not mapa:
            continue
        try:
            api.set_field(campo, mapa)
            print('  %-22s %d libros' % (campo, len(mapa)))
        except Exception as exc:
            print('  %-22s ERROR: %s' % (campo, exc))
    if sin_id:
        print('  sin aplicar (ref no numerica, libro inexistente o sin '
              'libreria valida): %d' % sin_id)
    try:
        api.close()
    except Exception:
        pass
    print('\nHecho. Pasa ahora la clasificacion local del plugin para que '
          'promocione lo que supere el umbral de confianza.')


# ---------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd')

    e = sub.add_parser('exportar', help='genera los lotes para el chat')
    e.add_argument('--in', dest='inp', required=True, help='catalogo CSV de Calibre')
    e.add_argument('--out', default=os.path.join(RAIZ, 'chat_out'))
    e.add_argument('--lote', type=int, default=40, help='libros por lote (default 40)')
    e.add_argument('--limite', type=int, default=0, help='corta tras N libros')
    e.add_argument('--sinopsis', type=int, default=1200, help='caracteres de sinopsis')
    e.add_argument('--col-libreria', default='#libreria')
    e.add_argument('--todos', action='store_true',
                   help='exporta todos, no solo los que estan sin clasificar')
    e.add_argument('--serie', action='store_true', help='pedir tambien la saga')

    i = sub.add_parser('importar', help='valida las respuestas del chat')
    i.add_argument('--in', dest='inp', required=True,
                   help='carpeta con respuesta_*.csv, o un fichero suelto')
    i.add_argument('--revision', default=None, help='CSV de revision a escribir')
    i.add_argument('--aplicar', action='store_true', help='escribe en Calibre')
    i.add_argument('--library', default=None)
    i.add_argument('--force-running', action='store_true')
    i.add_argument('--col-libreria-ia', default='#libreria_ia')
    i.add_argument('--col-temas-ia', default='#clasificacion_ia')
    i.add_argument('--col-conf', default='#confianza_ia')
    i.add_argument('--col-motivo', default='#motivo_ia')

    args = ap.parse_args(argv)
    if args.cmd == 'exportar':
        exportar(args)
    elif args.cmd == 'importar':
        importar(args)
    else:
        ap.print_help()
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
