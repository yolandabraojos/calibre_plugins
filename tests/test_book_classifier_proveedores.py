# -*- coding: utf-8 -*-
"""Servidores configurables (3.20.0): URL propia y proveedores nuevos."""
import os, sys, importlib.util

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir,
                    'book_classifier')
spec = importlib.util.spec_from_file_location(
    'llm_rescue_engine', os.path.join(BASE, 'llm_rescue_engine.py'))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

ok = [0]; bad = [0]


def check(name, cond):
    (ok if cond else bad)[0] += 1
    print(('  OK   ' if cond else '  FALLO') + '  ' + name)


print('\n== catalogo de proveedores ==')
for p in ('glm', 'google', 'openrouter', 'groq', 'mistral', 'cerebras',
          'together', 'local', 'otro', 'anthropic'):
    check('existe %r' % p, p in E.PROVIDERS)
check('los nuevos NO fijan modelo (sus catalogos cambian)',
      all(E.PROVIDERS[p][1] == '' for p in
          ('openrouter', 'groq', 'mistral', 'cerebras', 'together', 'otro')))
check("'otro' tampoco fija URL", E.PROVIDERS['otro'][2] == '')

print('\n== resolucion de modelo y URL ==')
def resolver(prov, model=None, base=None):
    fn, dm, db = E._dispatch(prov)
    return E._resolver_modelo_y_base(prov, model, base, dm, db)

check('un proveedor conocido usa sus valores',
      resolver('glm') == ('glm-4.5-flash', 'https://api.z.ai/api/paas/v4'))
check('la URL de la configuracion tiene prioridad',
      resolver('glm', base='http://mi-servidor:8000/v1')[1] == 'http://mi-servidor:8000/v1')
check('y el modelo de la configuracion tambien',
      resolver('glm', model='glm-5')[0] == 'glm-5')
check('espacios de sobra no cuentan como valor',
      resolver('glm', model='   ', base='  ') == ('glm-4.5-flash',
                                                  'https://api.z.ai/api/paas/v4'))
check('openrouter con modelo escrito a mano funciona',
      resolver('openrouter', model='meta-llama/llama-3.3-70b-instruct:free')
      == ('meta-llama/llama-3.3-70b-instruct:free', 'https://openrouter.ai/api/v1'))

print('\n== errores que explican que falta ==')
try:
    resolver('openrouter')
    check('sin modelo deberia fallar', False)
except RuntimeError as exc:
    check('sin modelo: dice que lo escribas en Modelo',
          'modelo' in str(exc).lower() and 'openrouter' in str(exc))
try:
    resolver('otro', model='loquesea')
    check('sin URL deberia fallar', False)
except RuntimeError as exc:
    check("sin URL: dice donde se pone",
          'URL del servidor' in str(exc))
try:
    E._dispatch('inventado')
    check('proveedor inexistente deberia fallar', False)
except RuntimeError as exc:
    check('proveedor inexistente: lista los validos',
          'openrouter' in str(exc) and 'otro' in str(exc))

print('\n== test_connection no revienta, informa ==')
okc, msg = E.test_connection('otro', 'clave', model='x')
check('devuelve (False, motivo) en vez de lanzar',
      okc is False and 'URL del servidor' in msg)

print('\n== contabilidad de tokens de la ultima llamada (3.22.0) ==')
# El bloque fijo del prompt son ~31.000 caracteres que se repiten en CADA lote.
# Si el proveedor no lo sirve de su cache de prefijo, se paga entero cada vez,
# asi que la traza tiene que poder decirlo.
E._anotar_uso({'prompt_tokens': 8300, 'completion_tokens': 900,
               'prompt_tokens_details': {'cached_tokens': 8000}},
              'prompt_tokens', 'completion_tokens', 'cached_tokens')
check('protocolo OpenAI: lee prompt_tokens_details.cached_tokens',
      E.ULTIMO_USO == {'in': 8300, 'out': 900, 'cache': 8000})
E._anotar_uso({'input_tokens': 8300, 'output_tokens': 900,
               'cache_read_input_tokens': 7900},
              'input_tokens', 'output_tokens', 'cache_read_input_tokens')
check('protocolo Anthropic: lee cache_read_input_tokens',
      E.ULTIMO_USO == {'in': 8300, 'out': 900, 'cache': 7900})
E._anotar_uso({'prompt_tokens': 8300, 'completion_tokens': 900},
              'prompt_tokens', 'completion_tokens', 'cached_tokens')
check('sin datos de cache, cache=0 (no revienta)',
      E.ULTIMO_USO == {'in': 8300, 'out': 900, 'cache': 0})
E._anotar_uso(None, 'prompt_tokens', 'completion_tokens', 'cached_tokens')
check('respuesta sin usage: se queda vacio, nunca lanza', E.ULTIMO_USO == {})
E._anotar_uso({'prompt_tokens': 'no es un numero'}, 'prompt_tokens', 'x', 'y')
check('usage con basura: tampoco lanza', E.ULTIMO_USO == {})

print('\n== el bloque fijo viaja en el mensaje system ==')
capturado = {}
def _falso(prompt, model, key, base, **kw):
    capturado['user'] = prompt
    capturado['system'] = kw.get('system', '')
    return '[{"n": 1, "libreria": "Terror", "confianza": 0.9}]'
E._dispatch = lambda p: (_falso, 'modelo', 'base')
E.classify_batch([{'titulo': 'Un libro raro', 'autor': 'Nadie'}], 'x', 'k')
check('el system lleva las reglas y el catalogo',
      'Reglas:' in capturado['system'] and 'Romantasy' in capturado['system'])
check('el system NO lleva el libro', 'Un libro raro' not in capturado['system'])
check('el mensaje del usuario lleva SOLO el libro',
      'Un libro raro' in capturado['user'] and 'Reglas:' not in capturado['user'])
check('y es una fraccion minima de lo que se envia',
      len(capturado['user']) * 20 < len(capturado['system']))

print('\n%d OK, %d fallos' % (ok[0], bad[0]))
sys.exit(1 if bad[0] else 0)
