# -*- coding: utf-8 -*-
"""Pruebas del informe de coherencia entre copias (fuera de Calibre)."""
import os, sys, types, importlib.util

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    os.pardir, 'book_classifier')

pkg = types.ModuleType('calibre_plugins'); pkg.__path__ = []
sub = types.ModuleType('calibre_plugins.book_classifier'); sub.__path__ = [BASE]
mlj = types.ModuleType('calibre_plugins.book_classifier.ml_jobs')
mlj._merge_prefixed = lambda n, p, f, o, w: list(n)
sys.modules.update({'calibre_plugins': pkg, 'calibre_plugins.book_classifier': sub,
                    'calibre_plugins.book_classifier.ml_jobs': mlj})

def load(name):
    spec = importlib.util.spec_from_file_location(
        'calibre_plugins.book_classifier.' + name, os.path.join(BASE, name + '.py'))
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m

load('llm_jobs')
C = load('coherence')

ok = [0]; bad = [0]
def check(name, cond):
    (ok if cond else bad)[0] += 1
    print(('  OK   ' if cond else '  FALLO') + '  ' + name)

def row(bid, title, aut, lib, temas, idioma='es'):
    return {'id': bid, 'title': title, 'authors': [aut], 'idioma': idioma,
            'libreria': lib, 'temas': list(temas), 'conf_pct': None, 'serie': None}

print('\n== contradiccion de libreria ==')
r = C.analyze([row(1, 'Elantris', 'Brandon Sanderson', 'Fantasia', ['Aventura']),
               row(2, 'Elantris', 'Sanderson, Brandon', 'Ciencia ficcion', ['Aventura'])])
check('detecta las dos librerias', len(r['lib_conflicts']) == 1)
check('agrupa pese a la forma del autor', r['lib_conflicts'][0]['n'] == 2)
check('da la busqueda de calibre', r['lib_conflicts'][0]['search'] == 'id:1 or id:2')
check('no lo cuenta como conflicto de temas', not r['mood_conflicts'])

print('\n== temas ==')
r = C.analyze([row(1, 'Dune', 'Frank Herbert', 'Ciencia ficcion', ['Espacio', 'Politica']),
               row(2, 'Dune', 'Frank Herbert', 'Ciencia ficcion', ['Espacio', 'Ecologia'])])
check('conjuntos incompatibles = contradiccion', len(r['mood_conflicts']) == 1)
check('y no incompletos', not r['mood_incomplete'])

r = C.analyze([row(1, 'Dune', 'Frank Herbert', 'Ciencia ficcion', ['Espacio', 'Politica']),
               row(2, 'Dune', 'Frank Herbert', 'Ciencia ficcion', ['Espacio'])])
check('subconjunto = incompleto', len(r['mood_incomplete']) == 1 and not r['mood_conflicts'])
w = C.unify_moods_writes(r['mood_incomplete'])
check('la union solo toca la copia pobre', w == {2: ['Espacio', 'Politica']})

r = C.analyze([row(1, 'Dune', 'Frank Herbert', 'Ciencia ficcion', ['Espacio']),
               row(2, 'Dune', 'Frank Herbert', 'Ciencia ficcion', [])])
check('copia sin temas = incompleto', len(r['mood_incomplete']) == 1)
check('la union la rellena', C.unify_moods_writes(r['mood_incomplete']) == {2: ['Espacio']})

r = C.analyze([row(1, 'Dune', 'Frank Herbert', 'Ciencia ficcion', ['Espacio']),
               row(2, 'Dune', 'Frank Herbert', 'Ciencia ficcion', ['Espacio'])])
check('copias identicas no salen en el informe',
      not r['lib_conflicts'] and not r['mood_conflicts'] and not r['mood_incomplete'])
check('pero si se cuenta el grupo', r['total_groups'] == 1)

print('\n== distintos libros no se mezclan ==')
r = C.analyze([row(1, 'Dune 2', 'Frank Herbert', 'Ciencia ficcion', ['Espacio']),
               row(2, 'Dune 3', 'Frank Herbert', 'Ensayo', ['Politica']),
               row(3, 'Dune', 'Frank Herbert', 'Ensayo', ['Politica'], idioma='en'),
               row(4, 'Dune', 'Frank Herbert', 'Ciencia ficcion', ['Espacio'])])
check('titulos y/o idiomas distintos: sin conflictos',
      not r['lib_conflicts'] and r['total_groups'] == 0)

print('\n== clasificados sin temas ==')
r = C.analyze([row(1, 'A', 'X', 'Fantasia', []),
               row(2, 'B', 'Y', 'Fantasia', ['Aventura']),
               row(3, 'C', 'Z', '', [])])
check('cuenta solo los que tienen libreria y no temas', r['no_moods_total'] == 1)

print('\n== html ==')
h = C.render_html(C.analyze([row(1, '<script>x', 'A & B', 'Fantasia', ['T']),
                             row(2, '<script>x', 'A & B', 'Ensayo', ['T'])]))
check('genera html', h.startswith('<!DOCTYPE html>') and h.rstrip().endswith('</html>'))
check('escapa el html del titulo', '<script>' not in h and '&lt;script&gt;' in h)
check('incluye la busqueda', 'id:1 or id:2' in h)

print('\n%d OK, %d fallos' % (ok[0], bad[0]))
sys.exit(1 if bad[0] else 0)
