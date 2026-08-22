# -*- coding: utf-8 -*-
"""
Motor de rescate LLM en la nube para Book Classifier (Python puro, urllib).

No usa dependencias externas: funciona dentro del Python embebido de Calibre.
Clasifica en UNA de las librerías (o (revisar)) y, opcionalmente, detecta temas
de un vocabulario cerrado. Envía varios libros por llamada (batching).

Se usa desde el worker (llm_jobs.py). No importa nada de Qt ni de Calibre.
"""
from __future__ import unicode_literals, division, absolute_import, print_function

import json
import re
import time
import unicodedata

try:
    import urllib.request as _rq
    import urllib.error as _er
except ImportError:  # Python 2 (no debería, Calibre 5+ es py3)
    import urllib2 as _rq
    _er = _rq

# Librerías que puede asignar el LLM (10). Dos cambios respecto al catálogo
# de 9: 'Paranormal' ya NO exige romance central -es lo sobrenatural insertado
# en la Tierra reconocible, con o sin romance (regla 4b)- y el antiguo
# 'Misterio·Thriller·Terror' se parte en 'Misterio·Thriller' y 'Terror',
# que son dos experiencias de lectura distintas: resolver algo y pasar miedo.
# La granularidad más fina (paranormal con o sin romance, tipo de terror, las
# ramas de Romantasy) NO son estanterías: son TEMAS de mood_rules.json.
# Deben ser las que quieres ver como "Biblioteca: ...".
LIBRERIAS = [
    "Romance contemporáneo",
    "Romance histórico",
    "Romantasy",
    "Paranormal",
    "Fantasía",
    "Ciencia Ficción",
    "Misterio·Thriller",
    "Terror",
    "Ficción general",
    "No-Ficción",
]

# Nombres del catálogo VIEJO. No se traducen solos: el reparto depende del
# contenido del libro, no del nombre (un 'Misterio·Thriller·Terror' puede ser
# cualquiera de las dos nuevas). Mejor '(revisar)' que un falso positivo.
OBSOLETAS = frozenset(("misterio thriller terror", "misterio terror",
                       "thriller terror"))

# Nombres comerciales frecuentes -> estantería del catálogo. La clave va ya
# normalizada con _lib_key (sin tildes, sin puntuación, en minúsculas).
ALIAS = {
    "misterio": "Misterio·Thriller",
    "thriller": "Misterio·Thriller",
    "suspense": "Misterio·Thriller",
    "novela negra": "Misterio·Thriller",
    "policiaco": "Misterio·Thriller",
    "terror sobrenatural": "Terror",
    "terror psicologico": "Terror",
    "terror gotico": "Terror",
    "horror": "Terror",
    "paranormal romance": "Paranormal",
    "romance paranormal": "Paranormal",
    "fantasia urbana": "Paranormal",
    "urban fantasy": "Paranormal",
}
REVISAR = "(revisar)"

# Etiquetas COMERCIALES de romance ('romantic suspense', 'thriller romantico',
# 'comedia romantica', 'dark romance'...). El sabor NO decide la estanteria:
# la decide la EPOCA (regla 4e del prompt). Un suspense romantico puede ser
# contemporaneo o de epoca, asi que si la respuesta no dice cual, se queda en
# REVISAR igual que 'Romance' a secas. Solo cuando la respuesta trae la epoca
# se puede colocar sin adivinar.
_RX_ROMANCE = re.compile(
    r"\b(?:romance|romances|romantic|romantica|romantico|romanticas|romanticos)\b")
_RX_EPOCA_HIST = re.compile(
    r"\b(?:historic[oa]s?|historical|epoca|regencia|regency|victorian[oa]|victorian|"
    r"eduardian[oa]|georgian[oa]|medieval|highlander|western|siglo)\b")
_RX_EPOCA_CONT = re.compile(
    r"\b(?:contemporane[oa]s?|contemporary|actual|actuales|moderno|modern)\b")
# Estanterias que GANAN al romance por las reglas 4a/4b/4c: si la respuesta las
# menciona, no se adivina nada. 'suspense', 'thriller' y 'misterio' NO estan
# aqui a proposito: ahi el romance central manda (reglas 4e y 5c).
_RX_GANAN_AL_ROMANCE = re.compile(
    r"\b(?:paranormal|sobrenatural|fantasia|fantasy|romantasy|ciencia|sci ?fi|"
    r"terror|horror|ficcion)\b")

SYSTEM = (
    "Eres un bibliotecario experto que clasifica libros en librerías temáticas "
    "y detecta sus tropos. Respondes SIEMPRE con un único array JSON válido, "
    "un objeto por libro y en el mismo orden, sin texto alrededor."
)

# proveedor -> (protocolo, modelo_por_defecto, base_url)
#
# Casi todos hablan el protocolo de OpenAI, asi que anadir un servidor nuevo es
# solo una linea aqui. Y para los que no esten, existe "otro": la URL se pone
# en la configuracion (`llm_base_url`), sin tocar codigo.
#
# El modelo por defecto envejece: los proveedores retiran nombres cada pocos
# meses. Si un proveedor lo trae VACIO es que hay que escribirlo a mano en la
# configuracion (el catalogo de modelos de OpenRouter/Groq cambia demasiado
# como para fijar uno aqui y que siga existiendo).
PROVIDERS = {
    "glm":        ("openai", "glm-4.5-flash",     "https://api.z.ai/api/paas/v4"),
    "deepseek":   ("openai", "deepseek-v4-flash", "https://api.deepseek.com/v1"),
    "openai":     ("openai", "gpt-4o-mini",       "https://api.openai.com/v1"),
    "google":     ("openai", "gemini-3.1-flash-lite",
                   "https://generativelanguage.googleapis.com/v1beta/openai"),
    "kimi":       ("openai", "kimi-k2.5",         "https://api.moonshot.ai/v1"),
    "qwen":       ("openai", "qwen-flash",
                   "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
    "openrouter": ("openai", "", "https://openrouter.ai/api/v1"),
    "groq":       ("openai", "", "https://api.groq.com/openai/v1"),
    "mistral":    ("openai", "", "https://api.mistral.ai/v1"),
    "cerebras":   ("openai", "", "https://api.cerebras.ai/v1"),
    "together":   ("openai", "", "https://api.together.xyz/v1"),
    "local":      ("openai", "llama3.1",          "http://localhost:11434/v1"),
    "otro":       ("openai", "", ""),
    "anthropic":  ("anthropic", "claude-haiku-4-5", "https://api.anthropic.com"),
}


# Diccionario de equivalencias entre la etiqueta COMERCIAL que aparece en los
# tags o la sinopsis y la estantería. Resuelve de un vistazo el grueso de los
# casos y deja las reglas 0-7 para los híbridos. Son ~50 líneas fijas por
# llamada: con lotes de 20 libros el sobrecoste por libro es marginal.
MAPA_SUBGENEROS = """
MAPA DE SUBGENEROS DE MERCADO (la etiqueta comercial que veras en los TAGS o la
sinopsis, y su estanteria). Si un subgenero de la lista describe el libro, esa es
la estanteria, salvo que una regla posterior (0-7) diga lo contrario.
 - Romance contemporáneo: rom-com, chick-lit, new adult/universitario,
   deportistas, billonario/CEO, mafia, moteros/MC, militar, medico, small town,
   navideno, dark romance actual, erotica con romance central, romantic suspense
   ACTUAL. Ej.: Colleen Hoover, Ali Hazelwood, Elle Kennedy.
 - Romance histórico: regencia, victoriano/eduardiano, highlander, western,
   piratas, romance belico (I y II GM), saga de epoca, y el suspense o la intriga
   romantica en epoca real. SIEMPRE sin nada sobrenatural (4c). Ej.: Julia Quinn,
   Lisa Kleypas, Amanda Quick.
 - Romantasy: romance central en MUNDO INVENTADO, lo mueva la magia o la
   tecnologia: fantasy romance de mundo secundario, fae, academia magica, jinetes
   de dragones, dark romantasy, alien/sci-fi romance de imperio o planeta propio,
   novias interestelares, reino o distopia ficticia sin magia. Ej.: Sarah J. Maas,
   Rebecca Yarros, Ruby Dixon, Kiera Cass.
 - Paranormal: sobrenatural INSERTADO en la Tierra reconocible, con o sin
   romance: paranormal romance (vampiros, shifters, angeles y demonios, brujas,
   fantasmas, monster romance, alien entre humanos) y tambien urban fantasy con
   detective o cazador, mitologia viva, juvenil con criaturas, sociedad oculta,
   gaslamp en una epoca real. Ej.: Meyer, J.R. Ward, Cassandra Clare, Jim Butcher,
   Rick Riordan, Neil Gaiman, Ben Aaronovitch.
 - Fantasía: alta fantasia y epica, grimdark, espada y brujeria, cozy fantasy,
   portal fantasy, juvenil de mundo secundario, mitologico en un mundo antiguo,
   LitRPG/GameLit, cultivo. Mundo inventado y sin romance central. Ej.: Tolkien,
   Sanderson, Abercrombie, Travis Baldree.
 - Ciencia Ficción: space opera, hard SF, cyberpunk/biopunk, distopia
   tecnologica, postapocaliptico y zombi de origen cientifico, primer contacto,
   IA, viaje en el tiempo con explicacion cientifica, military SF, cli-fi. Ej.:
   Herbert, Liu Cixin, Gibson, Suzanne Collins.
 - Misterio·Thriller: whodunit, cozy mystery, novela negra y hardboiled,
   policiaco, misterio historico, thriller psicologico, domestico, legal,
   financiero, politico, espionaje, accion, techno, medico, secuestro. Amenaza
   HUMANA y resolucion racional. Ej.: Christie, Camilleri, Gillian Flynn, le
   Carre, Harlan Coben.
 - Terror: casa encantada, fantasmas, posesion, maldiciones, demonios, monstruos,
   terror cosmico, gotico, folk horror, slasher, home invasion, sectas, body
   horror, supervivencia extrema, terror psicologico. Lo define el PROPOSITO: dar
   miedo. Ej.: Stephen King, Shirley Jackson, Lovecraft, Jack Ketchum.
 - Ficción general: literaria y upmarket, drama contemporaneo, saga familiar,
   novela historica NO romantica, coming-of-age realista, autoficcion, humor,
   belica sin romance central, realismo magico suave, poesia y teatro. Ej.: Ken
   Follett, Elena Ferrante, Isabel Allende, Delia Owens.
 - No-Ficción: ensayo, biografia y memorias, historia, divulgacion, autoayuda,
   negocios, cocina, viajes, espiritualidad, true crime documental, manuales.

NOTA SOBRE EL ROMANCE: el sabor comercial -suspense, thriller, misterio, comedia,
dark, erotica, deportistas, mafia- NO decide la estanteria, solo describe el tono.
En un romance SIN nada sobrenatural la decide la EPOCA (4e): presente ->
'Romance contemporáneo'; epoca real pasada -> 'Romance histórico'. Un 'romantic
suspense' puede ser cualquiera de las dos: mira la ambientacion, no la etiqueta.
El sabor se anota como TEMA, no como estanteria.
"""


def _partes(items, temas_vocab=None, librerias=None, pedir_serie=False):
    """Devuelve (sistema, usuario).

    `sistema` es la parte FIJA -catalogo, mapa de subgeneros, vocabulario de
    temas y reglas-: identica en todas las llamadas de una tanda. Va en el
    mensaje `system` para que la cache de prefijo del proveedor la cobre una
    vez (Gemini la cachea sola; `classify_batch` deja en la traza cuantos
    tokens vinieron de cache). `usuario` es lo unico que cambia: los libros."""
    librerias = librerias or LIBRERIAS
    opciones = "\n".join("  - " + l for l in librerias)
    bloque_temas = ""
    campo_temas = ""
    campo_serie = ""
    regla_serie = ""
    if pedir_serie:
        campo_serie = '"serie": "<nombre de la saga/serie o null>", '
        regla_serie = (
            "8. En 'serie', si el libro pertenece a una saga/serie conocida, "
            "escribe SOLO el nombre de la serie (sin numero ni titulo del libro). "
            "Si es autoconclusivo o no lo sabes con seguridad, pon null. No inventes.\n")
    if temas_vocab:
        # `temas_vocab` puede ser una lista de nombres o un dict
        # {nombre: descripcion} (mood_rules.json con el formato nuevo). Con
        # descripcion el modelo deja de adivinar que significa cada tema: solo
        # ve los NOMBRES, nunca la regex, asi que un nombre que mezcla dos
        # conceptos era ambiguo sin remedio.
        # Agrupados por EJE. El prefijo ('Dinamica \u00b7 ', 'Subgenero \u00b7 '...)
        # se repetia en las 151 lineas: sacarlo a una cabecera ahorra ~1.900
        # caracteres por llamada, y responder solo con la HOJA acorta tambien
        # la respuesta. `norm_temas` reconoce la hoja suelta desde 3.10.0 y el
        # test de vocabulario vigila que no haya dos hojas iguales.
        es_dict = isinstance(temas_vocab, dict)
        grupos, orden = {}, []
        for t in temas_vocab:
            partes_t = t.split("\u00b7")
            eje = partes_t[0].strip() if len(partes_t) > 1 else ""
            hoja = partes_t[-1].strip()
            if eje not in grupos:
                grupos[eje] = []
                orden.append(eje)
            desc = temas_vocab.get(t) if es_dict else ""
            grupos[eje].append("  " + hoja + ((" \u2014 " + desc) if desc else ""))
        lista = "\n".join(
            ((eje.upper() + ":\n") if eje else "") + "\n".join(grupos[eje])
            for eje in orden)
        aviso = ("Responde con la HOJA sola, tal cual esta escrita"
                 + (", sin la descripcion que va tras el guion largo"
                    if es_dict else "")
                 + ". La linea en MAYUSCULAS es solo el eje de las hojas de "
                   "debajo, no un tema.")
        bloque_temas = ("\nTEMAS permitidos (elige 0 o más SOLO de esta lista). "
                        + aviso + "\n" + lista + "\n")
        campo_temas = '"temas": [<0+ temas de la lista>], '
    libros = []
    for i, it in enumerate(items, 1):
        partes = ["[%d] Título: %s" % (i, it.get("titulo", "")),
                  "    Autor: %s" % (it.get("autor") or "(desconocido)")]
        if it.get("sinopsis"):
            partes.append("    Sinopsis: %s" % it["sinopsis"][:1200])
        if it.get("tags"):
            partes.append("    Tags: %s" % it["tags"])
        libros.append("\n".join(partes))
    sistema = (
        "Clasifica CADA libro en UNA librería (excluyentes):\n" + opciones + "\n"
        + MAPA_SUBGENEROS
        + bloque_temas + "\n"
        "Reglas:\n"
        "0. ORDEN DE EVALUACION: mira PRIMERO si hay elemento fantastico, "
        "sobrenatural o sci-fi. Si lo hay, decide por la AMBIENTACION (regla "
        "4): Tierra actual o reconocible \u2192 'Paranormal', TENGA O NO romance; "
        "mundo INVENTADO \u2192 'Romantasy' si el romance es un PILAR CENTRAL de "
        "la trama, y si no 'Fantasía' o 'Ciencia Ficción'. Si HAY romance "
        "central no uses NINGUNA sub-regla 3 (3a-3f): esas solo reparten entre "
        "'Fantasía' y 'Ciencia Ficción' y son para libros SIN romance central. "
        "EL ESCENARIO NUNCA GANA AL ROMANCE: da igual que haya naves, "
        "alienigenas, robots, mecas, ciborgs, IA, nanotecnologia, engranajes y "
        "vapor, un futuro tecnologico o una distopia. Un reverse harem / harem "
        "inverso / 'why choose' SIEMPRE tiene romance central por definicion. "
        "Si NO hay ningun elemento fantastico, sigue con las reglas 1, 2, 4e, "
        "5, 6 y 7 en orden normal.\n"
        "0b. COMO RECONOCER UN ROMANCE CENTRAL: la sinopsis cuenta la relacion "
        "entre dos (o mas) personajes -atraccion, deseo, un beso, la cama, "
        "celos, un pasado en comun, 'su corazon', final feliz- y si le quitas "
        "esa relacion no queda trama. Formulas que lo delatan aunque el "
        "escenario sea tecnologico: 'la hermana pequena de mi mejor amigo', "
        "'segunda oportunidad', 'de enemigos a amantes', 'no se conformara con "
        "menos que su corazon', 'ella lo invita a su cama'. Y CUIDADO CON LAS "
        "METAFORAS: en el romance de robots, mecas o steampunk los "
        "'engranajes', las 'piezas', las 'mejoras', los 'circuitos' o el "
        "'vapor' suelen ser el lenguaje sensual del libro, no ingenieria. Si la "
        "sinopsis va de dos personajes que se desean y usa vocabulario "
        "mecanico para contarlo, es romance, no Ciencia Ficcion.\n"
        "1. NO clasifiques por el titulo solo: el titulo aislado NO basta (una "
        "misma palabra cabe en varios generos). Basate en la SINOPSIS, los TAGS y "
        "el autor. Puedes usar titulo+autor sin sinopsis SOLO si reconoces con "
        "certeza ese libro o esa saga concreta; si no lo reconoces y no hay "
        "sinopsis ni tags utiles, responde libreria='" + REVISAR + "' (no adivines "
        "por palabras del titulo).\n"
        "2. No-ficción, ensayo, biografía o divulgación → 'No-Ficción'.\n"
        "3. Fantasía vs Ciencia Ficción. SOLO para libros SIN romance central "
        "(si lo hay, salta a la regla 4). Base: magia, mundos secundarios y "
        "criaturas vs tecnologia explicada, futuro y espacio. Para hibridos:\n"
        "   3a. Poderes innatos por sangre, linaje o mutacion SIN magia "
        "explicita ni base tecnologica (dones, castas de nacimiento, mutantes "
        "tipo X-Men): 'Fantasía'. Ni 'poderes' ni 'distopia' bastan para "
        "llamarlo Ciencia Ficcion. Solo lo es si el poder se explica por "
        "ciencia real (experimentos, virus, ingenieria genetica, IA) \u2192 "
        "'Ciencia Ficción'.\n"
        "   3b. Science fantasy (tecnologia y poder mistico sin explicar en el "
        "mismo mundo: elegidos, profecias, una 'fuerza' heredada, estilo Star "
        "Wars): decide por el MOTOR del conflicto. Poder mistico o profetico "
        "\u2192 'Fantasía'; problemas tecnologicos plausibles \u2192 'Ciencia "
        "Ficción'. Naves y planetas por si solos no bastan.\n"
        "   3c. Steampunk / retrofuturismo (vapor, engranajes, dirigibles, "
        "automatas, era victoriana alternativa): si ademas hay magia, criaturas "
        "u ocultismo que funcionan de verdad \u2192 'Fantasía'; si todo es "
        "tecnologia anacronica e inventos, sin magia real \u2192 'Ciencia Ficción'. "
        "Pero si hay ROMANCE CENTRAL esta regla no aplica (regla 0): los "
        "engranajes son el escenario, no el genero \u2192 regla 4.\n"
        "   3d. Post-colapso: si tras la caida de la civilizacion la magia "
        "(re)aparece o la tecnologia antigua se trata como leyenda o religion "
        "sin explicacion \u2192 'Fantasía'; si es postapocaliptico puramente "
        "tecnologico o biologico (virus, ruinas, supervivencia, sin magia) \u2192 "
        "'Ciencia Ficción'.\n"
        "   3e. Espacio puro sin magia (space opera, naves, invasiones "
        "alienigenas, colonias, IA) y sin romance central \u2192 'Ciencia Ficción'.\n"
        "   3f. El poder viene de SER de otra especie (alienigena, hibrido, "
        "descendiente), aunque su biologia no se explique \u2192 'Ciencia "
        "Ficción'. No apliques 3a aqui: 3a es linaje o casta HUMANA con dones "
        "sin explicar (\u2192 Fantasía). EXCEPCION: si ese mundo tiene ademas "
        "magia que funciona de verdad (hechizos, criaturas, poder mistico no "
        "biologico), gana la magia \u2192 'Fantasía'.\n"
        "   Si la lista de TEMAS esta disponible, marca la sub-regla que "
        "aplicaste añadiendo el tema correspondiente: 3b \u2192 'Subgenero · "
        "Science fantasy'; 3c \u2192 'Subgenero · Steampunk'; 3d \u2192 'Subgenero · "
        "Postcolapso con magia'; 3f \u2192 'Subgenero · Poder alienigena'.\n"
        "4. Elemento fantastico, sobrenatural o sci-fi: decide PRIMERO por la "
        "AMBIENTACION, y solo despues por el romance.\n"
        "   4a. 'Romantasy' = romance central como PILAR de la trama + mundo "
        "INVENTADO por el autor, NO reconocible como el nuestro: reino o "
        "imperio magico, mundo secundario, corte de hadas, imperio espacial "
        "propio, colonia en otro planeta, sociedad de maquinas, mecas o "
        "ciborgs sintientes, distopia o pais ficticio de nueva planta. Da "
        "igual que el motor del mundo sea magia o tecnologia: lo "
        "que importa es que el mundo NO es la Tierra reconocible. Si la lista "
        "de TEMAS esta disponible, marca la rama: mundo tecnologico o "
        "alienigena \u2192 'Subgenero \u00b7 Romance alienigena/Sci-fi'; mundo "
        "inventado sin magia ni ciencia (realeza ficticia, sociedad de castas "
        "sin explicar) \u2192 'Subgenero \u00b7 Mundo inventado sin magia'.\n"
        "   4b. 'Paranormal' = Tierra actual o reconocible (ciudad o pueblo "
        "real, nuestra historia, un futuro cercano que sigue siendo nuestro "
        "mundo) con algo sobrenatural o alienigena INSERTADO: vampiros en "
        "Nueva York, licantropos en un pueblo, un alien conviviendo con "
        "humanos, fantasmas, angeles, demonios, brujas, dioses, cazadores. EL "
        "ROMANCE NO ES REQUISITO: vale con romance central (paranormal "
        "romance) y sin el (urban fantasy con detective o cazador, mitologia "
        "viva, coming-of-age en esa sociedad). Si hay lista de TEMAS marca "
        "cual: 'Paranormal romance' o 'Paranormal sin romance'. Dos "
        "excepciones, de la regla 5: foco en resolver un crimen concreto y lo "
        "sobrenatural es puntual \u2192 'Misterio\u00b7Thriller' (5b); el libro "
        "busca dar MIEDO \u2192 'Terror' (5d).\n"
        "   4c. ESTO APLICA IGUAL EN AMBIENTACION HISTORICA: Londres "
        "victoriano/eduardiano, Persia antigua o regencia CON demonios, "
        "maldiciones, magia o cazadores sobrenaturales (p.ej. Shadowhunters) "
        "es Tierra reconocible del pasado \u2192 'Paranormal'. NO existe 'romance "
        "historico paranormal': si detectas algo sobrenatural en tu propio "
        "motivo, NO puede ser 'Romance histórico'. 'Romance histórico' es SOLO "
        "romance terrenal en epoca real pasada (intriga de corte, matrimonios "
        "concertados, guerra, sociedad de la epoca) SIN nada magico ni "
        "sobrenatural.\n"
        "   4d. Mundo INVENTADO y el amor NO es un pilar central \u2192 reglas 3: "
        "'Fantasía' o 'Ciencia Ficción' segun corresponda. La ausencia de "
        "romance NUNCA manda a 'Fantasía' un libro de la Tierra reconocible: "
        "para eso esta 4b.\n"
        "   4e. Romance central SIN ningun elemento fantastico ni sobrenatural: "
        "en el presente \u2192 'Romance contemporáneo'; en epoca real pasada \u2192 "
        "'Romance histórico'. Decide SOLO por la EPOCA: el sabor del romance "
        "(suspense, thriller, misterio, comedia, dark, erotica, deportistas, "
        "mafia...) NO cambia la estanteria. Un 'romantic suspense' o un "
        "'thriller romantico' es 'Romance contemporáneo' si pasa hoy y "
        "'Romance histórico' si pasa en epoca real pasada. Si la lista de "
        "TEMAS esta disponible, anota ahi el sabor (p.ej. 'Subgenero \u00b7 "
        "Romantic suspense').\n"
        "5. Lo sobrenatural + crimen o miedo: distingue DONDE vive lo "
        "sobrenatural y CUAL es el proposito del libro.\n"
        "   5a. Si la magia, las criaturas o los poderes son el EJE DEL MUNDO "
        "(sociedad de magos, razas sobrenaturales organizadas, sistema de magia "
        "como worldbuilding), aunque la trama sea de investigacion o caza de "
        "monstruos, NO uses 'Misterio\u00b7Thriller' salvo que el foco real sea "
        "resolver un crimen concreto (5b). En su lugar:\n"
        "      - mundo INVENTADO (ver 4a) \u2192 'Romantasy' si hay romance "
        "central, si no 'Fantasía' o 'Ciencia Ficción' (reglas 3 y 4d);\n"
        "      - Tierra actual o reconocible, presente o pasada (ver 4b y 4c) "
        "\u2192 'Paranormal', haya o no romance central.\n"
        "   5b. Si lo sobrenatural es solo un RASGO PUNTUAL de la protagonista "
        "en un mundo por lo demas normal y el foco real es resolver un crimen "
        "(cozy mystery con bruja detective que regenta una tienda en un pueblo "
        "normal, medium que ayuda a la policia, fantasma testigo), SI es "
        "'Misterio\u00b7Thriller'. Prueba rapida: si quitando el toque magico "
        "la trama sigue siendo un misterio reconocible, es "
        "'Misterio\u00b7Thriller'; si sin la magia el mundo entero se cae, "
        "aplica 5a.\n"
        "   5c. 'Misterio\u00b7Thriller' cubre ademas todo el crimen y la "
        "tension realistas: whodunit, cozy mystery, novela negra, policiaco, "
        "thriller psicologico o domestico, legal, politico, espionaje y "
        "thriller de accion. Amenaza HUMANA y resolucion racional, sin "
        "worldbuilding magico de fondo y sin romance central. Si el romance SI "
        "es central (la pareja y su relacion son el eje, y el crimen o la "
        "amenaza es lo que los junta o los pone en peligro), NO es "
        "'Misterio\u00b7Thriller': va a la estanteria de romance que le "
        "corresponda por EPOCA (regla 4e), sea contemporanea o historica.\n"
        "   5d. 'Terror' es una estanteria por PROPOSITO: el libro esta escrito "
        "para dar MIEDO, no para resolver un enigma ni para explorar un mundo. "
        "Cubre el terror sobrenatural (casa encantada, posesion, fantasmas, "
        "maldiciones, demonios, monstruos, terror cosmico, gotico, folk "
        "horror) y el realista (slasher, home invasion, sectas, supervivencia "
        "extrema, body horror, terror psicologico sin nada sobrenatural). Si "
        "la lista de TEMAS esta disponible, marca cual: 'Subgenero \u00b7 Terror "
        "sobrenatural' o 'Subgenero \u00b7 Terror realista'; si el libro nunca "
        "confirma lo sobrenatural, usa el realista.\n"
        "   5e. Desempates de 'Terror':\n"
        "      - vs 'Misterio\u00b7Thriller': miedo, asco o atmosfera de horror "
        "\u2192 'Terror'; tension de una trama racional que se resuelve \u2192 "
        "'Misterio\u00b7Thriller'. Un asesino en serie perseguido por la policia "
        "es 'Misterio\u00b7Thriller'; el mismo asesino como pesadilla visceral "
        "es 'Terror'.\n"
        "      - vs 'Paranormal': lo sobrenatural como AMENAZA que aterra \u2192 "
        "'Terror'; como MUNDO habitado con reglas y facciones, en tono de "
        "aventura o misterio \u2192 'Paranormal'.\n"
        "      - vs 'Ciencia Ficción' (zombis, plagas, alienigenas): miedo y "
        "supervivencia visceral \u2192 'Terror'; origen cientifico, sociedad o "
        "ideas \u2192 'Ciencia Ficción'.\n"
        "      - Con romance central manda la regla 4 ('Paranormal' o "
        "'Romantasy'), NUNCA 'Terror'.\n"
        "6. 'Ficción general' = narrativa SIN elementos de genero claros: sin "
        "magia de worldbuilding, sin crimen central, sin arco romantico "
        "central, sin ciencia ficcion (drama contemporaneo, literatura, "
        "autoficcion). Un toque especulativo leve como metafora literaria (un "
        "fantasma nunca confirmado, realismo magico suave) NO la saca de aqui "
        "si el peso esta en los personajes. La novela historica NO romantica "
        "(reconstruccion de una epoca, saga familiar, biografia novelada) es "
        "'Ficción general': 'Romance histórico' exige romance central (4e).\n"
        "7. Si de verdad NO tienes base, libreria='" + REVISAR + "'. No inventes.\n"
        + regla_serie + "\n"
        "FORMATO DE RESPUESTA: un array JSON, un objeto por libro y EN ORDEN, "
        "sin texto alrededor:\n"
        '[{"n": 1, "libreria": "<lista o (revisar)>", "confianza": <0.0-1.0>, '
        + campo_temas + campo_serie + '"motivo": "<breve>"}, ...]'
    )
    usuario = ("LIBROS:\n" + "\n\n".join(libros)
               + "\n\nDevuelve el array JSON, un objeto por libro y en el "
                 "mismo orden.")
    return sistema, usuario


def build_system_prompt(temas_vocab=None, librerias=None, pedir_serie=False):
    """Parte fija del prompt, lista para el mensaje `system`."""
    return SYSTEM + "\n\n" + _partes([], temas_vocab, librerias, pedir_serie)[0]


def build_user_prompt(items):
    """Parte variable: solo los libros del lote."""
    return _partes(items)[1]


def build_batch_prompt(items, temas_vocab=None, librerias=None, pedir_serie=False):
    """Prompt entero en un solo texto. Se conserva porque lo usan las pruebas y
    los scripts (`llm_rescue.py --dry-run`, `chat_lotes.py`), que quieren ver
    de una vez lo mismo que recibe el modelo."""
    sistema, usuario = _partes(items, temas_vocab, librerias, pedir_serie)
    return sistema + "\n" + usuario


class _RateLimited(RuntimeError):
    """429: limite de peticiones. Lleva los segundos sugeridos (Retry-After)."""
    def __init__(self, msg, retry_after=None):
        RuntimeError.__init__(self, msg)
        self.retry_after = retry_after


def _post_urllib(url, body, headers, timeout):
    req = _rq.Request(url, data=body, headers=headers)
    try:
        resp = _rq.urlopen(req, timeout=timeout)
        try:
            return json.loads(resp.read().decode("utf-8"))
        finally:
            resp.close()
    except _er.HTTPError as e:
        try:
            body_txt = e.read().decode("utf-8", "replace")[:500]
        except Exception:
            body_txt = ""
        if e.code == 429:
            ra = None
            try:
                ra = e.headers.get("Retry-After")
                ra = int(float(ra)) if ra is not None else None
            except Exception:
                ra = None
            raise _RateLimited("HTTP 429: %s" % body_txt, retry_after=ra)
        raise RuntimeError("HTTP %s: %s" % (e.code, body_txt))


def _http_post(url, payload, headers, timeout=90, retries=5):
    """POST JSON con urllib y reintento automatico:
      - 429 (limite de peticiones): espera PACIENTE y reintenta hasta `retries`
        veces, respetando la cabecera Retry-After si viene; si no, 10,20,30... s
        (tope 60). El tier gratis de GLM limita por minuto, asi que hay que
        esperar de verdad, no unos segundos.
      - timeout / fallo de red: reintenta con espera corta creciente.
    Solo urllib (el navegador de Calibre mandaba un content-type erroneo)."""
    body = json.dumps(payload).encode("utf-8")
    last = None
    for attempt in range(retries + 1):
        try:
            return _post_urllib(url, body, headers, timeout)
        except _RateLimited as e:
            last = e
            if attempt < retries:
                wait = e.retry_after if e.retry_after else min(60, 10 * (attempt + 1))
                time.sleep(wait)
                continue
            raise RuntimeError(str(e))
        except RuntimeError:
            raise                    # otro error HTTP con cuerpo -> arriba
        except Exception as e:       # timeout / conexion -> reintentar
            last = e
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            raise RuntimeError("red: %s" % e)
    raise RuntimeError("red: %s" % last)


# Consumo de la ULTIMA llamada: {'in', 'out', 'cache'}. `cache` son los tokens
# de entrada que el proveedor sirvio de su cache de prefijo en vez de cobrar
# enteros. Interesa porque la parte fija del prompt (reglas + mapa + temas) son
# unos 31.000 caracteres que se repiten en CADA lote: si `cache` es ~0 lote
# tras lote, se esta pagando entera cada vez y hay algo que la invalida.
ULTIMO_USO = {}


def _anotar_uso(usage, k_in, k_out, k_cache):
    """Guarda en ULTIMO_USO los tokens de la llamada. Nunca lanza: es telemetria."""
    ULTIMO_USO.clear()
    try:
        if not isinstance(usage, dict):
            return
        det = usage.get("prompt_tokens_details") or {}
        cache = usage.get(k_cache)
        if cache is None and isinstance(det, dict):
            cache = det.get("cached_tokens")
        ULTIMO_USO.update({
            "in": int(usage.get(k_in) or 0),
            "out": int(usage.get(k_out) or 0),
            "cache": int(cache or 0),
        })
    except Exception:
        ULTIMO_USO.clear()


def _call_openai(prompt, model, key, base, timeout=90, system=None):
    headers = {"content-type": "application/json"}
    if key:
        headers["authorization"] = "Bearer " + key
    data = _http_post(base.rstrip("/") + "/chat/completions",
                      {"model": model, "temperature": 0,
                       "messages": [{"role": "system",
                                     "content": system or SYSTEM},
                                    {"role": "user", "content": prompt}]},
                      headers, timeout=timeout)
    if "choices" not in data:
        raise RuntimeError("respuesta inesperada (sin 'choices'): %s"
                           % json.dumps(data)[:400])
    _anotar_uso(data.get("usage"), "prompt_tokens", "completion_tokens",
                "cached_tokens")
    return data["choices"][0]["message"]["content"]


def _call_anthropic(prompt, model, key, base, timeout=90, max_tokens=4096,
                    system=None):
    # `max_tokens` fijo en 4096 se quedaba corto con lotes grandes: cada libro
    # devuelve libreria, confianza, temas, serie y motivo (~200 tokens), asi
    # que a partir de unos 20 libros la respuesta se truncaba y solo se
    # salvaban los objetos completos. Lo escala `classify_batch`.
    # El bloque fijo va marcado con cache_control: aqui la cache NO es
    # automatica, hay que pedirla, y son ~8.000 tokens que se repiten en cada
    # lote de la tanda.
    data = _http_post(base.rstrip("/") + "/v1/messages",
                      {"model": model, "max_tokens": int(max_tokens),
                       "system": [{"type": "text", "text": system or SYSTEM,
                                   "cache_control": {"type": "ephemeral"}}],
                       "messages": [{"role": "user", "content": prompt}]},
                      {"content-type": "application/json", "x-api-key": key or "",
                       "anthropic-version": "2023-06-01"}, timeout=timeout)
    if "content" not in data:
        raise RuntimeError("respuesta inesperada: %s" % json.dumps(data)[:400])
    _anotar_uso(data.get("usage"), "input_tokens", "output_tokens",
                "cache_read_input_tokens")
    return data["content"][0]["text"]


def _dispatch(provider):
    try:
        kind, default_model, base = PROVIDERS[provider]
    except KeyError:
        raise RuntimeError(
            "Proveedor desconocido: %r. Elige uno de: %s -o 'otro' y escribe "
            "la URL del servidor en la configuracion-."
            % (provider, ", ".join(sorted(PROVIDERS))))
    fn = _call_anthropic if kind == "anthropic" else _call_openai
    return fn, default_model, base


def _salvage_objects(txt):
    """Rescata todos los objetos JSON completos {..} de un texto, ignorando uno
    final truncado. Sirve cuando el modelo corta la respuesta a medias."""
    dec = json.JSONDecoder()
    objs = []
    i, n = 0, len(txt)
    while i < n:
        j = txt.find("{", i)
        if j < 0:
            break
        try:
            obj, end = dec.raw_decode(txt, j)
            objs.append(obj)
            i = end
        except ValueError:
            i = j + 1
    return objs


def parse_array(txt):
    """Parsea el array JSON de la respuesta del modelo, tolerando fallos
    tipicos de los LLM: cercos de codigo, comas colgantes y respuestas
    truncadas (se rescatan los objetos completos)."""
    if not txt or not txt.strip():
        raise ValueError("respuesta vacia del modelo")
    t = txt.strip()
    # quitar cercos de codigo ```json ... ```
    if t.startswith("```"):
        t = t.strip("`")
        nl = t.find("\n")
        if nl != -1 and t[:nl].strip().lower() in ("json", ""):
            t = t[nl + 1:]
    s, e = t.find("["), t.rfind("]")
    frag = t[s:e + 1] if (s >= 0 and e > s) else (t[s:] if s >= 0 else t)
    # 1) tal cual
    try:
        return json.loads(frag)
    except Exception:
        pass
    # 2) quitar comas colgantes antes de } o ]
    import re as _re
    repaired = _re.sub(r",\s*([}\]])", r"\1", frag)
    try:
        return json.loads(repaired)
    except Exception:
        pass
    # 3) rescate: extraer objetos completos uno a uno (JSON truncado)
    objs = _salvage_objects(t)
    if objs:
        return objs
    raise ValueError("no se pudo parsear el JSON de la respuesta")


def _lib_key(v):
    """Clave de comparacion de un nombre de libreria: sin acentos, sin
    puntuacion (el '·' de 'Misterio·Thriller·Terror', guiones, barras) y con
    los espacios colapsados. Comparar con `.lower()` a secas descartaba en
    SILENCIO respuestas validas del modelo -'Ciencia Ficcion' sin tilde,
    'Misterio/Thriller/Terror', 'No Ficcion'- y el libro parecia no tener
    respuesta cuando en realidad la IA si habia contestado."""
    s = unicodedata.normalize("NFKD", str(v or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    return " ".join(s.lower().split())


def norm_libreria(v, librerias=None):
    """Devuelve la libreria del catalogo que corresponde a `v`, o REVISAR.

    Dos pasadas: coincidencia exacta de la clave normalizada y, si no, la
    libreria cuyo nombre aparezca COMO TAL dentro de la respuesta -y solo si
    es UNA: 'Romance' a secas sigue siendo REVISAR porque no distingue entre
    contemporaneo e historico, que es justo la duda que hay que marcar-.
    """
    librerias = librerias or LIBRERIAS
    k = _lib_key(v)
    if not k:
        return REVISAR
    for l in librerias:
        if k == _lib_key(l):
            return l
    if k in OBSOLETAS:
        return REVISAR
    if ALIAS.get(k) in librerias:
        return ALIAS[k]
    # El romance es el unico eje con dos estanterias que solo se distinguen por
    # la EPOCA, asi que se resuelve ANTES del reparto por nombre contenido: si
    # no, 'Romance contemporaneo o historico' -una duda explicita del modelo-
    # se quedaba con el contemporaneo solo porque el otro nombre no aparece
    # entero. El sabor comercial (suspense, thriller, comedia, dark) NO decide:
    # 'romantic suspense' a secas sigue siendo REVISAR, como 'Romance'.
    if _RX_ROMANCE.search(k) and not _RX_GANAN_AL_ROMANCE.search(k):
        hist = bool(_RX_EPOCA_HIST.search(k))
        cont = bool(_RX_EPOCA_CONT.search(k))
        if hist and cont:
            return REVISAR
        if hist or cont:
            elegida = "Romance histórico" if hist else "Romance contemporáneo"
            if elegida in librerias:
                return elegida
    dentro = [l for l in librerias
              if re.search(r"\b" + re.escape(_lib_key(l)) + r"\b", k)]
    if len(dentro) == 1:
        return dentro[0]
    return REVISAR


def norm_temas(v, vocab):
    """Devuelve los temas del vocabulario reconocidos en `v` (lista del LLM).

    Dos pasadas, como `norm_libreria`: clave normalizada del nombre completo
    (`_lib_key`: sin acentos, sin puntuacion, espacios colapsados) y, si no
    casa, la HOJA del nombre -lo que va tras el '\u00b7'- y solo si es UNA.

    Antes se comparaba con `.lower()` a secas contra el nombre exacto, asi que
    'Subgénero \u00b7 Fantasía urbana' -con las tildes que pone cualquier modelo
    que escriba bien espanol-, 'Subgenero: Fantasia urbana' o 'Fantasia
    urbana' a secas se descartaban EN SILENCIO: el libro parecia no tener
    temas cuando la IA si los habia dado.

    `vocab` admite lista de nombres o dict {nombre: descripcion}.
    """
    names = list(vocab.keys()) if isinstance(vocab, dict) else list(vocab or [])
    if not names or not isinstance(v, list):
        return []
    por_clave, por_hoja = {}, {}
    for t in names:
        por_clave.setdefault(_lib_key(t), t)
        hoja = t.split("\u00b7")[-1].strip()
        por_hoja.setdefault(_lib_key(hoja), []).append(t)
    out = []
    for x in v:
        k = _lib_key(x)
        if not k:
            continue
        t = por_clave.get(k)
        if t is None:
            cands = por_hoja.get(k) or []
            t = cands[0] if len(cands) == 1 else None
        if t is not None and t not in out:
            out.append(t)
    return out


def norm_serie(v):
    """Limpia el valor de serie: '' si el LLM no la sabe (null/none/vacio)."""
    v = ("" if v is None else str(v)).strip()
    if v.lower() in ("", "null", "none", "n/a", "na", "desconocida",
                     "desconocido", "(desconocido)", "-"):
        return ""
    return v[:200]


def classify_batch(items, provider, key, model=None, base=None,
                   temas_vocab=None, librerias=None, min_conf=0.55,
                   pedir_serie=False):
    """
    Clasifica UN lote de libros. Devuelve una lista alineada con `items`:
      [{libreria, confianza, temas, motivo}, ...]
    Lanza excepción si la llamada falla (el que llama decide qué hacer).
    """
    librerias = librerias or LIBRERIAS
    fn, default_model, default_base = _dispatch(provider)
    model, base = _resolver_modelo_y_base(provider, model, base,
                                          default_model, default_base)

    sistema, usuario = _partes(items, temas_vocab, librerias, pedir_serie)
    kw = {"system": SYSTEM + "\n\n" + sistema}
    if fn is _call_anthropic:
        # ~220 tokens por libro de respuesta, con suelo y techo. Los
        # proveedores con protocolo OpenAI usan su propio limite por defecto.
        kw["max_tokens"] = max(1024, min(8192, 220 * max(len(items), 1)))
    ULTIMO_USO.clear()
    arr = parse_array(fn(usuario, model, key, base, **kw))
    by_n = {}
    for i, o in enumerate(arr):
        try:
            by_n[int(o.get("n", i + 1))] = o
        except (ValueError, TypeError):
            by_n[i + 1] = o

    out = []
    for i in range(1, len(items) + 1):
        o = by_n.get(i, {})
        raw = o.get("libreria")
        lib = norm_libreria(raw, librerias)
        try:
            conf = float(o.get("confianza", 0.0))
        except (ValueError, TypeError):
            conf = 0.0
        # POR QUE queda sin resolver. Las cuatro causas piden acciones muy
        # distintas -bajar el umbral, arreglar el catalogo/prompt, aceptar la
        # duda o reintentar el lote-, asi que se distinguen en el informe en
        # vez de mezclarlas todas en un mismo "(revisar)".
        causa = ""
        if not o:
            causa = "sin_respuesta"      # el libro no vino en el array
        elif lib == REVISAR:
            if not str(raw or "").strip():
                causa = "sin_libreria"   # objeto sin el campo
            elif _lib_key(raw) == _lib_key(REVISAR):
                causa = "declarado"      # la IA dice que no tiene base
            else:
                causa = "nombre"         # nombre fuera del catalogo
        elif conf < min_conf:
            lib = REVISAR
            causa = "umbral"
        out.append({
            "libreria": lib,
            "libreria_raw": ("" if raw is None else str(raw))[:60],
            "causa": causa,
            "confianza": conf,
            "temas": norm_temas(o.get("temas"), temas_vocab),
            "serie": norm_serie(o.get("serie")) if pedir_serie else "",
            "motivo": o.get("motivo", ""),
        })
    return out


def _resolver_modelo_y_base(provider, model, base, default_model, default_base):
    """Modelo y URL definitivos, con el error explicado si falta alguno.

    Un modelo o una URL vacios acaban en un 404 o un 401 que no dice nada;
    mas vale decir exactamente que falta y donde se pone.
    """
    model = (model or "").strip() or default_model
    base = (base or "").strip() or default_base
    if not base:
        raise RuntimeError(
            "El proveedor %r no trae URL de servidor: escribela en Configurar "
            "plugin -> Rescate con IA -> 'URL del servidor' (p.ej. "
            "https://openrouter.ai/api/v1)." % provider)
    if not model:
        raise RuntimeError(
            "El proveedor %r no trae modelo por defecto (su catalogo cambia a "
            "menudo): escribe el nombre exacto del modelo en Configurar plugin "
            "-> Rescate con IA -> 'Modelo'." % provider)
    return model, base


def test_connection(provider, key, model=None, base=None):
    """Prueba una llamada mínima. Devuelve (ok, mensaje)."""
    try:
        fn, default_model, default_base = _dispatch(provider)
        model, base = _resolver_modelo_y_base(provider, model, base,
                                              default_model, default_base)
        txt = fn("Responde solo con el texto: OK", model, key, base, timeout=25)
        return True, (txt or "").strip()[:80]
    except Exception as e:
        return False, str(e)
