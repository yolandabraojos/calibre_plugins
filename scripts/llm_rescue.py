# -*- coding: utf-8 -*-
"""
llm_rescue.py — Capa de rescate LLM para Book Classifier (modelo híbrido)  v2
============================================================================

Coge SOLO los libros que el clasificador local dejó sin biblioteca firme
("Por revisar" + "Sin datos") y los manda a un LLM para decidir:
  • EJE 1 — librería (una de la lista, o (revisar))
  • EJE 2 — temas/tropos (multi-etiqueta, elegidos de tu vocabulario)

Novedades v2:
  • Fantasía y Ciencia Ficción separadas (antes iban unidas).
  • No-Ficción como librería propia (ensayo, biografía, divulgación).
  • BATCHING: varios libros por llamada → coste por libro mucho menor.
  • TEMAS opcionales, restringidos al vocabulario de mood_rules.json.
  • Proveedores: anthropic, openai, deepseek, qwen y local (Ollama).
    Todos menos anthropic hablan el protocolo OpenAI (mismo adaptador).

Uso:
  export DEEPSEEK_API_KEY=sk-...
  python3 llm_rescue.py --in clasificacion_resultado.csv --out rescatados.csv \
      --provider deepseek --temas-file mood_rules.json --batch 20 --limit 200

Requisitos: solo librería estándar (urllib). Sin pip install.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, os, re, sys, time, unicodedata
import urllib.request, urllib.error

# ─── Catalogo y prompt: se importan del PLUGIN, que es la fuente de verdad ────
# Antes estaban duplicados aqui a mano y se desincronizaban en cada cambio de
# estanterias (paso de verdad: este script siguio ofreciendo el catalogo viejo
# despues de trocear 'Misterio·Thriller·Terror'). El motor del plugin no
# depende de calibre -solo urllib-, asi que se puede cargar por ruta desde
# este script suelto y compartir LIBRERIAS, el prompt y los normalizadores.
def _cargar_motor():
    import importlib.util
    ruta = os.path.abspath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), os.pardir,
        'book_classifier', 'llm_rescue_engine.py'))
    if not os.path.exists(ruta):
        sys.exit('No encuentro el motor del plugin en:\n  {}\n'
                 'Este script comparte con el el catalogo de librerias y el '
                 'prompt, asi que necesita el repositorio completo.'.format(ruta))
    spec = importlib.util.spec_from_file_location('llm_rescue_engine', ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_ENG = _cargar_motor()

LIBRERIAS = _ENG.LIBRERIAS
REVISAR = _ENG.REVISAR
SYSTEM = _ENG.SYSTEM
build_batch_prompt = _ENG.build_batch_prompt   # (items, temas_vocab)
norm_libreria = _ENG.norm_libreria             # (v[, librerias])
norm_temas = _ENG.norm_temas                   # (v, vocab)

# ─── Adaptadores de API (urllib, sin dependencias) ────────────────────────────
def _http_post(url, payload, headers):
    """POST JSON y devuelve el dict de respuesta. Si la API devuelve error HTTP,
    lo relanza con el cuerpo real del mensaje (no solo el codigo)."""
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"HTTP {e.code}: {body}")

def call_anthropic(prompt, model, key, base):
    data = _http_post("https://api.anthropic.com/v1/messages",
        {"model": model, "max_tokens": 2000, "system": SYSTEM,
         "messages": [{"role": "user", "content": prompt}]},
        {"content-type": "application/json", "x-api-key": key,
         "anthropic-version": "2023-06-01"})
    if "content" not in data:
        raise RuntimeError(f"respuesta inesperada: {json.dumps(data)[:400]}")
    return data["content"][0]["text"]

def call_openai_compat(prompt, model, key, base):
    """Vale para OpenAI, DeepSeek, Qwen, GLM/z.ai y Ollama local (mismo protocolo)."""
    headers = {"content-type": "application/json"}
    if key:  # Ollama local no necesita clave
        headers["authorization"] = f"Bearer {key}"
    data = _http_post(base.rstrip("/") + "/chat/completions",
        {"model": model, "temperature": 0,
         "messages": [{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": prompt}]},
        headers)
    if "choices" not in data:
        raise RuntimeError(f"respuesta inesperada (sin 'choices'): {json.dumps(data)[:400]}")
    return data["choices"][0]["message"]["content"]

PROVIDERS = {
    # nombre:      (fn,               env,               modelo,             base_url)
    "anthropic": (call_anthropic,    "ANTHROPIC_API_KEY", "claude-haiku-4-5", None),
    "openai":    (call_openai_compat,"OPENAI_API_KEY",    "gpt-4o-mini",      "https://api.openai.com/v1"),
    "deepseek":  (call_openai_compat,"DEEPSEEK_API_KEY",  "deepseek-v4-flash","https://api.deepseek.com/v1"),
    "qwen":      (call_openai_compat,"DASHSCOPE_API_KEY", "qwen-flash",       "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
    "google":    (call_openai_compat,"GEMINI_API_KEY",    "gemini-3.1-flash-lite","https://generativelanguage.googleapis.com/v1beta/openai"),
    "kimi":      (call_openai_compat,"MOONSHOT_API_KEY",  "kimi-k2.5",        "https://api.moonshot.ai/v1"),
    "glm":       (call_openai_compat,"ZAI_API_KEY",       "glm-4.5-flash",    "https://api.z.ai/api/paas/v4"),
    "local":     (call_openai_compat, None,               "llama3.1",         "http://localhost:11434/v1"),
}

def parse_array(txt):
    s, e = txt.find("["), txt.rfind("]")
    return json.loads(txt[s:e + 1])

def key_for(row):
    h = hashlib.sha1((row["Titulo"] + "|" + row["Autor"]).encode("utf-8")).hexdigest()
    return h[:16]

def load_json(path):
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f: return json.load(f)
    return None

def save_cache(path, cache):
    if path:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp")
    ap.add_argument("--out", dest="out")
    ap.add_argument("--provider", choices=PROVIDERS, default="deepseek")
    ap.add_argument("--model", default=None)
    ap.add_argument("--base-url", default=None, help="sobreescribe la URL del proveedor")
    ap.add_argument("--temas-file", default=None, help="mood_rules.json para el vocabulario de temas")
    ap.add_argument("--batch", type=int, default=20, help="libros por llamada")
    ap.add_argument("--cache", default="llm_cache.json")
    ap.add_argument("--limit", type=int, default=0, help="0 = sin límite")
    ap.add_argument("--min-conf", type=float, default=0.55)
    ap.add_argument("--estados", default="Por revisar,Sin datos")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--diag", action="store_true", help="prueba una sola llamada y muestra la respuesta cruda")
    args = ap.parse_args()

    call, env, default_model, default_base = PROVIDERS[args.provider]
    model = args.model or default_model
    base  = args.base_url or default_base
    estados = {e.strip() for e in args.estados.split(",")}
    crudo = (load_json(args.temas_file) or {}) if args.temas_file else {}
    # Valor = regex (formato antiguo) u objeto {"regex", "desc"} (3.10.0).
    temas_vocab = {n: ((r.get("desc") or "") if isinstance(r, dict) else "")
                   for n, r in crudo.items()}
    key = os.environ.get(env) if env else None

    if args.diag:
        print(f"Diagnóstico: proveedor={args.provider} modelo={model} base={base}")
        print(f"Clave detectada: {'sí' if key else 'NO (variable ' + str(env) + ' vacía)'}")
        try:
            txt = call('Responde solo con el texto: OK', model, key, base)
            print("Respuesta del modelo:", repr(txt)[:300])
            print("\n>>> La conexión funciona.")
        except Exception as e:
            print("\n>>> FALLO:", e)
        return

    if not args.inp or not args.out:
        sys.exit("Faltan --in y --out (o usa --diag para probar la conexión).")


    with open(args.inp, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    targets = [r for r in rows if r.get("Estado") in estados]
    if args.limit:
        targets = targets[:args.limit]
    print(f"A rescatar: {len(targets)} de {len(rows)} | proveedor={args.provider} "
          f"modelo={model} batch={args.batch} temas={'sí' if temas_vocab else 'no'}")

    def to_item(r):
        return {"titulo": r["Titulo"], "autor": r["Autor"],
                "sinopsis": r.get("Sinopsis", ""), "tags": r.get("Tags_antojo", "")}

    if args.dry_run:
        print("\n----- PROMPT de ejemplo (primer lote) -----\n")
        print(build_batch_prompt([to_item(r) for r in targets[:args.batch]], temas_vocab))
        print("\n(dry-run: no se llamó a la API)")
        return

    if env and not key:
        sys.exit(f"Falta la variable de entorno {env} con tu clave de API.")

    cache = load_json(args.cache) or {}
    out_rows, new_calls, from_cache, errors = [], 0, 0, 0

    # separa lo cacheado de lo pendiente
    pending = []
    for r in targets:
        k = key_for(r)
        if k in cache:
            from_cache += 1
        else:
            pending.append(r)

    # procesa lo pendiente en lotes
    for b in range(0, len(pending), args.batch):
        lote = pending[b:b + args.batch]
        prompt = build_batch_prompt([to_item(r) for r in lote], temas_vocab)
        try:
            arr = parse_array(call(prompt, model, key, base))
            by_n = {int(o.get("n", i + 1)): o for i, o in enumerate(arr)}
            for i, r in enumerate(lote, 1):
                o = by_n.get(i, {})
                res = {"libreria": norm_libreria(o.get("libreria")),
                       "confianza": o.get("confianza", 0.0),
                       "temas": norm_temas(o.get("temas"), temas_vocab),
                       "motivo": o.get("motivo", "")}
                if float(res["confianza"] or 0) < args.min_conf:
                    res["libreria"] = REVISAR
                cache[key_for(r)] = res
        except (urllib.error.URLError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as e:
            if errors == 0:
                print(f"\n[!] Primer error de la API: {e}\n")
            # NO cacheamos los errores: así se reintentan en la próxima ejecución
            errors += len(lote)
        new_calls += 1
        if new_calls % 10 == 0:
            save_cache(args.cache, cache)
            print(f"  … {new_calls} llamadas ({b + len(lote)}/{len(pending)} libros)")
        time.sleep(0.2)

    save_cache(args.cache, cache)

    # construye salida
    for r in targets:
        res = cache.get(key_for(r), {})
        out = dict(r)
        out["LLM_libreria"]  = res.get("libreria", REVISAR)
        out["LLM_confianza"] = res.get("confianza", "")
        out["LLM_temas"]     = "; ".join(res.get("temas", []))
        out["LLM_motivo"]    = res.get("motivo", "")
        out_rows.append(out)

    with open(args.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader(); w.writerows(out_rows)

    asign = sum(1 for o in out_rows if o["LLM_libreria"] != REVISAR)
    print(f"\nHecho. {len(out_rows)} libros → {asign} con biblioteca "
          f"({asign/max(len(out_rows),1)*100:.0f}%), {len(out_rows)-asign} en (revisar).")
    print(f"Llamadas nuevas: {new_calls} | de caché: {from_cache} libros | errores: {errors}")
    print(f"Resultado: {args.out}")

if __name__ == "__main__":
    main()
