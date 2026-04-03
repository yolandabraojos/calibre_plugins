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

def get_simhash(text, hash_size=64):
    """
    Genera una huella digital (SimHash) de 64 bits.
    Permite comparar similitud de textos de forma ultra rápida.
    """
    tokens = text.split()
    if not tokens:
        return 0
    
    v = [0] * hash_size
    for word in tokens:
        # Generamos un hash único para cada palabra
        h = int(hashlib.md5(word.encode('utf-8')).hexdigest(), 16)
        for i in range(hash_size):
            if (h >> i) & 1:
                v[i] += 1
            else:
                v[i] -= 1
    
    ans = 0
    for i in range(hash_size):
        if v[i] >= 0:
            ans |= (1 << i)
    return ans

def hamming_distance(h1, h2):
    """Calcula cuántos bits son diferentes entre dos SimHashes."""
    x = h1 ^ h2
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
      len_a=1000, len_b=1000  → ratio=1.0  → penalty=1.0  (sin penalización)
      len_a=200,  len_b=1000  → ratio=0.2  → harmonic=0.33 → penalty≈0.58
      len_a=100,  len_b=1000  → ratio=0.1  → harmonic=0.18 → penalty≈0.43
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

# --- FUNCIÓN PRINCIPAL ---

def compare_books(chapters_a, chapters_b, method='combined', progress_cb=None):
    total_a = len(chapters_a)
    total_b = len(chapters_b)

    if total_a == 0 or total_b == 0:
        return {'global_similarity': 0.0, 'chapter_map': [], 
                'unique_to_a': list(chapters_a.keys()), 'unique_to_b': list(chapters_b.keys())}

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
                    score = sim_score * _length_penalty(text_a, text_b)
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
                        # SequenceMatcher sobre los primeros 2000 chars
                        sm = SequenceMatcher(None, text_a[:2000], text_b[:2000], autojunk=True)
                        raw_score = (tfi * 70) + (sm.quick_ratio() * 30)

                    # Penalizar según diferencia de longitud para que
                    # "20% del texto de B presente en A" no dé 90%.
                    score = raw_score * _length_penalty(text_a, text_b)

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

    # A sin pareja (por debajo del umbral o sin B disponible) → único
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

    # Capítulos de B sin ningún A asignado → filas con chapter_a=None
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
    # score que recibió desde cualquier A según el score_matrix — si quedó
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