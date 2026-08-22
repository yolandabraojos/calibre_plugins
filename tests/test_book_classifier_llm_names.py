# -*- coding: utf-8 -*-
"""Pruebas del reconocimiento de nombres de libreria y de la causa del (revisar)."""
import os, sys, json, types, importlib.util

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    os.pardir, 'book_classifier')
spec = importlib.util.spec_from_file_location(
    'llm_rescue_engine', os.path.join(BASE, 'llm_rescue_engine.py'))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

ok = [0]; bad = [0]
def check(name, cond):
    (ok if cond else bad)[0] += 1
    print(('  OK   ' if cond else '  FALLO') + '  ' + name)

print('\n== nombres que ANTES se descartaban en silencio ==')
for entrada, esperado in [
        ('Ciencia Ficción', 'Ciencia Ficción'),
        ('Ciencia Ficcion', 'Ciencia Ficción'),
        ('CIENCIA  FICCION', 'Ciencia Ficción'),
        ('  ciencia ficción  ', 'Ciencia Ficción'),
        ('Misterio·Thriller', 'Misterio·Thriller'),
        ('Misterio/Thriller', 'Misterio·Thriller'),
        ('Misterio', 'Misterio·Thriller'),
        ('Novela negra', 'Misterio·Thriller'),
        ('Terror', 'Terror'),
        ('Terror gótico', 'Terror'),
        ('Paranormal', 'Paranormal'),
        ('Paranormal romance', 'Paranormal'),
        ('urban fantasy', 'Paranormal'),
        ('No-Ficción', 'No-Ficción'),
        ('No Ficcion', 'No-Ficción'),
        ('Fantasía épica', 'Fantasía'),
        ('Romantasy', 'Romantasy')]:
    check("'{}' -> {}".format(entrada, esperado),
          E.norm_libreria(entrada) == esperado)

print('\n== lo que debe seguir siendo (revisar) ==')
for entrada in ['Romance', '', None, 'Misterio·Thriller·Terror',
                'Fantasía o Ciencia Ficción', '(revisar)']:
    check("'{}' -> (revisar)".format(entrada), E.norm_libreria(entrada) == E.REVISAR)
check("'Romance' no elige entre contemporaneo e historico",
      E.norm_libreria('Romance') == E.REVISAR)

print('\n== romance: el SABOR no decide, la EPOCA si ==')
# Un "romantic suspense" puede ser contemporaneo o de epoca: el subgenero
# comercial solo describe el tono. Con la epoca en la respuesta se coloca; sin
# ella se queda en (revisar), igual que 'Romance' a secas.
for entrada, esperado in [
        ('Romantic suspense historico', 'Romance hist\u00f3rico'),
        ('Suspense romantico de epoca', 'Romance hist\u00f3rico'),
        ('Romance de suspense victoriano', 'Romance hist\u00f3rico'),
        ('Romance historico de suspense', 'Romance hist\u00f3rico'),
        ('Romance regencia', 'Romance hist\u00f3rico'),
        ('Romantic suspense contemporary', 'Romance contempor\u00e1neo'),
        ('Thriller romantico actual', 'Romance contempor\u00e1neo'),
        ('Comedia romantica contemporanea', 'Romance contempor\u00e1neo'),
        ('Romance contemporaneo (romantic suspense)', 'Romance contempor\u00e1neo')]:
    check("'{}' -> {}".format(entrada, esperado),
          E.norm_libreria(entrada) == esperado)

print('\n== sin epoca NO se adivina ==')
for entrada in ['Romantic suspense', 'Suspense romantico', 'Thriller romantico',
                'Comedia romantica', 'Dark romance', 'Erotica con romance central',
                'Romance contemporaneo o historico']:
    check("'{}' -> (revisar)".format(entrada), E.norm_libreria(entrada) == E.REVISAR)

print('\n== lo sobrenatural sigue ganando al romance (reglas 4a/4b/4c) ==')
for entrada, esperado in [
        ('Paranormal romance', 'Paranormal'),
        ('Romance paranormal contemporaneo', 'Paranormal'),
        ('Romantasy', 'Romantasy')]:
    check("'{}' -> {}".format(entrada, esperado),
          E.norm_libreria(entrada) == esperado)

print('\n== el prompt dice que el sabor no cambia la estanteria ==')
_pr = E.build_batch_prompt([{'titulo': 'T', 'autor': 'A'}])
check('el mapa avisa de que el sabor comercial no decide',
      'NO decide la estanteria' in _pr)
check('y de que un romantic suspense puede ser de las dos epocas',
      "puede ser cualquiera de las dos" in _pr)
check("la regla 4e manda decidir SOLO por la epoca",
      'Decide SOLO por la EPOCA' in _pr)
check("la 5c saca del thriller lo que tiene romance central",
      "NO es 'Misterio\u00b7Thriller': va a la estanteria de romance" in _pr)
check('el romance historico ya admite suspense de epoca',
      'romantica en epoca real' in _pr)

print('\n== el escenario no gana al romance (caso Mecha Origin) ==')
# "Mecha Origin - As the Cog Turns" (Eve Langlais) salio como Ciencia Ficcion:
# la sinopsis es un romance ("his best friends little sister", "the kiss", "her
# bed", "nothing less than her heart") contado con metaforas mecanicas (cogs,
# gears, upgrades, steam), y el modelo se quedo con los engranajes. La 3c
# -steampunk sin magia -> Ciencia Ficcion- no tenia puerta de romance.
_p = E.build_batch_prompt([{'titulo': 'T', 'autor': 'A'}])
check('la regla 0 cierra las SUB-reglas 3 enteras, no solo 3e/3f',
      'no uses NINGUNA sub-regla 3 (3a-3f)' in _p)
check('y nombra los escenarios tecnologicos que enganaban',
      'robots, mecas, ciborgs, IA, nanotecnologia, engranajes y vapor' in _p)
check('EL ESCENARIO NUNCA GANA AL ROMANCE esta en mayusculas',
      'EL ESCENARIO NUNCA GANA AL ROMANCE' in _p)
check('hay una regla 0b que explica como se ve un romance central',
      '0b. COMO RECONOCER UN ROMANCE CENTRAL' in _p)
check('0b avisa de las metaforas mecanicas',
      'CUIDADO CON LAS METAFORAS' in _p and 'lenguaje sensual' in _p)
check('la cabecera de la 3 dice que es solo sin romance central',
      'SOLO para libros SIN romance central' in _p)
check('la 3c (steampunk) tiene su propia puerta',
      'los engranajes son el escenario, no el genero' in _p)
check('4a admite mundos de maquinas como mundo inventado',
      'sociedad de maquinas, mecas o ciborgs sintientes' in _p)

print('\n== causa del (revisar) ==')
def run(respuesta, n_items=1, min_conf=0.55):
    # `system` viaja aparte desde 3.22.0 (el bloque fijo va en el mensaje
    # system para que el proveedor lo cachee), asi que el doble traga **kw.
    E._dispatch = lambda p: ((lambda prompt, model, key, base, **kw:
                              json.dumps(respuesta)), 'modelo', 'base')
    return E.classify_batch([{'titulo': 't', 'autor': 'a'}] * n_items,
                            'x', 'k', min_conf=min_conf)

r = run([{'n': 1, 'libreria': 'Romance contemporáneo', 'confianza': 0.50,
          'motivo': 'romance en Nueva York con elemento sobrenatural'}])
check('confianza baja -> causa "umbral"', r[0]['causa'] == 'umbral')
check('y la libreria se anula', r[0]['libreria'] == E.REVISAR)
check('pero el motivo se conserva', 'Nueva York' in r[0]['motivo'])
check('y la confianza tambien', r[0]['confianza'] == 0.5)

r = run([{'n': 1, 'libreria': 'Romance contemporáneo', 'confianza': 0.90}])
check('confianza alta -> resuelto sin causa',
      r[0]['libreria'] == 'Romance contemporáneo' and r[0]['causa'] == '')

# 'Novela negra' ya NO vale como ejemplo de nombre desconocido: desde el
# troceo de estanterias lo resuelve el ALIAS a 'Misterio·Thriller'.
r = run([{'n': 1, 'libreria': 'Novela rosa', 'confianza': 0.95}])
check('nombre fuera del catalogo -> causa "nombre"', r[0]['causa'] == 'nombre')
check('guarda el nombre bruto para el informe',
      r[0]['libreria_raw'] == 'Novela rosa')

r = run([{'n': 1, 'libreria': '(revisar)', 'confianza': 0.95}])
check('la IA se declara sin base -> causa "declarado"', r[0]['causa'] == 'declarado')

r = run([{'n': 1, 'confianza': 0.95}])
check('respuesta sin campo libreria -> causa "sin_libreria"',
      r[0]['causa'] == 'sin_libreria')

r = run([{'n': 1, 'libreria': 'Fantasía', 'confianza': 0.9}], n_items=2)
check('libro que no vuelve del modelo -> causa "sin_respuesta"',
      r[1]['causa'] == 'sin_respuesta' and r[0]['causa'] == '')

r = run([{'n': 1, 'libreria': 'Ciencia Ficcion', 'confianza': 0.95}])
check('un nombre sin tilde YA no se pierde',
      r[0]['libreria'] == 'Ciencia Ficción' and r[0]['causa'] == '')

print('\n== ninguna decision del prompt se ha perdido al comprimirlo (3.22.0) ==')
# Al recortar reglas y mapa en 3.22.0 (12.118 -> 10.822 car de reglas,
# 4.495 -> 3.703 el mapa) lo unico que se quito fue palabreria y ejemplos
# repetidos. Esta lista es el inventario de DECISIONES: si un recorte futuro
# se lleva una por delante, este test lo canta.
_sis = E.build_system_prompt()
for etiqueta, marca in [
        ('las 10 estanterias del catalogo', None),
        ('regla 0 (orden de evaluacion)', '0. ORDEN DE EVALUACION'),
        ('regla 0b (que es un romance central)', '0b. COMO RECONOCER'),
        ('regla 1 (no clasificar por el titulo)', '1. NO clasifiques por el titulo'),
        ('regla 2 (no ficcion)', "2. No-ficción"),
        ('regla 3 solo sin romance central', 'SOLO para libros SIN romance central'),
        ('3a linaje humano -> Fantasia', '3a. Poderes innatos'),
        ('3b science fantasy por el MOTOR', 'decide por el MOTOR del conflicto'),
        ('3c steampunk', '3c. Steampunk'),
        ('3d post-colapso', '3d. Post-colapso'),
        ('3e espacio puro sin romance', '3e. Espacio puro'),
        ('3f otra especie -> Ciencia Ficcion', '3f. El poder viene de SER de otra especie'),
        ('3f mantiene la excepcion de la magia', 'gana la magia'),
        ('4a romantasy = mundo inventado', "4a. 'Romantasy'"),
        ('4b paranormal = Tierra reconocible', "4b. 'Paranormal' = Tierra actual"),
        ('4b el romance no es requisito', 'EL ROMANCE NO ES REQUISITO'),
        ('4c no existe romance historico paranormal', "NO existe 'romance "),
        ('4d mundo inventado sin romance', '4d. Mundo INVENTADO'),
        ('4e romance sin fantastico, por epoca', 'Decide SOLO por la EPOCA'),
        ('5a la magia como eje del mundo', '5a. Si la magia'),
        ('5b lo sobrenatural puntual + crimen', '5b. Si lo sobrenatural es solo un RASGO'),
        ('5c thriller sin romance central', "5c. 'Misterio"),
        ('5c el romance central sale del thriller', 'va a la estanteria de romance'),
        ('5d terror es una estanteria por proposito', 'estanteria por PROPOSITO'),
        ('5e desempates de terror', "5e. Desempates de 'Terror'"),
        ('5e el romance manda sobre el terror', "NUNCA 'Terror'"),
        ('6 ficcion general', "6. 'Ficción general'"),
        ('7 si no hay base, revisar', '7. Si de verdad NO tienes base'),
        ('el escenario no gana al romance', 'EL ESCENARIO NUNCA GANA AL ROMANCE'),
        ('el mapa de subgeneros sigue estando', 'MAPA DE SUBGENEROS DE MERCADO'),
        ('y su nota sobre la epoca', 'NOTA SOBRE EL ROMANCE'),
        ('formato de respuesta', 'FORMATO DE RESPUESTA')]:
    if marca is None:
        check(etiqueta, all(l in _sis for l in E.LIBRERIAS))
    else:
        check(etiqueta, marca in _sis)

print('\n== y el prompt no ha vuelto a engordar ==')
_vocab = {n: 'x' * 60 for n in ['Eje · Uno', 'Eje · Dos']}
check('la parte fija sin temas cabe en 16.000 caracteres',
      len(E.build_system_prompt()) < 16000)
check('cada libro anade poco: el user es solo la ficha',
      len(E.build_user_prompt([{'titulo': 'T', 'autor': 'A'}])) < 200)

print('\n%d OK, %d fallos' % (ok[0], bad[0]))
sys.exit(1 if bad[0] else 0)
