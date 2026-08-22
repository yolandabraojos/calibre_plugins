# -*- coding: utf-8 -*-
"""Vocabulario de temas: descripciones para el LLM y reconocimiento tolerante.

Dos cosas nuevas en 3.10.0:
  * `mood_rules.json` admite {"regex": ..., "desc": ...}; la descripcion viaja
    al prompt porque el LLM solo ve los NOMBRES del vocabulario.
  * `norm_temas` ya no descarta en silencio un tema bien elegido por venir con
    tildes u otra puntuacion.
"""
import os, sys, json, importlib.util

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir,
                    'book_classifier')


def _load(name, fname):
    spec = importlib.util.spec_from_file_location(name, os.path.join(BASE, fname))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


E = _load('llm_rescue_engine_vocab', 'llm_rescue_engine.py')
M = _load('ml_classifier_vocab', 'ml_classifier.py')
MOOD = json.load(open(os.path.join(BASE, 'mood_rules.json'), encoding='utf-8'))

ok = [0]; bad = [0]


def check(name, cond):
    (ok if cond else bad)[0] += 1
    print(('  OK   ' if cond else '  FALLO') + '  ' + name)


print('\n== mood_rules.json: formato y contenido ==')
check('todas las entradas son objetos {regex, desc}',
      all(isinstance(v, dict) and 'regex' in v and 'desc' in v
          for v in MOOD.values()))
sin_desc = [k for k, v in MOOD.items() if not (v.get('desc') or '').strip()]
check('ningun tema sin descripcion (el LLM solo ve el nombre): %s' % (sin_desc[:3],),
      not sin_desc)
check('todas las regex compilan', all(
    M.re.compile(v['regex']) is not None for v in MOOD.values()))
hojas = {}
for k in MOOD:
    hojas.setdefault(k.split('·')[-1].strip().lower(), []).append(k)
choques = {h: v for h, v in hojas.items() if len(v) > 1}
check('sin colisiones de hoja (rompen la 2a pasada de norm_temas): %s' % (choques,),
      not choques)

print('\n== los temas "solo LLM" no los aplica el motor local ==')
clf = M.MLClassifier(model={'classes': ['x'], 'idf': {}, 'coef': {},
                            'intercept': [0.0]}, mood=MOOD)
solo_llm = [k for k, v in MOOD.items() if v['regex'] == '$^']
check('hay temas solo-LLM declarados', len(solo_llm) >= 1)
texto = ' '.join(MOOD) + ' paranormal sin romance mundo inventado sin magia'
check('y ninguno se dispara por regex',
      not [k for k in solo_llm if k in clf.mood_tags(texto)])
check('la descripcion queda accesible en mood_desc',
      clf.mood_desc.get(solo_llm[0]) not in (None, ''))

print('\n== formato ANTIGUO (valor = regex) sigue valiendo ==')
viejo = {'Tono · Oscuro': 'dark romance|romance oscuro'}
clf2 = M.MLClassifier(model={'classes': ['x'], 'idf': {}, 'coef': {},
                             'intercept': [0.0]}, mood=viejo)
check('carga la regex', clf2.mood_tags('a dark romance') == ['Tono · Oscuro'])
check('y deja la descripcion vacia', clf2.mood_desc['Tono · Oscuro'] == '')

print('\n== norm_temas: lo que antes se perdia en silencio ==')
vocab = {'Subgenero · Fantasia urbana': 'Magia oculta en una ciudad real.',
         'Paranormal · Vampiros': 'Vampiros.',
         'Tono · Oscuro': ''}
for entrada in ['Subgenero · Fantasia urbana', 'Subgénero · Fantasía urbana',
                'Subgenero: Fantasia urbana', 'Fantasia urbana',
                'fantasia  urbana', 'SUBGENERO - FANTASIA URBANA']:
    check("%r -> Subgenero · Fantasia urbana" % entrada,
          E.norm_temas([entrada], vocab) == ['Subgenero · Fantasia urbana'])
check('la hoja sola tambien vale',
      E.norm_temas(['Vampiros'], vocab) == ['Paranormal · Vampiros'])
check('un tema inventado se sigue descartando',
      E.norm_temas(['Subgenero · No existe'], vocab) == [])
check('no duplica si viene dos veces escrito distinto',
      E.norm_temas(['Fantasia urbana', 'Subgenero · Fantasia urbana'], vocab)
      == ['Subgenero · Fantasia urbana'])
check('una lista de nombres (sin descripciones) sigue valiendo',
      E.norm_temas(['Tono · Oscuro'], list(vocab)) == ['Tono · Oscuro'])
check('vocabulario vacio -> nada', E.norm_temas(['lo que sea'], []) == [])

print('\n== el bloque de temas va agrupado por eje (3.22.0) ==')
# El prefijo del eje se repetia en las 151 lineas. Ahora es una cabecera y
# debajo van solo las HOJAS, que es lo que `norm_temas` sabe reconocer desde
# 3.10.0. Ahorra ~1.900 caracteres por llamada y acorta tambien la respuesta.
pr = E.build_batch_prompt([{'titulo': 'T', 'autor': 'A'}], vocab)
check('el eje sale UNA vez como cabecera', '\nSUBGENERO:\n' in pr)
check('y no se repite en cada linea',
      '  - Subgenero · Fantasia urbana' not in pr)
check('la hoja lleva su descripcion tras el guion largo',
      '\n  Fantasia urbana — Magia oculta en una ciudad real.\n' in pr)
check('un tema sin descripcion sale solo con la hoja', '\n  Oscuro\n' in pr)
check('avisa de que se responda con la hoja', 'Responde con la HOJA sola' in pr)
check('y de que no se copie la descripcion', 'sin la descripcion' in pr)
check('avisa de que la cabecera NO es un tema', 'no un tema' in pr)
pr2 = E.build_batch_prompt([{'titulo': 'T', 'autor': 'A'}], list(vocab))
check('con lista simple (sin descripciones) tambien agrupa',
      '\nSUBGENERO:\n  Fantasia urbana\n' in pr2)

print('\n== el prompt se parte en system (fijo) y user (los libros) ==')
sis = E.build_system_prompt(vocab)
usr = E.build_user_prompt([{'titulo': 'Mi libro', 'autor': 'Alguien'}])
check('el system lleva las reglas', 'Reglas:' in sis and '4e.' in sis)
check('el system lleva el vocabulario de temas', 'TEMAS permitidos' in sis)
check('el system lleva el formato de respuesta', 'FORMATO DE RESPUESTA' in sis)
check('el system NO lleva ningun libro', 'Mi libro' not in sis)
check('el user lleva los libros', 'Mi libro' in usr and 'Alguien' in usr)
check('el user NO repite las reglas', 'Reglas:' not in usr)
check('el user es diminuto al lado del system', len(usr) * 20 < len(sis))
check('build_batch_prompt sigue devolviendo el prompt entero',
      all(x in E.build_batch_prompt([{'titulo': 'Mi libro', 'autor': 'A'}], vocab)
          for x in ('Reglas:', 'TEMAS permitidos', 'Mi libro')))


print('\n== falsos positivos del motor local (regex sobre la sinopsis) ==')
# El caso que lo destapo: "Wicked Lovers - Mia Para Siempre" (Shayla Black),
# romantica de suspense SIN tags, caia en "Paranormal - Angeles y demonios"
# porque normalize() quita las tildes y "Los Angeles" casaba con \bangeles\b.
clf_real = M.MLClassifier(model={'classes': ['x'], 'idf': {}, 'coef': {},
                                 'intercept': [0.0]}, mood=MOOD)
ANGELES = 'Paranormal \u00b7 Angeles y demonios'

NO_DEBEN = [
    (ANGELES, u'Tyler era un detective en el departamento de polic\u00eda de '
              u'Los \u00c1ngeles, soltero y feliz.'),
    (ANGELES, u'Se mud\u00f3 a Los \u00c1ngeles buscando una segunda oportunidad.'),
    (ANGELES, u'\u2014\u00bfQu\u00e9 demonios haces aqu\u00ed?'),
    (ANGELES, u'\u2014\u00bfC\u00f3mo demonios lo has averiguado?'),
    (ANGELES, u'\u2014\u00bfD\u00f3nde demonios te hab\u00edas metido?'),
    (ANGELES, u'Ten\u00eda una sonrisa angelical y ojos de ni\u00f1a buena.'),
    (ANGELES, u'Ella era un \u00e1ngel, siempre pendiente de los dem\u00e1s.'),
    (ANGELES, u'Eres mi \u00e1ngel, le dijo \u00e9l.'),
    (ANGELES, u'El daemon del servidor dej\u00f3 de responder.'),
]
for tema, texto in NO_DEBEN:
    check(u'%r NO da %s' % (texto[:42], tema.split('\u00b7')[-1].strip()),
          tema not in clf_real.mood_tags(texto))

SI_DEBEN = [
    (ANGELES, u'Un \u00e1ngel ca\u00eddo condenado a vagar entre los mortales.'),
    (ANGELES, u'Los nefilim luchan contra los demonios que asedian la ciudad.'),
    (ANGELES, u'She is an angel sent to guard him from the demons of hell.'),
    (ANGELES, u'\u00c1ngeles y demonios se disputan el alma de Sara.'),
    (ANGELES, u'Un arc\u00e1ngel guerrero y una cazadora de demonios.'),
    (ANGELES, u'El pr\u00edncipe de los infiernos quiere su alma.'),
    (ANGELES, u'A fallen angel and the woman who saved him.'),
    (ANGELES, u'El demonio que la pose\u00f3 no piensa soltarla.'),
    (ANGELES, u'Los \u00e1ngeles ca\u00eddos han declarado la guerra al Cielo.'),
    (ANGELES, u'Un romance con un demonio de las sombras.'),
    (ANGELES, u'Su \u00e1ngel guardi\u00e1n result\u00f3 ser un nefilim.'),
]
for tema, texto in SI_DEBEN:
    check(u'%r SI da %s' % (texto[:42], tema.split('\u00b7')[-1].strip()),
          tema in clf_real.mood_tags(texto))

# Caso 2: "Bachelor Brothers of Sydney - Bought at Auction" (Mel Teshco).
# Romantica contemporanea que salia como Lobos/Shifters por la TAG
# "Themes.Alpha Male": las tags entran en el mismo texto que la sinopsis
# (ml_jobs.py arma title+tags+comments+series), y \balpha\b casaba solo.
SHIFT = 'Paranormal \u00b7 Lobos/Shifters'
OMEGA = 'Paranormal \u00b7 Omegaverse'

BOUGHT = (u'Bachelor Brothers of Sydney - Bought at Auction - Mel Teshco '
          u'Themes.Explicit Sex, English.Romance.Contemporary Romance, '
          u'English.Romance.Paranormal Romance, Themes.Alpha Male '
          u'Aiden Black enjoys his one night stands and the notoriety of being '
          u'a love em and leave em playboy.')
check('la tag "Alpha Male" NO da Lobos/Shifters',
      SHIFT not in clf_real.mood_tags(BOUGHT))

for texto in [u'An alpha billionaire romance.',
              u'A standalone MC romance with alpha male bikers.',
              u'Chase Ryder is an alpha hero to the nth degree.',
              u'Featuring an obsessive alpha husband and his pregnant wife.']:
    check(u'%r NO da Lobos/Shifters' % texto[:40],
          SHIFT not in clf_real.mood_tags(texto))

for texto in [u'A wolf shifter rescue romance.',
              u'The pack alpha claimed her as his mate.',
              u'An alpha wolf and the woman who tamed him.',
              u'El lobo alfa de la manada la eligio a ella.',
              u'A bear alpha and a bunny omega snowed in.',
              u'Werewolves of the northern woods.']:
    check(u'%r SI da Lobos/Shifters' % texto[:40],
          SHIFT in clf_real.mood_tags(texto))

check(u'"alpha and omega series" SI da Omegaverse',
      OMEGA in clf_real.mood_tags(u'The cub and his alphas. Alpha and Omega series, book 7.'))
check(u'un mpreg SI da Omegaverse',
      OMEGA in clf_real.mood_tags(u'The cowboys baby, an mpreg romance.'))
check(u'el "alfa y omega" biblico NO da Omegaverse',
      OMEGA not in clf_real.mood_tags(
          u'El sacerdote de Santa Maria y el alpha and the omega.'))

# Los seis temas de la auditoria 3.20.3. Cada par es (tema, texto); NO_DA son
# expresiones hechas del castellano/ingles corriente que disparaban la regex,
# medidas sobre los 17.763 libros de _datos_ejemplo/sample.csv.
FAE   = 'Paranormal \u00b7 Fae/Feerico'
TRAU  = 'Tono \u00b7 Trauma/Salud mental'
LEGAL = 'Subgenero \u00b7 Thriller legal'
REAL  = 'Arquetipo \u00b7 Realeza'
SIREN = 'Paranormal \u00b7 Sirenas'
ALFA  = 'Arquetipo \u00b7 Alpha male'

NO_DA = [
    (FAE,   u'A fairy tale for grown-ups.'),
    (FAE,   u'Someone elses fairytale.'),
    (FAE,   u'The tooth fairy and her loathsome imps.'),
    (FAE,   u'Santas elves dont seem to be helping much.'),
    (FAE,   u'Su historia parec\u00eda un cuento de hadas.'),
    (FAE,   u'Se cort\u00f3 el pelo, un pixie cut que le sentaba fatal.'),
    (TRAU,  u'Times are difficult during the Great Depression.'),
    (TRAU,  u'A finales de la gran depresi\u00f3n en Estados Unidos.'),
    (TRAU,  u'Se enfrentar\u00e1n cara a cara en un duelo singular.'),
    (TRAU,  u'Las andanzas de su nuevo personaje crean adicci\u00f3n.'),
    (TRAU,  u'Las contradicciones de la historia argentina.'),
    (LEGAL, u'Seg\u00fan un juicio de Walter Benjamin.'),
    (LEGAL, u'El d\u00eda del juicio final ha llegado.'),
    (LEGAL, u'Poner en tela de juicio la extra\u00f1a tradici\u00f3n.'),
    (LEGAL, u'El tribunal de la realidad ha rechazado su instancia.'),
    (REAL,  u'Su amante no es exactamente un pr\u00edncipe azul.'),
    (REAL,  u'No matter what happens, mi princesa.'),
    (SIREN, u'Las sirenas de la polic\u00eda rompieron el silencio.'),
]
for tema, texto in NO_DA:
    check(u'%r NO da %s' % (texto[:40], tema.split('\u00b7')[-1].strip()),
          tema not in clf_real.mood_tags(texto))

SI_DA = [
    (FAE,   u'A dance with fire, Fae Elementals book 1.'),
    (FAE,   u'The faerie realm faces extinction.'),
    (FAE,   u'Never trust an elf, a thief or a woman.'),
    (FAE,   u'Los duendes que se apropian de la vida de los ni\u00f1os.'),
    (TRAU,  u'An angsty tale of love, revenge and PTSD recovery.'),
    (TRAU,  u'Su tratamiento de las adicciones sexuales.'),
    (TRAU,  u'A\u00fan de duelo por el asesinato de su hijo.'),
    (LEGAL, u'Assistant district attorney Lainey Abbott.'),
    (LEGAL, u'El posterior juicio al asesino.'),
    (LEGAL, u'Un abogado de Chicago con demasiados secretos.'),
    (REAL,  u'La enigm\u00e1tica muerte del pr\u00edncipe Ludwig von Arensberg.'),
    (SIREN, u'A reverse harem mermaid romance.'),
    (SIREN, u'El planeta de las sirenas.'),
    (ALFA,  u'An alpha billionaire romance.'),
    (ALFA,  u'A standalone MC romance with alpha male bikers.'),
    (ALFA,  u'Chase Ryder is an alpha hero to the nth degree.'),
]
for tema, texto in SI_DA:
    check(u'%r SI da %s' % (texto[:40], tema.split('\u00b7')[-1].strip()),
          tema in clf_real.mood_tags(texto))

check(u'la tag "Alpha Male" ahora SI da Arquetipo \u00b7 Alpha male',
      ALFA in clf_real.mood_tags(BOUGHT))

# La descripcion que ve el LLM tiene que decir tambien lo que NO cuenta, o
# volvera a poner el tema por su cuenta en la segunda pasada.
check('la desc de Angeles y demonios avisa del uso figurado',
      'Los Angeles' in MOOD[ANGELES]['desc'])

print('\n%d OK, %d fallos' % (ok[0], bad[0]))
sys.exit(1 if bad[0] else 0)
