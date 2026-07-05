# -*- coding: utf-8 -*-
"""
Clasificador IA local (sin dependencias externas).

Carga un modelo de regresión logística entrenado offline y exportado a
`model_weights.json` (vocabulario TF-IDF + coeficientes por librería), y lo
ejecuta en Python puro — no necesita scikit-learn ni numpy, así que funciona
dentro del Python embebido de Calibre.

Dos ejes de clasificación:
  • EJE 1 (librería): predice UNA librería por libro (excluyente) con confianza.
  • EJE 2 (tags de tema): reglas de palabras clave multi-etiqueta de tono/tropo,
    cargadas de `mood_rules.json`.

Ambos JSON se buscan primero en la carpeta de configuración de Calibre (para que
el usuario pueda actualizarlos sin reinstalar) y, si no, en el propio paquete.
"""
from __future__ import unicode_literals, division, absolute_import, print_function

import os
import re
import json
import math
import pkgutil
import unicodedata


def _load_json(name):
    """Carga un JSON: 1) carpeta config de Calibre  2) paquete  3) zip del
    plugin instalado (fiable en Calibre real)  4) fichero local (pruebas)."""
    # 1) carpeta de configuración del usuario
    try:
        from calibre.utils.config import config_dir
        p = os.path.join(config_dir, name)
        if os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    # 2) datos empaquetados con el plugin (pkgutil; no siempre funciona)
    try:
        pkg = __package__ or 'calibre_plugins.book_classifier'
        data = pkgutil.get_data(pkg, name)
        if data:
            return json.loads(data.decode('utf-8'))
    except Exception:
        pass
    # 3) leer directamente del ZIP instalado del plugin. Calibre carga los
    # plugins con un loader propio cuyo __file__ apunta DENTRO del zip (no es
    # una ruta real de disco), así que pkgutil.get_data y open() normal pueden
    # fallar con FileNotFoundError. plugin.load_resources() es el método
    # oficial de calibre para leer ficheros empaquetados en el zip del propio
    # plugin, y funciona siempre independientemente del loader interno.
    try:
        from calibre.customize.ui import find_plugin
        plugin = find_plugin('Book Classifier')
        if plugin is not None:
            data = plugin.load_resources([name]).get(name)
            if data:
                return json.loads(data.decode('utf-8'))
    except Exception:
        pass
    # 4) fichero junto a este módulo (modo prueba fuera de Calibre)
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, name), 'r', encoding='utf-8') as f:
        return json.load(f)


def normalize(text):
    """Minúsculas, sin acentos, sin HTML ni puntuación (igual que el entrenamiento)."""
    text = re.sub(r'<[^>]+>', ' ', text or '')
    text = unicodedata.normalize('NFKD', text)
    text = ''.join(c for c in text if not unicodedata.combining(c)).lower()
    text = re.sub(r"[^a-z0-9/\- ]", ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


class MLClassifier:
    """Clasificador de librería (eje 1) + tags de tema (eje 2)."""

    def __init__(self, model=None, mood=None, default_threshold=0.55):
        m = model if model is not None else _load_json('model_weights.json')
        self.classes   = m['classes']
        self.idf       = m['idf']           # { ngram: idf }
        self.coef      = m['coef']          # { ngram: [coef por clase] }
        self.intercept = m['intercept']     # [intercept por clase]
        self.default_threshold = default_threshold

        mood = mood if mood is not None else _load_json('mood_rules.json')
        self._mood = []
        for name, pattern in mood.items():
            try:
                self._mood.append((name, re.compile(pattern)))
            except re.error:
                pass

    # ─── Eje 1: librería ──────────────────────────────────────────────────────
    def predict_library(self, text):
        """Devuelve (libreria, confianza 0..1). (None, 0.0) si no hay texto útil."""
        words = normalize(text).split()
        if not words:
            return None, 0.0
        grams = words + [words[i] + ' ' + words[i + 1] for i in range(len(words) - 1)]
        idf = self.idf
        tf = {}
        for g in grams:
            if g in idf:
                tf[g] = tf.get(g, 0) + 1
        if not tf:
            return None, 0.0
        # TF-IDF sublinear + normalización L2 (idéntico a sklearn)
        vec = {g: (1.0 + math.log(c)) * idf[g] for g, c in tf.items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        scores = list(self.intercept)
        coef = self.coef
        n_cls = len(self.classes)
        for g, v in vec.items():
            vv = v / norm
            cf = coef[g]
            for k in range(n_cls):
                scores[k] += vv * cf[k]
        # softmax para confianza
        mx = max(scores)
        exps = [math.exp(s - mx) for s in scores]
        z = sum(exps) or 1.0
        ki = max(range(n_cls), key=lambda i: scores[i])
        return self.classes[ki], exps[ki] / z

    # ─── Eje 2: tags de tema ────────────────────────────────────────────────
    def mood_tags(self, text):
        """Lista de tags de tono/tropo que coinciden (multi-etiqueta)."""
        norm = normalize(text)
        return [name for name, rx in self._mood if rx.search(norm)]

    # ─── Combinado ────────────────────────────────────────────────────────────
    def classify(self, text, threshold=None):
        if threshold is None:
            threshold = self.default_threshold
        library, confidence = self.predict_library(text)
        return {
            'library':    library,
            'confidence': confidence,
            'uncertain':  (library is None or confidence < threshold),
            'moods':      self.mood_tags(text),
        }
