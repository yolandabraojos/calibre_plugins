# -*- coding: utf-8 -*-
"""Promocion de los TEMAS de la IA al campo principal (nivel 0, 3.16.0).

Los temas que el rescate dejo en su columna propia sustituyen a los que el
motor local detecta por regex, con el mismo umbral de confianza que la
libreria y validados contra el vocabulario ACTUAL de mood_rules.json.
"""
import os, sys, json, types, importlib.util

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir,
                    'book_classifier')


def _load(name, fname, register=None):
    spec = importlib.util.spec_from_file_location(name, os.path.join(BASE, fname))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[register or name] = mod
    spec.loader.exec_module(mod)
    return mod


pkg = types.ModuleType('calibre_plugins'); pkg.__path__ = []
sub = types.ModuleType('calibre_plugins.book_classifier'); sub.__path__ = [BASE]
sys.modules.update({'calibre_plugins': pkg, 'calibre_plugins.book_classifier': sub})
ENG = _load('llm_rescue_engine', 'llm_rescue_engine.py',
            register='calibre_plugins.book_classifier.llm_rescue_engine')
sub.llm_rescue_engine = ENG
M = _load('ml_jobs_prom', 'ml_jobs.py')

VOCAB = list(json.load(open(os.path.join(BASE, 'mood_rules.json'),
                            encoding='utf-8')).keys())

ok = [0]; bad = [0]


def check(name, cond):
    (ok if cond else bad)[0] += 1
    print(('  OK   ' if cond else '  FALLO') + '  ' + name)


class FakeDB(object):
    """Minimo para _llm_promoted_temas: solo field_for."""

    def __init__(self, valores):
        self.valores = valores

    def field_for(self, campo, bid):
        if campo not in self.valores:
            raise ValueError('columna inexistente: %s' % campo)
        return self.valores[campo]


S = {'llm_temas_field': '#clasificacion_ia', 'llm_temas_prefix': 'Tema IA: ',
     'llm_conf_field': '#confianza_ia', 'llm_promote_threshold': 0.90,
     'llm_promote_temas_enabled': True}


def temas(valores, s=None, vocab=VOCAB):
    return M._llm_promoted_temas(FakeDB(valores), 1, dict(s or S), vocab)


print('\n== se copian con confianza suficiente ==')
r = temas({'#clasificacion_ia': ('Paranormal · Vampiros', 'Tono · Oscuro'),
           '#confianza_ia': 95})
check('columna multivalor -> los dos temas',
      r == ['Paranormal · Vampiros', 'Tono · Oscuro'])
r = temas({'#clasificacion_ia': 'Paranormal · Vampiros, Tono · Oscuro',
           '#confianza_ia': 90})
check('columna de texto con comas -> igual, y 90 justo entra',
      r == ['Paranormal · Vampiros', 'Tono · Oscuro'])

print('\n== el umbral se respeta ==')
check('confianza 89 -> nada',
      temas({'#clasificacion_ia': 'Tono · Oscuro', '#confianza_ia': 89}) == [])
check('sin confianza -> nada',
      temas({'#clasificacion_ia': 'Tono · Oscuro', '#confianza_ia': None}) == [])
check('sin columna de confianza -> nada',
      temas({'#clasificacion_ia': 'Tono · Oscuro'}) == [])
check('desactivado por preferencia -> nada',
      temas({'#clasificacion_ia': 'Tono · Oscuro', '#confianza_ia': 100},
            dict(S, llm_promote_temas_enabled=False)) == [])
check('sin temas en la columna -> nada',
      temas({'#clasificacion_ia': '', '#confianza_ia': 100}) == [])
check('columna inexistente -> nada, sin reventar',
      temas({'#confianza_ia': 100}) == [])

print('\n== se validan contra el vocabulario ACTUAL ==')
check('un nombre desdoblado en 3.10.0 no resucita',
      temas({'#clasificacion_ia': 'Subgenero · Zombi/No muertos, Tono · Oscuro',
             '#confianza_ia': 100}) == ['Tono · Oscuro'])
check('un tema inventado se descarta',
      temas({'#clasificacion_ia': 'Subgenero · Lo que sea', '#confianza_ia': 100}) == [])
check('con tildes de mas se reconoce igual',
      temas({'#clasificacion_ia': 'Subgénero · Fantasía urbana', '#confianza_ia': 100})
      == ['Subgenero · Fantasia urbana'])
check('vocabulario vacio -> nada',
      temas({'#clasificacion_ia': 'Tono · Oscuro', '#confianza_ia': 100}, vocab=[]) == [])

print('\n== en tags hace falta el prefijo ==')
en_tags = dict(S, llm_temas_field='tags')
check('solo se toman los que llevan el prefijo',
      M._llm_promoted_temas(
          FakeDB({'tags': ['Autor favorito', 'Tema IA: Tono · Oscuro'],
                  '#confianza_ia': 100}), 1, en_tags, VOCAB) == ['Tono · Oscuro'])
check('sin prefijo no se toca nada del resto de tags',
      M._llm_promoted_temas(
          FakeDB({'tags': ['Autor favorito', 'Tono · Oscuro'],
                  '#confianza_ia': 100}), 1, en_tags, VOCAB) == [])

print('\n== promocion de LIBRERIA: solo valores del catalogo (3.17.0) ==')

SL = {'llm_library_field': '#libreria_ia', 'llm_library_prefix': 'Biblioteca IA: ',
      'llm_conf_field': '#confianza_ia', 'llm_promote_threshold': 0.90,
      'llm_promote_enabled': True}


def lib(valores, s=None, stats=None):
    return M._llm_promoted_library(FakeDB(valores), 1, dict(s or SL), stats)


check('un nombre del catalogo se promociona',
      lib({'#libreria_ia': 'Paranormal', '#confianza_ia': 95})
      == ('Paranormal', 0.95))
check('el nombre del catalogo VIEJO ya no resucita',
      lib({'#libreria_ia': 'Misterio·Thriller·Terror', '#confianza_ia': 100}) is None)
check('un nombre inventado tampoco',
      lib({'#libreria_ia': 'Novela rosa', '#confianza_ia': 100}) is None)
check('y se canoniza lo que llega mal escrito',
      lib({'#libreria_ia': 'Ciencia Ficcion', '#confianza_ia': 100})[0]
      == 'Ciencia Ficción')
check('los alias comerciales tambien entran, ya canonizados',
      lib({'#libreria_ia': 'Misterio', '#confianza_ia': 100})[0]
      == 'Misterio·Thriller')
check('el umbral sigue mandando',
      lib({'#libreria_ia': 'Paranormal', '#confianza_ia': 80}) is None)
check('columna multivalor propia: el valor entero es de la IA',
      lib({'#libreria_ia': ('Terror',), '#confianza_ia': 100})[0] == 'Terror')

st = {}
lib({'#libreria_ia': 'Misterio·Thriller·Terror', '#confianza_ia': 100}, stats=st)
lib({'#libreria_ia': 'Misterio·Thriller·Terror', '#confianza_ia': 100}, stats=st)
lib({'#libreria_ia': 'Novela rosa', '#confianza_ia': 100}, stats=st)
check('se cuentan los rechazos para el informe',
      st.get('promocion_nombre_invalido') == 3)
check('y se guarda que nombres eran',
      st.get('promocion_nombres', {}).get('Misterio·Thriller·Terror') == 2)

print('\n%d OK, %d fallos' % (ok[0], bad[0]))
sys.exit(1 if bad[0] else 0)
