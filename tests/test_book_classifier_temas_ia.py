# -*- coding: utf-8 -*-
"""Campo PROPIO para los temas del rescate LLM (`llm_temas_field`, 3.9.0).

Antes, `apply_llm_result` escribia los temas de la IA en el MISMO campo que el
motor local (`ml_mood_field`) y solo si la libreria quedaba resuelta. Estas
pruebas fijan las dos cosas que cambian: campo separado y temas guardados
aunque la libreria no se resuelva.
"""
import os, sys, types, importlib.util

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    os.pardir, 'book_classifier')


def _load(name, fname):
    spec = importlib.util.spec_from_file_location(name, os.path.join(BASE, fname))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# llm_jobs importa `calibre_plugins.book_classifier.ml_jobs`: se registra a mano
# el paquete falso para poder cargarlo fuera de Calibre.
_pkg = types.ModuleType('calibre_plugins'); _pkg.__path__ = []
sys.modules['calibre_plugins'] = _pkg
_sub = types.ModuleType('calibre_plugins.book_classifier'); _sub.__path__ = []
sys.modules['calibre_plugins.book_classifier'] = _sub
_load('calibre_plugins.book_classifier.ml_jobs', 'ml_jobs.py')
J = _load('llm_jobs_under_test', 'llm_jobs.py')

REV = '(revisar)'
ok = [0]; bad = [0]


def check(name, cond):
    (ok if cond else bad)[0] += 1
    print(('  OK   ' if cond else '  FALLO') + '  ' + name)


def L(v):
    """Una columna VACIA hace que _merge_prefixed devuelva cadena con comas;
    una con valor previo devuelve lista. Se normalizan las dos."""
    return [x.strip() for x in v.split(',')] if isinstance(v, str) else list(v)


BASE_SETTINGS = {
    'mood_field': 'tags', 'mood_prefix': 'Tema: ', 'overwrite': True,
    'llm_library_field': '#libreria_ia', 'llm_library_prefix': 'Biblioteca IA: ',
    'llm_temas_field': '#temas_ia', 'llm_temas_prefix': 'Tema IA: ',
    'llm_write_temas': True, 'llm_write_reason': True,
    'llm_reason_field': '#motivo_ia', 'llm_write_serie': True,
    'llm_write_conf': True,
}

print('\n== libro RESUELTO: cada eje a su campo ==')
cfg = J._write_cfg(BASE_SETTINGS)
res = J._empty_result('t')
J.apply_llm_result(
    {'id': 1, 'prev': {'#libreria_ia': None, '#temas_ia': None,
                       'tags': ['Autor favorito', 'Tema: Regex del motor local']}},
    {'libreria': 'Paranormal', 'confianza': 0.9, 'motivo': 'm',
     'temas': ['Paranormal · Vampiros', 'Tono · Oscuro']},
    cfg, res, revisar=REV)
w = res['writes_by_field']
check('la libreria va a #libreria_ia', L(w['#libreria_ia'][1]) == ['Paranormal'])
check('los temas van a #temas_ia',
      L(w['#temas_ia'][1]) == ['Paranormal · Vampiros', 'Tono · Oscuro'])
check('NO se tocan los Tema: del motor local', 'tags' not in w)

print('\n== libro SIN resolver: los temas ya no se pierden ==')
res = J._empty_result('t')
J.apply_llm_result(
    {'id': 2, 'prev': {'#temas_ia': None}},
    {'libreria': REV, 'causa': 'umbral', 'confianza': 0.4, 'motivo': 'm',
     'temas': ['Tono · Oscuro']},
    cfg, res, revisar=REV)
w = res['writes_by_field']
check('no se escribe libreria', '#libreria_ia' not in w)
check('pero SI los temas', L(w['#temas_ia'][2]) == ['Tono · Oscuro'])
check('y se cuentan aparte para el informe', res['temas_sin_libreria'] == 1)
check('la causa del (revisar) se sigue registrando',
      res['revisar_causes'].get('umbral') == 1)

print('\n== sin temas devueltos: no se escribe nada ==')
res = J._empty_result('t')
J.apply_llm_result({'id': 7, 'prev': {}},
                   {'libreria': 'Paranormal', 'confianza': 0.9, 'temas': [],
                    'motivo': 'm'}, cfg, res, revisar=REV)
check('no crea una escritura vacia', '#temas_ia' not in res['writes_by_field'])

print('\n== campo VACIO = comportamiento anterior a 3.9.0 ==')
s2 = dict(BASE_SETTINGS); s2['llm_temas_field'] = ''
cfg2 = J._write_cfg(s2)
check('cae al campo del motor local', cfg2['temas_field'] == 'tags')
check('y usa su prefijo', cfg2['temas_prefix_eff'] == 'Tema: ')
res = J._empty_result('t')
J.apply_llm_result(
    {'id': 6, 'prev': {'tags': ['Autor favorito', 'Tema: Regex viejo']}},
    {'libreria': 'Paranormal', 'confianza': 0.9, 'motivo': 'm',
     'temas': ['Tono · Oscuro']}, cfg2, res, revisar=REV)
check('vuelve a pisar los Tema: del motor local',
      res['writes_by_field']['tags'][6] == ['Autor favorito', 'Tema: Tono · Oscuro'])

print('\n== libreria y temas en el MISMO campo: no se pisan ==')
s3 = dict(BASE_SETTINGS)
s3['llm_library_field'] = 'tags'; s3['llm_temas_field'] = 'tags'
cfg3 = J._write_cfg(s3)
res = J._empty_result('t')
J.apply_llm_result(
    {'id': 3, 'prev': {'tags': ['Autor favorito', 'Biblioteca IA: Vieja',
                                'Tema: Viejo']}},
    {'libreria': 'Fantasía', 'confianza': 0.9, 'motivo': 'm',
     'temas': ['Tono · Oscuro']}, cfg3, res, revisar=REV)
check('las dos escrituras se encadenan',
      res['writes_by_field']['tags'][3] ==
      ['Autor favorito', 'Biblioteca IA: Fantasía', 'Tema: Tono · Oscuro'])

print('\n== grupo de duplicados ==')
res = J._empty_result('t')
J.apply_llm_result(
    {'id': 4, 'prev': {'#temas_ia': None},
     'dup_group': [{'id': 4, 'prev': {'#temas_ia': None}},
                   {'id': 5, 'prev': {'#temas_ia': ['Previo']}}]},
    {'libreria': 'Paranormal', 'confianza': 0.9, 'motivo': 'm',
     'temas': ['Tono · Oscuro']}, cfg, res, revisar=REV)
w = res['writes_by_field']['#temas_ia']
check('escribe en las dos copias', sorted(w) == [4, 5])
check('y reemplaza el valor previo de la columna propia',
      L(w[5]) == ['Tono · Oscuro'])

print('\n%d OK, %d fallos' % (ok[0], bad[0]))
sys.exit(1 if bad[0] else 0)
