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
import argparse, csv, hashlib, json, os, sys, time, urllib.request, urllib.error

# ─── Tus librerías (deben coincidir EXACTAMENTE con las del plugin) ────────────
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

def build_batch_prompt(items, temas_vocab):
    """items: lista de dicts {titulo, autor, sinopsis, tags}. Devuelve el prompt."""
    opciones = "\n".join(f"  - {l}" for l in LIBRERIAS)
    bloque_temas = ""
    campo_temas = ""
    if temas_vocab:
        lista = "\n".join(f"  - {t}" for t in temas_vocab)
        bloque_temas = (
            "\nTEMAS permitidos (elige 0 o más SOLO de esta lista, textual):\n"
            f"{lista}\n"
        )
        campo_temas = '"temas": [<0+ temas de la lista>], '
    libros = []
    for i, it in enumerate(items, 1):
        partes = [f"[{i}] Título: {it['titulo']}",
                  f"    Autor: {it['autor'] or '(desconocido)'}"]
        if it.get('sinopsis'): partes.append(f"    Sinopsis: {it['sinopsis'][:1200]}")
        if it.get('tags'):     partes.append(f"    Tags: {it['tags']}")
        libros.append("\n".join(partes))
    return (
        "Clasifica CADA libro en UNA librería (excluyentes):\n"
        f"{opciones}\n"
        f"{bloque_temas}\n"
        "Reglas:\n"
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
        "7. Si de verdad NO tienes base, libreria='" + REVISAR + "'. No inventes.\n\n"
        "LIBROS:\n" + "\n\n".join(libros) + "\n\n"
        "Devuelve un array JSON, un objeto por libro EN ORDEN:\n"
        '[{"n": 1, "libreria": "<lista o (revisar)>", "confianza": <0.0-1.0>, '
        + campo_temas + '"motivo": "<breve>"}, ...]'
    )

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

def norm_libreria(v):
    v = (v or "").strip()
    for l in LIBRERIAS:
        if v.lower() == l.lower():
            return l
    return REVISAR

def norm_temas(v, vocab):
    if not vocab or not isinstance(v, list): return []
    vl = {t.lower(): t for t in vocab}
    return [vl[str(x).strip().lower()] for x in v if str(x).strip().lower() in vl]

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
    temas_vocab = list((load_json(args.temas_file) or {}).keys()) if args.temas_file else []
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
