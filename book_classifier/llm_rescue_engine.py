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
import time

try:
    import urllib.request as _rq
    import urllib.error as _er
except ImportError:  # Python 2 (no debería, Calibre 5+ es py3)
    import urllib2 as _rq
    _er = _rq

# Librerías que puede asignar el LLM (9: Romantasy y Paranormal separadas,
# más No-Ficción). Deben ser las que quieres ver como "Biblioteca: ...".
LIBRERIAS = [
    "Romance contemporáneo",
    "Romance histórico",
    "Romantasy",
    "Paranormal",
    "Fantasía",
    "Ciencia Ficción",
    "Misterio·Thriller·Terror",
    "Ficción general",
    "No-Ficción",
]
REVISAR = "(revisar)"

SYSTEM = (
    "Eres un bibliotecario experto que clasifica libros en librerías temáticas "
    "y detecta sus tropos. Respondes SIEMPRE con un único array JSON válido, "
    "un objeto por libro y en el mismo orden, sin texto alrededor."
)

# proveedor -> (fn, cabecera_env_no_usada, modelo_por_defecto, base_url)
PROVIDERS = {
    "glm":       ("openai", "glm-4.5-flash",     "https://api.z.ai/api/paas/v4"),
    "deepseek":  ("openai", "deepseek-v4-flash", "https://api.deepseek.com/v1"),
    "openai":    ("openai", "gpt-4o-mini",       "https://api.openai.com/v1"),
    "google":    ("openai", "gemini-3.1-flash-lite",
                  "https://generativelanguage.googleapis.com/v1beta/openai"),
    "kimi":      ("openai", "kimi-k2.5",         "https://api.moonshot.ai/v1"),
    "qwen":      ("openai", "qwen-flash",
                  "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
    "local":     ("openai", "llama3.1",          "http://localhost:11434/v1"),
    "anthropic": ("anthropic", "claude-haiku-4-5", "https://api.anthropic.com"),
}


def build_batch_prompt(items, temas_vocab=None, librerias=None, pedir_serie=False):
    """items: [{titulo, autor, sinopsis, tags}] -> texto del prompt."""
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
        lista = "\n".join("  - " + t for t in temas_vocab)
        bloque_temas = ("\nTEMAS permitidos (elige 0 o más SOLO de esta lista, "
                        "textual):\n" + lista + "\n")
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
    return (
        "Clasifica CADA libro en UNA librería (excluyentes):\n" + opciones + "\n"
        + bloque_temas + "\n"
        "Reglas:\n"
        "0. ORDEN DE EVALUACION: mira PRIMERO si la relacion amorosa es un "
        "PILAR CENTRAL de la trama (regla 4) antes de mirar el escenario "
        "(reglas 3 y 5). Un reverse harem / harem inverso / 'why choose' "
        "SIEMPRE tiene romance central por definicion. Si hay romance "
        "central, aplica 4a-4d segun la ambientacion y NO uses 3e/3f para "
        "mandarlo a 'Ciencia Ficción' solo porque haya naves, alienigenas o "
        "un escenario espacial/futurista: el romance central manda sobre el "
        "escenario. Si NO hay romance central, sigue con las reglas 1, 2, 3, "
        "5, 6 y 7 en orden normal.\n"
        "1. NO clasifiques por el titulo solo: el titulo aislado NO basta (una "
        "misma palabra cabe en varios generos). Basate en la SINOPSIS, los TAGS y "
        "el autor. Puedes usar titulo+autor sin sinopsis SOLO si reconoces con "
        "certeza ese libro o esa saga concreta; si no lo reconoces y no hay "
        "sinopsis ni tags utiles, responde libreria='" + REVISAR + "' (no adivines "
        "por palabras del titulo).\n"
        "2. No-ficción, ensayo, biografía o divulgación → 'No-Ficción'.\n"
        "3. Fantasía vs Ciencia Ficción. Base: magia, mundos secundarios y "
        "criaturas vs tecnologia explicada, futuro y espacio. Para hibridos:\n"
        "   3a. Poderes innatos por sangre, linaje o mutacion SIN sistema magico "
        "explicito ni base tecnologica real (dones, castas con habilidades de "
        "nacimiento, mutantes tipo X-Men, p.ej. los Plata de Red Queen): eso NO "
        "es Ciencia Ficcion solo por sonar a 'poderes' o por ser un mundo "
        "distopico -la palabra 'distopia' sola NO determina el genero-; es "
        "'Fantasía', salvo que el poder se explique por ciencia real y explicita "
        "(experimentos, virus, ingenieria genetica, IA, naves, futuro "
        "tecnologico), en cuyo caso si es 'Ciencia Ficción'.\n"
        "   3b. Science fantasy (naves o alta tecnologia conviviendo con un "
        "poder mistico sin explicacion cientifica: ordenes de elegidos, "
        "profecias, 'energia' o 'fuerza' heredada, espadas de energia con aura "
        "magica, estilo Star Wars): decide por el MOTOR del conflicto central. "
        "Si lo que mueve la trama es el poder mistico/heredado/profetico \u2192 "
        "'Fantasía'; si son ideas o problemas tecnologicos plausibles \u2192 "
        "'Ciencia Ficción'. La sola presencia de naves o planetas NO convierte "
        "el libro en Ciencia Ficcion.\n"
        "   3c. Steampunk / retrofuturismo (vapor, engranajes, dirigibles, "
        "automatas, era victoriana alternativa): si ademas hay magia, criaturas "
        "u ocultismo que funcionan de verdad \u2192 'Fantasía'; si todo es "
        "tecnologia anacronica e inventos, sin magia real \u2192 'Ciencia Ficción'.\n"
        "   3d. Post-colapso: si tras la caida de la civilizacion la magia "
        "(re)aparece o la tecnologia antigua se trata como leyenda o religion "
        "sin explicacion \u2192 'Fantasía'; si es postapocaliptico puramente "
        "tecnologico o biologico (virus, ruinas, supervivencia, sin magia) \u2192 "
        "'Ciencia Ficción'.\n"
        "   3e. Espacio puro sin magia (space opera, naves, invasiones "
        "alienigenas, colonias, IA) y sin romance central \u2192 'Ciencia Ficción'.\n"
        "   3f. Poder de origen alienigena / otra especie: si el poder existe "
        "porque el personaje ES un alienigena, un hibrido o desciende de una "
        "especie extraterrestre (aunque la biologia de esa especie no se "
        "explique con detalle cientifico), NO apliques 3a: no es un linaje "
        "humano con dones sin explicar, es biologia de otra especie \u2192 "
        "'Ciencia Ficción'. Distingue: 3a = linaje o casta HUMANA con poderes "
        "que nadie explica (\u2192 Fantasía); 3f = el poder viene de SER de una "
        "especie alienigena (\u2192 Ciencia Ficción). EXCEPCION: si ese mundo "
        "ademas convive con un sistema de magia real que funciona (hechizos, "
        "criaturas magicas, poder mistico no biologico), gana el sistema "
        "magico \u2192 'Fantasía'.\n"
        "   Si la lista de TEMAS esta disponible, marca la sub-regla que "
        "aplicaste añadiendo el tema correspondiente: 3b \u2192 'Subgenero · "
        "Science fantasy'; 3c \u2192 'Subgenero · Steampunk'; 3d \u2192 'Subgenero · "
        "Postcolapso con magia'; 3f \u2192 'Subgenero · Poder alienigena'.\n"
        "4. Pregunta clave: la relacion amorosa, es un PILAR CENTRAL de la "
        "trama? NO basta con que haya romance o escenas picantes: el amor tiene "
        "que ser un hilo principal. Si NO lo es, gana el GENERO (reglas 3, 5 y "
        "6). Si SI lo es y ademas hay elemento fantastico, paranormal o sci-fi, "
        "decide entre 'Romantasy' y 'Paranormal' por la AMBIENTACION:\n"
        "   4a. 'Romantasy' = romance central + mundo INVENTADO por el autor, "
        "NO reconocible como el nuestro: reino o imperio magico, mundo "
        "secundario, corte de hadas, imperio espacial propio, colonia en otro "
        "planeta, distopia futura de nueva planta. Da igual que el motor del "
        "mundo sea magia o tecnologia: lo que importa es que el mundo NO es la "
        "Tierra reconocible.\n"
        "   4b. 'Paranormal' = romance central + Tierra actual o reconocible "
        "(una ciudad real, un pueblo normal, nuestra historia, o un futuro "
        "cercano que sigue siendo claramente nuestro mundo) con un elemento "
        "sobrenatural o alienigena INSERTADO en ella: vampiros en Nueva York, "
        "licantropos en un pueblo, un alien conviviendo con humanos (p.ej. la "
        "serie Lux de J.L. Armentrout / los Luxen), fantasmas, angeles, "
        "demonios.\n"
        "   4c. ESTO APLICA IGUAL EN AMBIENTACION HISTORICA: Londres "
        "victoriano/eduardiano, Persia antigua o regencia CON demonios, "
        "maldiciones, magia o cazadores sobrenaturales (p.ej. Shadowhunters) "
        "es Tierra reconocible del pasado \u2192 'Paranormal'. NO existe 'romance "
        "historico paranormal': si detectas algo sobrenatural en tu propio "
        "motivo, NO puede ser 'Romance histórico'. 'Romance histórico' es SOLO "
        "romance terrenal en epoca real pasada (intriga de corte, matrimonios "
        "concertados, guerra, sociedad de la epoca) SIN nada magico ni "
        "sobrenatural.\n"
        "   4d. Romance central SIN ningun elemento fantastico ni sobrenatural: "
        "en el presente \u2192 'Romance contemporáneo'; en epoca real pasada \u2192 "
        "'Romance histórico'.\n"
        "5. Magia + crimen/investigacion: distingue DONDE vive la magia.\n"
        "   5a. Si la magia, criaturas o poderes son el EJE DEL MUNDO (sociedad "
        "entera de magos, razas sobrenaturales organizadas, sistema de magia "
        "como worldbuilding), aunque la trama sea de investigacion, caza de "
        "monstruos, crimen o amenaza (fantasia urbana con detective "
        "sobrenatural, agentes, cazadores), NO uses "
        "'Misterio\u00b7Thriller\u00b7Terror': aplica las reglas 3 y 4 "
        "('Fantasía', 'Ciencia Ficción', 'Romantasy' o 'Paranormal' segun "
        "corresponda).\n"
        "   5b. Si lo sobrenatural es solo un RASGO PUNTUAL de la protagonista "
        "en un mundo por lo demas normal y el foco real es resolver un crimen "
        "(cozy mystery con bruja detective que regenta una tienda en un pueblo "
        "normal, medium que ayuda a la policia, fantasma testigo), SI es "
        "'Misterio\u00b7Thriller\u00b7Terror'. Prueba rapida: si quitando el "
        "toque magico la trama sigue siendo un misterio reconocible, es "
        "Misterio; si sin la magia el mundo entero se cae, aplica 5a.\n"
        "   5c. 'Misterio\u00b7Thriller\u00b7Terror' cubre ademas crimen "
        "realista, misterio policiaco, thriller de espias, terror psicologico "
        "y terror sobrenatural puntual (casa encantada, posesion) sin "
        "worldbuilding magico de fondo y sin romance central.\n"
        "6. 'Ficción general' es narrativa literaria SIN elementos de genero "
        "claros: sin magia como worldbuilding, sin crimen central, sin arco "
        "romantico central, sin ciencia ficcion (drama contemporaneo, "
        "literatura, autoficcion...). Un toque especulativo leve usado solo "
        "como metafora literaria (un posible fantasma nunca confirmado, "
        "realismo magico suave) NO saca el libro de 'Ficción general' si el "
        "peso esta en los personajes y no en el elemento fantastico.\n"
        "7. Si de verdad NO tienes base, libreria='" + REVISAR + "'. No inventes.\n"
        + regla_serie + "\n"
        "LIBROS:\n" + "\n\n".join(libros) + "\n\n"
        "Devuelve un array JSON, un objeto por libro EN ORDEN:\n"
        '[{"n": 1, "libreria": "<lista o (revisar)>", "confianza": <0.0-1.0>, '
        + campo_temas + campo_serie + '"motivo": "<breve>"}, ...]'
    )


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


def _call_openai(prompt, model, key, base, timeout=90):
    headers = {"content-type": "application/json"}
    if key:
        headers["authorization"] = "Bearer " + key
    data = _http_post(base.rstrip("/") + "/chat/completions",
                      {"model": model, "temperature": 0,
                       "messages": [{"role": "system", "content": SYSTEM},
                                    {"role": "user", "content": prompt}]},
                      headers, timeout=timeout)
    if "choices" not in data:
        raise RuntimeError("respuesta inesperada (sin 'choices'): %s"
                           % json.dumps(data)[:400])
    return data["choices"][0]["message"]["content"]


def _call_anthropic(prompt, model, key, base, timeout=90):
    data = _http_post(base.rstrip("/") + "/v1/messages",
                      {"model": model, "max_tokens": 4096, "system": SYSTEM,
                       "messages": [{"role": "user", "content": prompt}]},
                      {"content-type": "application/json", "x-api-key": key or "",
                       "anthropic-version": "2023-06-01"}, timeout=timeout)
    if "content" not in data:
        raise RuntimeError("respuesta inesperada: %s" % json.dumps(data)[:400])
    return data["content"][0]["text"]


def _dispatch(provider):
    kind, default_model, base = PROVIDERS[provider]
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


def norm_libreria(v, librerias=None):
    librerias = librerias or LIBRERIAS
    v = (v or "").strip()
    for l in librerias:
        if v.lower() == l.lower():
            return l
    return REVISAR


def norm_temas(v, vocab):
    if not vocab or not isinstance(v, list):
        return []
    vl = {t.lower(): t for t in vocab}
    return [vl[str(x).strip().lower()] for x in v
            if str(x).strip().lower() in vl]


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
    model = model or default_model
    base = base or default_base

    prompt = build_batch_prompt(items, temas_vocab, librerias, pedir_serie)
    arr = parse_array(fn(prompt, model, key, base))
    by_n = {}
    for i, o in enumerate(arr):
        try:
            by_n[int(o.get("n", i + 1))] = o
        except (ValueError, TypeError):
            by_n[i + 1] = o

    out = []
    for i in range(1, len(items) + 1):
        o = by_n.get(i, {})
        lib = norm_libreria(o.get("libreria"), librerias)
        try:
            conf = float(o.get("confianza", 0.0))
        except (ValueError, TypeError):
            conf = 0.0
        if conf < min_conf:
            lib = REVISAR
        out.append({
            "libreria": lib,
            "confianza": conf,
            "temas": norm_temas(o.get("temas"), temas_vocab),
            "serie": norm_serie(o.get("serie")) if pedir_serie else "",
            "motivo": o.get("motivo", ""),
        })
    return out


def test_connection(provider, key, model=None, base=None):
    """Prueba una llamada mínima. Devuelve (ok, mensaje)."""
    try:
        fn, default_model, default_base = _dispatch(provider)
        txt = fn("Responde solo con el texto: OK",
                 model or default_model, key, base or default_base, timeout=25)
        return True, (txt or "").strip()[:80]
    except Exception as e:
        return False, str(e)
