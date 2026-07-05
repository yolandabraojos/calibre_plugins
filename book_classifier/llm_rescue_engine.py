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

try:
    import urllib.request as _rq
    import urllib.error as _er
except ImportError:  # Python 2 (no debería, Calibre 5+ es py3)
    import urllib2 as _rq
    _er = _rq

# Librerías que puede asignar el LLM (8: Fantasía y Ciencia Ficción separadas,
# más No-Ficción). Deben ser las que quieres ver como "Biblioteca: ...".
LIBRERIAS = [
    "Romance contemporáneo",
    "Romance histórico",
    "Romantasy / Paranormal",
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


def build_batch_prompt(items, temas_vocab=None, librerias=None):
    """items: [{titulo, autor, sinopsis, tags}] -> texto del prompt."""
    librerias = librerias or LIBRERIAS
    opciones = "\n".join("  - " + l for l in librerias)
    bloque_temas = ""
    campo_temas = ""
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
        "1. Si conoces el libro por título+autor, úsalo aunque falte sinopsis.\n"
        "2. No-ficción, ensayo, biografía o divulgación → 'No-Ficción'.\n"
        "3. Fantasía y Ciencia Ficción son distintas: magia/mundos secundarios "
        "vs tecnología/futuro/espacio. Si mezcla romance central + "
        "fantasía/paranormal, usa 'Romantasy / Paranormal'.\n"
        "4. Si de verdad NO tienes base, libreria='" + REVISAR + "'. No inventes.\n\n"
        "LIBROS:\n" + "\n\n".join(libros) + "\n\n"
        "Devuelve un array JSON, un objeto por libro EN ORDEN:\n"
        '[{"n": 1, "libreria": "<lista o (revisar)>", "confianza": <0.0-1.0>, '
        + campo_temas + '"motivo": "<breve>"}, ...]'
    )


def _http_post(url, payload, headers, timeout=120):
    req = _rq.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
    try:
        resp = _rq.urlopen(req, timeout=timeout)
        try:
            return json.loads(resp.read().decode("utf-8"))
        finally:
            resp.close()
    except _er.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")[:500]
        except Exception:
            body = ""
        raise RuntimeError("HTTP %s: %s" % (e.code, body))


def _call_openai(prompt, model, key, base):
    headers = {"content-type": "application/json"}
    if key:
        headers["authorization"] = "Bearer " + key
    data = _http_post(base.rstrip("/") + "/chat/completions",
                      {"model": model, "temperature": 0,
                       "messages": [{"role": "system", "content": SYSTEM},
                                    {"role": "user", "content": prompt}]},
                      headers)
    if "choices" not in data:
        raise RuntimeError("respuesta inesperada (sin 'choices'): %s"
                           % json.dumps(data)[:400])
    return data["choices"][0]["message"]["content"]


def _call_anthropic(prompt, model, key, base):
    data = _http_post(base.rstrip("/") + "/v1/messages",
                      {"model": model, "max_tokens": 2000, "system": SYSTEM,
                       "messages": [{"role": "user", "content": prompt}]},
                      {"content-type": "application/json", "x-api-key": key or "",
                       "anthropic-version": "2023-06-01"})
    if "content" not in data:
        raise RuntimeError("respuesta inesperada: %s" % json.dumps(data)[:400])
    return data["content"][0]["text"]


def _dispatch(provider):
    kind, default_model, base = PROVIDERS[provider]
    fn = _call_anthropic if kind == "anthropic" else _call_openai
    return fn, default_model, base


def parse_array(txt):
    s, e = txt.find("["), txt.rfind("]")
    if s < 0 or e < 0:
        raise ValueError("no se encontró un array JSON en la respuesta")
    return json.loads(txt[s:e + 1])


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


def classify_batch(items, provider, key, model=None, base=None,
                   temas_vocab=None, librerias=None, min_conf=0.55):
    """
    Clasifica UN lote de libros. Devuelve una lista alineada con `items`:
      [{libreria, confianza, temas, motivo}, ...]
    Lanza excepción si la llamada falla (el que llama decide qué hacer).
    """
    librerias = librerias or LIBRERIAS
    fn, default_model, default_base = _dispatch(provider)
    model = model or default_model
    base = base or default_base

    prompt = build_batch_prompt(items, temas_vocab, librerias)
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
            "motivo": o.get("motivo", ""),
        })
    return out


def test_connection(provider, key, model=None, base=None):
    """Prueba una llamada mínima. Devuelve (ok, mensaje)."""
    try:
        fn, default_model, default_base = _dispatch(provider)
        txt = fn("Responde solo con el texto: OK",
                 model or default_model, key, base or default_base)
        return True, (txt or "").strip()[:80]
    except Exception as e:
        return False, str(e)
