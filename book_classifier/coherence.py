# -*- coding: utf-8 -*-
"""
Informe de COHERENCIA entre copias del mismo libro.

Modulo PURO: no toca la base de datos ni objetos Qt (los datos los lee
`action._prefetch_library_rows` en el hilo de la GUI, como el resto del
plugin). Agrupa por la MISMA clave de identidad que el indice de donantes
(`llm_jobs.book_key`) y saca a la luz lo que ni la clasificacion local ni el
rescate con IA revisan nunca: dos copias del mismo titulo y autor con
clasificaciones que se contradicen.

Por que hace falta: tanto el clasificador local como la IA deciden libro a
libro, a partir de la sinopsis de ESE registro. Dos copias del mismo libro con
sinopsis distintas (o una sin sinopsis) pueden acabar en librerias distintas o
con temas distintos sin que nada lo detecte. Ademas, desde 3.6.0 un libro ya
clasificado actua como DONANTE para sus copias, asi que un error se propaga:
este informe es la contrapartida.

Cuatro hallazgos, de mas a menos grave:

  1. CONTRADICCION DE LIBRERIA - dos copias con libreria distinta. Una esta
     mal por definicion; hay que decidir cual.
  2. CONTRADICCION DE TEMAS - conjuntos de temas incompatibles (ninguno
     contiene al otro): cada copia afirma algo que la otra niega.
  3. TEMAS INCOMPLETOS - los temas de unas copias son subconjunto de los de
     otras (incluida la copia que no tiene ninguno). No hay nada que decidir:
     la union es la respuesta, y se puede unificar sin criterio humano.
  4. CLASIFICADOS SIN TEMAS - libros con libreria pero sin ningun tema. No es
     una contradiccion entre copias, sino el hueco sistematico del plugin: los
     temas viajan de paquete con la libreria, asi que un libro que se resolvio
     cuando `llm_write_temas` estaba desactivado -o que resolvio el
     clasificador local por autor/serie- se queda sin ellos para siempre.
"""
from __future__ import unicode_literals, division, absolute_import, print_function

from calibre_plugins.book_classifier.llm_jobs import book_key


def _fmt_moods(moods):
    return ', '.join(sorted(moods)) if moods else '(ninguno)'


def _search(ids):
    """Busqueda de calibre que deja en pantalla justo ese grupo."""
    return ' or '.join('id:{}'.format(i) for i in sorted(ids))


def _group_entry(key, books):
    libs = {}
    for b in books:
        lib = (b.get('libreria') or '').strip()
        if lib:
            libs.setdefault(lib, []).append(b['id'])
    mood_sets = dict((b['id'], frozenset(b.get('temas') or [])) for b in books)
    return {
        'key': key,
        'title': books[0].get('title') or '',
        'authors': ', '.join(books[0].get('authors') or []),
        'idioma': books[0].get('idioma') or '',
        'n': len(books),
        'libs': libs,
        'books': books,
        'mood_sets': mood_sets,
        'union_moods': sorted(set().union(*mood_sets.values())) if mood_sets else [],
        'search': _search([b['id'] for b in books]),
    }


def _mood_status(entry):
    """'conflicto' si hay dos conjuntos incompatibles, 'incompleto' si unos
    son subconjunto de otros, '' si todas las copias coinciden."""
    sets = list(entry['mood_sets'].values())
    distintos = set(sets)
    if len(distintos) <= 1:
        return ''
    for a in distintos:
        for b in distintos:
            if a is not b and not (a <= b or b <= a):
                return 'conflicto'
    return 'incompleto'


def analyze(rows, sample_no_moods=60):
    """Analiza las filas de la biblioteca y devuelve el informe (dict)."""
    groups = {}
    for r in rows:
        k = book_key(r.get('title'), r.get('authors'), r.get('idioma'))
        groups.setdefault(k, []).append(r)

    rep = {
        'total_books': len(rows),
        'total_groups': 0,
        'lib_conflicts': [],
        'mood_conflicts': [],
        'mood_incomplete': [],
        'no_moods': [],
        'no_moods_total': 0,
    }
    for k, books in groups.items():
        if len(books) > 1:
            rep['total_groups'] += 1
            e = _group_entry(k, books)
            if len(e['libs']) > 1:
                rep['lib_conflicts'].append(e)
            st = _mood_status(e)
            if st == 'conflicto':
                rep['mood_conflicts'].append(e)
            elif st == 'incompleto':
                rep['mood_incomplete'].append(e)
        for b in books:
            if (b.get('libreria') or '').strip() and not (b.get('temas') or []):
                rep['no_moods_total'] += 1
                if len(rep['no_moods']) < sample_no_moods:
                    rep['no_moods'].append(b)

    for clave in ('lib_conflicts', 'mood_conflicts', 'mood_incomplete'):
        rep[clave].sort(key=lambda e: (-e['n'], e['title'].lower()))
    return rep


def unify_moods_writes(entry_list):
    """Escrituras para el caso INCOMPLETO: a cada copia del grupo, la union de
    los temas del grupo. Devuelve {id: [temas]} solo de los que cambian."""
    out = {}
    for e in entry_list:
        union = frozenset(e['union_moods'])
        if not union:
            continue
        for bid, ms in e['mood_sets'].items():
            if ms != union:
                out[bid] = sorted(union)
    return out


# ---------------------------------------------------------------------------
# Informe HTML
# ---------------------------------------------------------------------------

_CSS = """
body{font-family:Segoe UI,Helvetica,Arial,sans-serif;margin:24px;color:#222;
     background:#fafafa;font-size:14px}
h1{font-size:22px;margin:0 0 4px}
h2{font-size:17px;margin:28px 0 6px;border-bottom:2px solid #ddd;padding-bottom:4px}
p.sub{color:#666;margin:0 0 18px}
p.nota{color:#555;margin:4px 0 12px;max-width:60em}
table{border-collapse:collapse;width:100%;background:#fff;margin-bottom:10px}
th,td{border:1px solid #e0e0e0;padding:6px 8px;text-align:left;vertical-align:top}
th{background:#f0f0f0;font-weight:600}
tr.grupo td{background:#f6f8ff;font-weight:600}
code{background:#eee;padding:1px 4px;border-radius:3px;font-size:12px}
.vacio{color:#888;font-style:italic}
.res{display:inline-block;background:#fff;border:1px solid #ddd;border-radius:6px;
     padding:8px 12px;margin:0 8px 8px 0}
.res b{font-size:20px;display:block}
.bien{color:#1a7f37}
.mal{color:#c0392b}
"""


def _esc(t):
    return (str(t if t is not None else '')
            .replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


def _tabla_grupos(entries, mostrar_temas=True, limite=400):
    if not entries:
        return '<p class="vacio">Nada que revisar aqui.</p>'
    out = ['<table><tr><th>Libro</th><th>id</th><th>Libreria</th>'
           + ('<th>Temas</th>' if mostrar_temas else '') + '</tr>']
    for e in entries[:limite]:
        out.append(
            '<tr class="grupo"><td colspan="{}">{} &mdash; <i>{}</i>{}'
            '<br><code>{}</code></td></tr>'.format(
                4 if mostrar_temas else 3, _esc(e['title']), _esc(e['authors']),
                (' [{}]'.format(_esc(e['idioma'])) if e['idioma'] else ''),
                _esc(e['search'])))
        for b in e['books']:
            out.append('<tr><td>{}</td><td>{}</td><td>{}</td>{}</tr>'.format(
                _esc(b.get('title')), b['id'],
                _esc(b.get('libreria') or '(sin librería)'),
                ('<td>{}</td>'.format(_esc(_fmt_moods(b.get('temas'))))
                 if mostrar_temas else '')))
    out.append('</table>')
    if len(entries) > limite:
        out.append('<p class="vacio">... y {} grupos mas (no se listan).</p>'
                   .format(len(entries) - limite))
    return '\n'.join(out)


def render_html(rep, titulo='Coherencia entre copias', biblioteca=''):
    n_lib = len(rep['lib_conflicts'])
    n_mc = len(rep['mood_conflicts'])
    n_mi = len(rep['mood_incomplete'])
    h = ['<!DOCTYPE html><html><head><meta charset="utf-8">',
         '<title>{}</title><style>{}</style></head><body>'.format(_esc(titulo), _CSS),
         '<h1>{}</h1>'.format(_esc(titulo)),
         '<p class="sub">Book Classifier &mdash; {} libros analizados, {} '
         'titulos con mas de una copia{}</p>'.format(
             rep['total_books'], rep['total_groups'],
             ' &mdash; ' + _esc(biblioteca) if biblioteca else ''),
         '<div>',
         '<div class="res"><b class="{}">{}</b>contradicciones de libreria</div>'.format(
             'mal' if n_lib else 'bien', n_lib),
         '<div class="res"><b class="{}">{}</b>contradicciones de temas</div>'.format(
             'mal' if n_mc else 'bien', n_mc),
         '<div class="res"><b>{}</b>grupos con temas incompletos</div>'.format(n_mi),
         '<div class="res"><b>{}</b>clasificados sin ningun tema</div>'.format(
             rep['no_moods_total']),
         '</div>',
         '<h2>1. Contradicciones de libreria</h2>',
         '<p class="nota">Dos copias del mismo titulo y autor con libreria '
         'distinta: una de las dos esta mal, y desde 3.6.0 cualquiera de ellas '
         'puede actuar de donante para una tercera copia sin clasificar. '
         'Corrige la que sobre y vuelve a clasificar el grupo.</p>',
         _tabla_grupos(rep['lib_conflicts']),
         '<h2>2. Contradicciones de temas</h2>',
         '<p class="nota">Conjuntos de temas incompatibles: ninguno contiene al '
         'otro, asi que cada copia afirma algo que la otra no dice. Hay que '
         'decidir cual vale.</p>',
         _tabla_grupos(rep['mood_conflicts']),
         '<h2>3. Temas incompletos</h2>',
         '<p class="nota">Los temas de unas copias son un subconjunto de los de '
         'otras (incluida la copia que no tiene ninguno). No hay nada que '
         'decidir: la union es la respuesta. El informe se puede aplicar solo, '
         'desde el propio dialogo del plugin.</p>',
         _tabla_grupos(rep['mood_incomplete']),
         '<h2>4. Clasificados sin ningun tema</h2>',
         '<p class="nota">Libros con libreria pero sin temas. No es una '
         'contradiccion: es el hueco sistematico del plugin, porque los temas '
         'solo se escriben cuando se resuelve la libreria. Se arreglan con una '
         '"Reevaluacion con IA" de la seleccion.</p>']
    if rep['no_moods']:
        h.append('<table><tr><th>Libro</th><th>id</th><th>Libreria</th></tr>')
        for b in rep['no_moods']:
            h.append('<tr><td>{}</td><td>{}</td><td>{}</td></tr>'.format(
                _esc(b.get('title')), b['id'], _esc(b.get('libreria'))))
        h.append('</table>')
        h.append('<p><code>{}</code></p>'.format(
            _esc(_search([b['id'] for b in rep['no_moods']]))))
        if rep['no_moods_total'] > len(rep['no_moods']):
            h.append('<p class="vacio">... y {} mas (no se listan).</p>'.format(
                rep['no_moods_total'] - len(rep['no_moods'])))
    else:
        h.append('<p class="vacio">Ninguno: todos los clasificados tienen temas.</p>')
    h.append('</body></html>')
    return '\n'.join(h)
