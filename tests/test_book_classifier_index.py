# -*- coding: utf-8 -*-
"""Pruebas del indice de donantes y del filtro de ya-rescatados (fuera de Calibre)."""
import os, sys, types, importlib.util

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    os.pardir, 'book_classifier')

pkg = types.ModuleType('calibre_plugins'); pkg.__path__ = []
sub = types.ModuleType('calibre_plugins.book_classifier'); sub.__path__ = [BASE]
mlj = types.ModuleType('calibre_plugins.book_classifier.ml_jobs')
def _merge_prefixed(newvals, prev, field, own_prefixes, overwrite):
    if field == 'tags':
        keep = [] if overwrite else [t for t in (prev or [])
                                     if not any(str(t).startswith(p) for p in own_prefixes if p)]
        return keep + list(newvals)
    return newvals[0] if newvals else None
mlj._merge_prefixed = _merge_prefixed
sys.modules.update({'calibre_plugins': pkg, 'calibre_plugins.book_classifier': sub,
                    'calibre_plugins.book_classifier.ml_jobs': mlj})
spec = importlib.util.spec_from_file_location(
    'calibre_plugins.book_classifier.llm_jobs', os.path.join(BASE, 'llm_jobs.py'))
L = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = L
spec.loader.exec_module(L)

ok = [0]; bad = [0]
def check(name, cond):
    (ok if cond else bad)[0] += 1
    print(('  OK   ' if cond else '  FALLO') + '  ' + name)

S = {'library_field': 'tags', 'mood_field': 'tags',
     'library_prefix': 'Biblioteca: ', 'mood_prefix': 'Tema: ',
     'llm_library_field': '#libreria_ia', 'llm_library_prefix': 'Biblioteca IA: ',
     'llm_conf_field': '#confianza_ia', 'llm_serie_field': '#serie_ia',
     'llm_reason_field': '#motivo_ia', 'overwrite': True,
     'llm_write_temas': True, 'llm_write_reason': True,
     'llm_write_serie': True, 'llm_write_conf': True}

print('\n== clave de identidad ==')
k = L.book_key
check("'Sanderson, Brandon' == 'Brandon Sanderson'",
      k('Elantris', ['Sanderson, Brandon']) == k('Elantris', ['Brandon Sanderson']))
check("acentos/mayusculas/puntuacion no importan",
      k('El Heroe de las Eras', ['B. Sanderson']) == k('el heroe de las eras!', ['B Sanderson']))
check("segundo autor no cambia la clave",
      k('X', ['A Uno', 'B Dos']) == k('X', ['A Uno', 'C Tres']))
check("'Dune 2' != 'Dune 3' (estricta)", k('Dune 2', ['F Herbert']) != k('Dune 3', ['F Herbert']))
check("'Dune 2' != 'Dune 3' (laxa)",
      k('Dune 2', ['F Herbert'], loose=True) != k('Dune 3', ['F Herbert'], loose=True))
check("sufijo de saga solo cae en la laxa",
      k('Nacidos de la bruma (Mistborn, 1)', ['B S'], loose=True) == k('Nacidos de la bruma', ['B S'], loose=True)
      and k('Nacidos de la bruma (Mistborn, 1)', ['B S']) != k('Nacidos de la bruma', ['B S']))
check("idioma distingue", k('X', ['A'], 'es') != k('X', ['A'], 'en'))
check("titulo que es solo subtitulo no queda vacio", L._norm_title(': prologo', loose=True) != '')

print('\n== punto 2: no reenviar lo ya rescatado ==')
def book(bid, title, lib_value, ia=None, aut=('Autor Uno',)):
    return {'id': bid, 'title': title, 'authors': list(aut), 'comments': 'sinopsis larga',
            'tags': [], 'idioma': 'es', 'lib_value': lib_value,
            'prev': {'tags': [], '#libreria_ia': ia}}
books = [book(1, 'Uno', 'Biblioteca: [REVISAR]'),
         book(2, 'Dos', 'Biblioteca: [REVISAR]', ia='Fantasia'),
         book(3, 'Tres', 'Biblioteca: [REVISAR]', ia='[REVISAR]')]
cand, diag = L.select_rescue_candidates(books, S)
check('el ya rescatado no es candidato', sorted(c[0]['id'] for c in cand) == [1, 3])
check('se contabiliza en diag', diag['already_llm'] == 1)
cand_f, _ = L.select_rescue_candidates(books, dict(S, force_all=True))
check('con force_all vuelve a entrar', len(cand_f) == 3)

print('\n== punto 3: indice de donantes ==')
rows = [{'id': 10, 'title': 'Elantris', 'authors': ['Sanderson, Brandon'], 'idioma': 'es',
         'libreria': 'Fantasia', 'temas': ['Aventura'], 'conf_pct': 93, 'serie': 'Elantris'},
        {'id': 11, 'title': 'Dune', 'authors': ['Frank Herbert'], 'idioma': 'es',
         'libreria': '[REVISAR]', 'temas': [], 'conf_pct': None, 'serie': None}]
idx = L.build_donor_index(rows)
check('el residuo no entra como donante', len(idx['strict']) == 1)

c = [({'id': 1, 'title': 'Elantris', 'authors': ['Brandon Sanderson'], 'idioma': 'es',
       'prev': {'tags': []}}, {})]
pend, res = L.resolve_from_index(c, idx, S)
check('resuelto sin llamar al LLM', not pend and res['from_index'] == 1)
check('escribe la libreria en el campo de la IA',
      res['writes_by_field'].get('#libreria_ia', {}).get(1) == 'Fantasia')
check('copia los temas (clave estricta)', res['writes_by_field'].get('tags', {}).get(1) == ['Tema: Aventura'])
check('copia la confianza', res['conf_writes'].get(1) == 93)
check('copia la serie', res['serie_writes'].get(1) == 'Elantris')
check('deja rastro en el motivo', 'id 10' in (res['reason_writes'].get(1) or ''))

print('\n== clave laxa: solo si hay unanimidad ==')
rows2 = [{'id': 20, 'title': 'Star Wars: Una nueva esperanza', 'authors': ['George Lucas'],
          'idioma': 'es', 'libreria': 'Ciencia ficcion', 'temas': ['Espacio'], 'conf_pct': 90},
         {'id': 21, 'title': 'Star Wars: El imperio contraataca', 'authors': ['George Lucas'],
          'idioma': 'es', 'libreria': 'Ciencia ficcion', 'temas': ['Guerra'], 'conf_pct': 90}]
i2 = L.build_donor_index(rows2)
c2 = [({'id': 22, 'title': 'Star Wars: El retorno del jedi', 'authors': ['George Lucas'],
        'idioma': 'es', 'prev': {'tags': []}}, {})]
p2, r2 = L.resolve_from_index(c2, i2, S)
check('saga unanime: responde la libreria', r2['from_index'] == 1 and r2['from_index_loose'] == 1)
check('la laxa NO copia temas', 'tags' not in r2['writes_by_field'])

rows3 = list(rows2); rows3[1] = dict(rows2[1], libreria='Ensayo')
i3 = L.build_donor_index(rows3)
p3, r3 = L.resolve_from_index(c2, i3, S)
check('si discrepan, la clave laxa no responde', r3['from_index'] == 0 and len(p3) == 1)

print('\n== dedup + indice conviven ==')
c4 = [({'id': 30, 'title': 'Elantris', 'authors': ['Brandon Sanderson'], 'idioma': 'es',
        'prev': {'tags': []}, 'dup_group': [{'id': 30, 'title': 'Elantris', 'prev': {'tags': []}},
                                            {'id': 31, 'title': 'Elantris', 'prev': {'tags': []}}]}, {})]
p4, r4 = L.resolve_from_index(c4, idx, S)
check('el resultado se aplica a las 2 copias del grupo',
      set(r4['writes_by_field']['#libreria_ia']) == {30, 31} and r4['from_index'] == 2)

d5, _ = L.resolve_from_index([({'id': 10, 'title': 'Elantris',
                                'authors': ['Brandon Sanderson'], 'idioma': 'es',
                                'prev': {'tags': []}}, {})], idx, S)
check('un libro no se dona a si mismo', len(d5) == 1)

print('\n== reparto en jobs: 1 job = 1 llamada, sin restos sueltos (3.14.0) ==')

def tam(n, **s):
    s.setdefault('llm_batch', 20)
    return [len(c['cand']) for c in
            L.plan_rescue_chunks([({'id': i}, {}) for i in range(n)], s)]

check('45 con lote 20 -> 2 llamadas de 23 y 22 (antes 20+20+5)', tam(45) == [23, 22])
check('21 caben en UNA llamada, no 20+1', tam(21) == [21])
check('46 -> 23+23, no 20+20+6', tam(46) == [23, 23])
check('nunca se pasa del techo (lote x 1.25 = 25)',
      all(max(tam(n)) <= 25 for n in (25, 26, 61, 100, 205)))
check('reparto uniforme: no hay grupos desiguales',
      all(max(tam(n)) - min(tam(n)) <= 1 for n in (26, 41, 86, 101, 205)))
check('no se pierde ni se duplica ningun candidato',
      all(sum(tam(n)) == n for n in (1, 25, 46, 101, 205)))
check('sin candidatos, sin jobs', L.plan_rescue_chunks([], {'llm_batch': 20}) == [])
check('los tramos de la etiqueta son consecutivos',
      [c['label'] for c in
       L.plan_rescue_chunks([({'id': i}, {}) for i in range(46)], {'llm_batch': 20})]
      == ['lote 1-23', 'lote 24-46'])
check('tolerancia 0 -> techo duro, reparto uniforme igualmente',
      tam(46, llm_batch_tolerancia=0) == [16, 15, 15])
check('tolerancia con basura no rompe', tam(46, llm_batch_tolerancia='x') == [23, 23])
check('lote 1 -> un job por libro', tam(45, llm_batch=1) == [1] * 45)
check('lote invalido (0) no divide por cero', tam(46, llm_batch=0) == [23, 23])

print('\n== prefijo VACIO = columna propia, no "tags sin marca" (3.12.0) ==')
libro = {'id': 77, 'title': 'X', 'authors': ['A'], 'comments': 'Sinopsis.',
         'idioma': 'es', 'lib_value': '[REVISAR]', 'prev': {},
         'tags': ['vampiros', 'romance oscuro', 'Leido 2024',
                  'Tema: Vampiros', 'Biblioteca: Paranormal']}
c, _ = L.select_rescue_candidates([dict(libro)],
                                  {'library_field': 'tags', 'mood_field': 'tags',
                                   'force_all': True})
check('con los dos ejes en tags, se quitan los del plugin (y "Leido 2024",'
      ' que es estanteria de lectura, desde 3.13.0)',
      c[0][1]['tags'] == 'vampiros, romance oscuro')
c, _ = L.select_rescue_candidates([dict(libro)],
                                  {'library_field': 'tags', 'mood_field': '#tema',
                                   'force_all': True})
check('con los temas en columna propia, el LLM SIGUE viendo los tags',
      'vampiros' in c[0][1]['tags'] and 'romance oscuro' in c[0][1]['tags'])
check('y la libreria del plugin se sigue quitando',
      'Biblioteca: Paranormal' not in c[0][1]['tags'])
c, _ = L.select_rescue_candidates([dict(libro)],
                                  {'library_field': '#libreria', 'mood_field': '#tema',
                                   'force_all': True})
check('con los dos en columna propia, los tags de verdad siguen llegando',
      c[0][1]['tags'] == 'vampiros, romance oscuro')
check('pero los valores del propio plugin no, esten donde esten configurados',
      'Tema: ' not in c[0][1]['tags'] and 'Biblioteca: ' not in c[0][1]['tags'])

check('ya-rescatado en columna propia MULTIVALOR se reconoce',
      L._llm_already_value({'prev': {'#libreria_ia': ('Paranormal',)}},
                           '#libreria_ia', '') == 'Paranormal')
check('en columna de texto simple, igual que antes',
      L._llm_already_value({'prev': {'#libreria_ia': 'Paranormal'}},
                           '#libreria_ia', '') == 'Paranormal')
check('en tags SIN prefijo sigue siendo indistinguible -> None',
      L._llm_already_value({'prev': {'tags': ['Paranormal']}}, 'tags', '') is None)
bk = {'id': 2, 'title': 'Y', 'authors': ['A'], 'idioma': 'es', 'comments': '',
      'tags': [], 'lib_value': '[REVISAR]', 'prev': {'#libreria_ia': ('Paranormal',)}}
c2, d2 = L.select_rescue_candidates([bk], {'library_field': 'tags',
                                           'mood_field': '#tema',
                                           'llm_library_field': '#libreria_ia',
                                           'force_all': False})
check('y por tanto ese libro ya no se reenvia al LLM',
      not c2 and d2['already_llm'] == 1)

print('\n== tags que se mandan al LLM: sin ruido y con tope (3.13.0) ==')
QUITAR = ['Biblioteca: ', 'Tema: ', 'Biblioteca IA: ', 'Tema IA: ']
for ruido in ['to-read', 'TBR', 'currently reading', 'owned', 'kindle',
              'audiobook', 'favorites', 'favoritos', 'dnf', 'leidos',
              'por leer', '2019', 'read-2020', '5 stars', 'netgalley', '42']:
    check('ruido de estanteria fuera: %r' % ruido, L._is_noise_tag(ruido))
for senal in ['paranormal romance', 'urban fantasy', 'vampires', 'romance',
              'novela historica', 'fiction', 'enemies-to-lovers']:
    check('senal conservada: %r' % senal, not L._is_noise_tag(senal))

t = L.tags_para_prompt(
    ['to-read', 'paranormal-romance', 'Tema: Vampiros', 'Biblioteca: Paranormal',
     'Genero · Paranormal', 'Subgenero · Fantasia urbana', 'witches'], QUITAR)
check('quita el ruido, el eco del plugin y la fuga de genero',
      t == ['paranormal-romance', 'Subgenero · Fantasia urbana', 'witches'])
check('un Tema: de una config ANTERIOR tambien se quita',
      'Tema: Vampiros' not in t)

muchas = ['relleno-%02d' % i for i in range(30)] + ['paranormal romance',
                                                    'urban fantasy']
sel = L.tags_para_prompt(muchas, QUITAR, max_tags=5)
check('se respeta el tope', len(sel) == 5)
check('y sobreviven las mas informativas',
      'paranormal romance' in sel and 'urban fantasy' in sel)
check('sin tope, no se recorta nada',
      len(L.tags_para_prompt(muchas, QUITAR, max_tags=0)) == 32)
check('lista vacia -> vacia', L.tags_para_prompt([], QUITAR) == [])
check('un prefijo vacio NO filtra nada',
      L.tags_para_prompt(['romance'], ['']) == ['romance'])

print('\n%d OK, %d fallos' % (ok[0], bad[0]))
sys.exit(1 if bad[0] else 0)
