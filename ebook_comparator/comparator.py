import logging
import math
import hashlib
from difflib import SequenceMatcher
from collections import Counter

logger = logging.getLogger('ebook_comparator.comparator')

# --- UTILIDADES DE HASHING ---

def get_text_hash(text):
    """Hash MD5 para detectar si el contenido es 100% idéntico."""
    return hashlib.md5(text.encode('utf-8')).hexdigest()


def book_fingerprint(chapters):
    """
    Huella de libro independiente del orden: MD5 del conjunto ORDENADO de
    hashes de capítulo.  Dos libros con exactamente los mismos capítulos
    (tras normalización y eliminación de jackets) comparten huella, aunque
    el orden de los ficheros internos difiera.

    Permite agrupar copias "idénticas salvo jackets" en O(libros) comparando
    una sola cadena por libro, en lugar de comparar capítulo a capítulo cada
    par.  Devuelve None si el libro no tiene capítulos procesables.
    """
    if not chapters:
        return None
    hashes = sorted(get_text_hash(t) for t in chapters.values())
    return hashlib.md5('|'.join(hashes).encode('utf-8')).hexdigest()


def get_simhash(text, hash_size=64):
    """
    Genera una huella digital (SimHash) de 64 bits.

    Optimización vs. la versión previa:
      - Se agrupan los tokens con Counter, de modo que cada palabra ÚNICA se
        hashea una sola vez (ponderada por su frecuencia).  En textos reales,
        con mucha repetición de palabras, esto reduce drásticamente el número
        de hashes y de iteraciones de bits.
      - Se usa blake2b(digest_size=8) en lugar de md5().hexdigest()+int(...,16):
        produce directamente 64 bits sin convertir una cadena hex de 128 bits.
    """
    counts = Counter(text.split())
    if not counts:
        return 0

    v = [0] * hash_size
    for word, c in counts.items():
        h = int.from_bytes(
            hashlib.blake2b(word.encode('utf-8'), digest_size=8).digest(),
            'little',
        )
        for i in range(hash_size):
            if (h >> i) & 1:
                v[i] += c
            else:
                v[i] -= c

    ans = 0
    for i in range(hash_size):
        if v[i] >= 0:
            ans |= (1 << i)
    return ans


def hamming_distance(h1, h2):
    """Calcula cuántos bits son diferentes entre dos SimHashes."""
    x = h1 ^ h2
    try:
        return x.bit_count()          # Python 3.10+ (Calibre 6+)
    except AttributeError:
        dist = 0
        while x:
            dist += 1
            x &= x - 1
        return dist

# --- MÉTODOS TRADICIONALES (Para precisión y modo manual) ---

def _tokenize(text):
    return text.split()

def prepare_tfidf_data(chapters_a, chapters_b):
    all_docs_tokens = (
        [_tokenize(t) for t in chapters_a.values()] +
        [_tokenize(t) for t in chapters_b.values()]
    )
    all_docs_sets = [set(tokens) for tokens in all_docs_tokens]
    vocab = set()
    for s in all_docs_sets:
        vocab.update(s)
    num_docs = len(all_docs_sets)
    idf_map = {}
    for word in vocab:
        containing = sum(1 for s in all_docs_sets if word in s)
        idf_map[word] = math.log((num_docs + 1) / (containing + 1)) + 1
    return idf_map, vocab

def get_vector(text, idf_map, vocab):
    tokens = _tokenize(text)
    counts = Counter(tokens)
    total = len(tokens) or 1
    return {w: (counts[w] / total) * idf_map[w] for w in counts if w in idf_map}

def cosine_similarity(va, vb):
    if len(va) > len(vb):
        va, vb = vb, va
    dot = sum(va[w] * vb.get(w, 0) for w in va)
    na = math.sqrt(sum(v ** 2 for v in va.values()))
    nb = math.sqrt(sum(v ** 2 for v in vb.values()))
    return dot / (na * nb) if na and nb else 0.0


def _length_penalty(text_a, text_b):
    """
    Penalización por diferencia de longitud entre dos textos.

    TF-IDF coseno y SimHash miden similitud de vocabulario, no cobertura:
    si A tiene 200 palabras y B tiene 1000, y esas 200 son un subconjunto
    casi perfecto de las 1000, el coseno da ~1.0 aunque A solo cubre el 20%
    del contenido de B.

    Este factor escala el score proporcionalmente al ratio de longitud,
    usando la media armónica para ser simétrico (no importa cuál es A y
    cuál es B) y para penalizar más los casos extremos que la media simple.

    Ejemplos:
      len_a=1000, len_b=1000  -> ratio=1.0  -> penalty=1.0  (sin penalización)
      len_a=200,  len_b=1000  -> ratio=0.2  -> harmonic=0.33 -> penalty~0.58
      len_a=100,  len_b=1000  -> ratio=0.1  -> harmonic=0.18 -> penalty~0.43
    """
    len_a = len(text_a.split())
    len_b = len(text_b.split())
    if len_a == 0 or len_b == 0:
        return 0.0
    ratio = min(len_a, len_b) / max(len_a, len_b)
    # Media armónica del ratio y 1.0: suaviza la penalización para
    # diferencias moderadas pero es contundente en diferencias extremas.
    harmonic = 2 * ratio / (ratio + 1.0)
    return math.sqrt(harmonic)   # raíz cuadrada para no ser demasiado agresivo


# Umbral de prefiltro de longitud global del libro.  Si el libro más corto
# tiene menos de este ratio de palabras respecto al más largo, los libros son
# tan dispares en tamaño que no merece la pena construir la matriz capítulo a
# capítulo: se devuelve un resultado disjunto de baja similitud directamente.
PREFILTER_LENGTH_RATIO = 0.15


def _total_words(chapters):
    return sum(len(t.split()) for t in chapters.values())


def _build_disjoint_result(chapters_a, chapters_b, method):
    """
    Resultado para pares descartados por el prefiltro de longitud: ningún
    capítulo se considera emparejado.  Mantiene exactamente el mismo contrato
    (chapter_map, unique_to_a/b, global_similarity) que _build_result_map para
    que la UI lo muestre sin cambios.
    """
    chapter_map = []
    for name_a in chapters_a:
        chapter_map.append({
            'chapter_a':    name_a,
            'best_match_b': None,
            'similarity':   0.0,
            'is_unique':    True,
        })
    for name_b in chapters_b:
        chapter_map.append({
            'chapter_a':    None,
            'best_match_b': name_b,
            'similarity':   0.0,
            'is_unique':    True,
        })
    return {
        'global_similarity': 0.0,
        'method':            method,
        'chapter_map':       chapter_map,
        'unique_to_a':       list(chapters_a.keys()),
        'unique_to_b':       list(chapters_b.keys()),
        'score_matrix':      {},
    }


# Caracteres totales muestreados para SequenceMatcher.  En lugar de tomar solo
# el principio del capítulo (que ignora diferencias en mitad/final, p. ej. un
# epílogo añadido o un final alternativo), se reparte el presupuesto entre el
# INICIO y el FINAL del texto.  Así se detectan divergencias tardías sin pagar
# el coste O(n*m) de comparar el capítulo completo.
SEQ_SAMPLE_CHARS = 6000


def _sample_head_tail(text, total=SEQ_SAMPLE_CHARS):
    """
    Devuelve una muestra del texto formada por su mitad inicial y su mitad
    final.  Si el texto cabe entero en el presupuesto, se devuelve tal cual.
    """
    if len(text) <= total:
        return text
    half = total // 2
    return text[:half] + text[-half:]


# --- FUNCIÓN PRINCIPAL ---

def compare_books_ultrafast(chapters_a, chapters_b):
    """
    Modo ultrarrápido: detecta únicamente pares con similitud del 100%.

    Detiene la comparación en cuanto determina que el resultado será
    inferior al 100% y devuelve None (par descartado silenciosamente).
    Solo devuelve un dict de resultado cuando los dos libros son idénticos
    capítulo a capítulo (coincidencia exacta por MD5 para cada capítulo).

    Condiciones de descarte inmediato (early-exit):
      1. Número de capítulos diferente -> los libros no pueden ser idénticos.
      2. Algún capítulo de A no tiene una pareja exacta (por MD5) en B.

    Retorno:
      dict  -> similitud 100 %, con chapter_map completo.
      None  -> similitud < 100 %, par descartado.
    """
    total_a = len(chapters_a)
    total_b = len(chapters_b)

    # Sin capítulos procesables en ambos libros: no hay nada que comparar
    if total_a == 0 and total_b == 0:
        return None

    # Número diferente de capítulos -> imposible obtener 100 %
    if total_a != total_b:
        return None

    names_b  = list(chapters_b.keys())
    hashes_b = [get_text_hash(t) for t in chapters_b.values()]

    chapter_map = []
    matched_b   = set()  # índices de capítulos de B ya emparejados

    for name_a, text_a in chapters_a.items():
        h_a   = get_text_hash(text_a)
        found = False
        for idx, h_b in enumerate(hashes_b):
            if idx not in matched_b and h_a == h_b:
                matched_b.add(idx)
                chapter_map.append({
                    'chapter_a':    name_a,
                    'best_match_b': names_b[idx],
                    'similarity':   100.0,
                    'is_unique':    False,
                })
                found = True
                break
        if not found:
            return None  # early-exit: este capítulo no tiene pareja exacta

    # total_a == total_b y todos los A emparejados -> todos los B también emparejados
    return {
        'global_similarity': 100.0,
        'method':            'ultrafast',
        'chapter_map':       chapter_map,
        'unique_to_a':       [],
        'unique_to_b':       [],
    }


def compare_books(chapters_a, chapters_b, method='combined', progress_cb=None):
    total_a = len(chapters_a)
    total_b = len(chapters_b)

    if total_a == 0 or total_b == 0:
        return {'global_similarity': 0.0, 'chapter_map': [],
                'unique_to_a': list(chapters_a.keys()), 'unique_to_b': list(chapters_b.keys())}

    # 0. PREFILTRO POR LONGITUD GLOBAL
    # Si los dos libros difieren enormemente en número total de palabras,
    # no pueden ser el mismo libro (ni una versión con jackets distintos):
    # evitamos construir la matriz O(total_a x total_b) y devolvemos un
    # resultado disjunto de baja similitud.  Solo se aplica cuando ambos
    # libros tienen contenido suficiente para que el ratio sea fiable.
    words_a = _total_words(chapters_a)
    words_b = _total_words(chapters_b)
    if words_a > 0 and words_b > 0:
        ratio = min(words_a, words_b) / max(words_a, words_b)
        if ratio < PREFILTER_LENGTH_RATIO:
            logger.debug('Prefiltro longitud: ratio=%.3f -> par descartado', ratio)
            if progress_cb:
                progress_cb(100)
            return _build_disjoint_result(chapters_a, chapters_b, method)

    # 1. PREPARACIÓN DE HASHES
    # Generar SimHash es órdenes de magnitud más rápido que TF-IDF
    simhashes_a = {n: get_simhash(t) for n, t in chapters_a.items()}
    simhashes_b = {n: get_simhash(t) for n, t in chapters_b.items()}
    md5_hashes_b = {n: get_text_hash(t) for n, t in chapters_b.items()}

    # Solo inicializamos TF-IDF si el SimHash no es concluyente en algunos capítulos
    idf_map, vocab = None, None
    vectors_a, vectors_b = {}, {}

    score_matrix = {}
    total_ops = total_a * total_b
    done = 0

    for name_a, text_a in chapters_a.items():
        score_matrix[name_a] = {}
        h_md5_a = get_text_hash(text_a)
        h_sim_a = simhashes_a[name_a]

        for name_b, text_b in chapters_b.items():
            # A. COINCIDENCIA EXACTA
            if h_md5_a == md5_hashes_b[name_b]:
                score = 100.0
            else:
                # B. SIMHASH (Vía rápida)
                dist = hamming_distance(h_sim_a, simhashes_b[name_b])
                sim_score = (1.0 - (dist / 64.0)) * 100

                if sim_score > 96:
                    # Tan parecido que no merece la pena calcular TF-IDF;
                    # aun así aplicamos la penalización por longitud.
                    #
                    # CAP a 99.99: el 100.0 se reserva EXCLUSIVAMENTE para la
                    # identidad real (MD5 del texto normalizado, rama A, o el
                    # fast-path binario).  Un SimHash idéntico (distancia 0) NO
                    # garantiza textos idénticos (colisión posible), así que
                    # nunca debe reportarse como 100 % aquí.
                    score = min(sim_score * _length_penalty(text_a, text_b), 99.99)
                elif sim_score < 60:
                    # Tan diferente que lo descartamos
                    score = 0.0
                else:
                    # C. VÍA LENTA (Precisión para modo manual o dudas)
                    # Aquí usamos el TF-IDF y SequenceMatcher original
                    if idf_map is None:
                        idf_map, vocab = prepare_tfidf_data(chapters_a, chapters_b)

                    if name_a not in vectors_a:
                        vectors_a[name_a] = get_vector(text_a, idf_map, vocab)
                    if name_b not in vectors_b:
                        vectors_b[name_b] = get_vector(text_b, idf_map, vocab)

                    tfi = cosine_similarity(vectors_a[name_a], vectors_b[name_b])

                    if method == 'tfidf':
                        raw_score = tfi * 100
                    else: # combined (Precisión máxima)
                        # SequenceMatcher sobre una muestra de INICIO + FINAL
                        # (SEQ_SAMPLE_CHARS), para captar divergencias en la
                        # parte final del capítulo (epílogos, finales
                        # alternativos, reescrituras tardías).
                        #
                        # Usamos ratio() real (no quick_ratio): es sensible al
                        # ORDEN de los caracteres, no solo a su frecuencia, así
                        # que distingue textos con el mismo vocabulario pero
                        # estructura distinta.  Es O(n*m), pero solo se ejecuta
                        # en la franja dudosa de SimHash (60-96), que es la
                        # minoría de los pares, y sobre una ventana acotada.
                        sm = SequenceMatcher(
                            None,
                            _sample_head_tail(text_a),
                            _sample_head_tail(text_b),
                            autojunk=True,
                        )
                        raw_score = (tfi * 70) + (sm.ratio() * 30)

                    # Penalizar según diferencia de longitud para que
                    # "20% del texto de B presente en A" no dé 90%.
                    #
                    # CAP a 99.99 (ver rama SimHash): coseno=1 y ratio=1 sobre
                    # la MUESTRA no implican texto idéntico fuera de la muestra,
                    # así que el 100 % se reserva a la coincidencia MD5/binaria.
                    score = min(raw_score * _length_penalty(text_a, text_b), 99.99)

            score_matrix[name_a][name_b] = round(score, 2)
            done += 1
            if progress_cb and (done % 5 == 0 or done == total_ops):
                progress_cb(int(done / total_ops * 100))

    return _build_result_map(chapters_a, chapters_b, score_matrix, method)


# Umbral mínimo de similitud para considerar que dos capítulos son el mismo.
# Por debajo de este valor el capítulo se trata como único (sin pareja).
# Usado tanto en el greedy de matching como en el flag is_unique del chapter_map.
UNIQUE_THRESHOLD = 35.0


def _build_result_map(chapters_a, chapters_b, score_matrix, method):
    chapter_map = []

    # --- Matching exclusivo greedy por score descendente ---
    # Reglas:
    #   1. Cada capítulo de B solo puede emparejarse con UN capítulo de A.
    #   2. Solo se asignan parejas con score >= UNIQUE_THRESHOLD.
    #      Si el mejor score disponible para un A está por debajo del umbral,
    #      ese A queda sin pareja (is_unique=True, best_match_b=None) aunque
    #      todavía haya capítulos de B libres.  Esto evita que un capítulo
    #      único aparezca emparejado con un archivo de B casi al azar solo
    #      porque ese B aún no había sido reclamado por nadie.
    matched_b  = set()   # capítulos de B ya asignados
    assigned_a = {}      # name_a -> (name_b | None, score)

    candidates = []
    for name_a, scores in score_matrix.items():
        for name_b, score in scores.items():
            candidates.append((score, name_a, name_b))
    candidates.sort(key=lambda x: x[0], reverse=True)

    for score, name_a, name_b in candidates:
        if score < UNIQUE_THRESHOLD:
            break        # lista ordenada: todos los restantes también son < umbral
        if name_a in assigned_a:
            continue     # este A ya tiene pareja
        if name_b in matched_b:
            continue     # este B ya fue reclamado por otro A
        assigned_a[name_a] = (name_b, score)
        matched_b.add(name_b)

    # A sin pareja (por debajo del umbral o sin B disponible) -> único
    for name_a in chapters_a:
        if name_a not in assigned_a:
            assigned_a[name_a] = (None, 0.0)

    # Construir chapter_map en el orden original de A
    for name_a in chapters_a:
        best_b, best_score = assigned_a[name_a]
        is_unique = best_b is None   # el greedy ya garantiza score >= umbral si hay pareja
        chapter_map.append({
            'chapter_a':    name_a,
            'best_match_b': best_b,   # None si es único
            'similarity':   best_score,
            'is_unique':    is_unique,
        })

    # Capítulos de B sin ningún A asignado -> filas con chapter_a=None
    unmatched_b = [name_b for name_b in chapters_b if name_b not in matched_b]
    for name_b in unmatched_b:
        chapter_map.append({
            'chapter_a':    None,
            'best_match_b': name_b,
            'similarity':   0.0,
            'is_unique':    True,
        })

    total_a = len(chapters_a)
    total_b = len(chapters_b)
    universe = total_a + total_b   # total de capítulos en ambos libros

    # Similitud global = media de todos los capítulos del universo combinado.
    #
    # Para cada capítulo de A usamos su score del matching exclusivo (ya
    # calculado en chapter_map).  Para cada capítulo de B usamos el mejor
    # score que recibió desde cualquier A según el score_matrix -- si quedó
    # sin match (unmatched_b) su score es 0.0.
    #
    # Usar la media sobre el universo total (en lugar de media de medias)
    # evita que un subconjunto pequeño con scores altos infle el global
    # cuando el otro libro tiene muchos más capítulos sin correspondencia.
    sum_scores = 0.0

    # Aportación de los capítulos de A
    for r in chapter_map:
        if r['chapter_a'] is not None:
            sum_scores += r['similarity']
        # Los capítulos con chapter_a=None son huérfanos de B; su score 0.0
        # ya está contabilizado en la aportación de B más abajo.

    # Aportación de los capítulos de B (mejor score que recibieron desde A)
    for name_b in chapters_b:
        best = max(
            (score_matrix[name_a].get(name_b, 0.0) for name_a in chapters_a),
            default=0.0,
        )
        sum_scores += best

    global_similarity = round(sum_scores / universe, 2) if universe else 0.0

    return {
        'global_similarity': global_similarity,
        'method':            method,
        'chapter_map':       chapter_map,
        'unique_to_a':       [r['chapter_a'] for r in chapter_map
                              if r['is_unique'] and r['chapter_a'] is not None],
        'unique_to_b':       unmatched_b,
        'score_matrix':      score_matrix,
    }
