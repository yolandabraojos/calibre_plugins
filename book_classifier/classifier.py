# -*- coding: utf-8 -*-
"""
Motor de clasificación de libros.

Formato del JSON de reglas:
{
  "categories": [
    {
      "name": "Romance Regencia",
      "require_all": false,       // false = OR entre keywords (cualquiera basta)
                                  // true  = AND (todas deben aparecer)
      "min_keywords_match": 1,    // AHORA AQUÍ: mínimo de keywords que deben coincidir
      "keywords": ["regencia", "regency", "romance"],
      "exclude_keywords": [],     // Si aparece alguna → NO clasificar aquí
      "priority": 10              // Mayor prioridad gana en caso de conflicto
                                  // (solo relevante si allow_multiple=false)
    }
  ],
  "options": {
    "case_sensitive": false,
    "whole_word": true,           // true = busca palabras completas
    "allow_multiple": true        // false = solo la categoría de mayor prioridad
  }
}
"""

import re
import unicodedata


class BookClassifier:
    """Clasifica un libro según un conjunto de reglas JSON."""

    def __init__(self, rules: dict):
        self.categories = rules.get('categories', [])
        opts = rules.get('options', {})

        self.case_sensitive    = opts.get('case_sensitive', False)
        self.whole_word        = opts.get('whole_word', True)
        self.allow_multiple    = opts.get('allow_multiple', True)
        
        # Pre-compilar expresiones regulares para rendimiento
        self._compiled = self._compile_rules()

    # ─── Public API ───────────────────────────────────────────────────────────

    def classify(self, text: str) -> list[str]:
        """
        Devuelve la lista de categorías que coinciden con el texto del libro.

        :param text: Texto concatenado del libro (título + subtítulo + comentarios + tags).
        :returns: Lista de nombres de categorías coincidentes.
        """
        if not text:
            return []

        normalized = self._normalize(text)
        matched = []

        for cat in self._compiled:
            if self._matches(normalized, cat):
                matched.append((cat['priority'], cat['name']))

        if not matched:
            return []

        matched.sort(key=lambda x: -x[0])  # Mayor prioridad primero

        if self.allow_multiple:
            return [name for _, name in matched]
        else:
            return [matched[0][1]]  # Solo la de mayor prioridad

    def test_text(self, text: str) -> dict:
        """
        Modo diagnóstico: devuelve qué keywords de cada categoría coinciden.
        Útil para depurar las reglas.
        """
        normalized = self._normalize(text)
        report = {}

        for cat in self._compiled:
            kw_hits     = [kw for kw in cat['keywords']     if self._search(normalized, kw)]
            excl_hits   = [kw for kw in cat['exclude']      if self._search(normalized, kw)]
            matched     = self._matches(normalized, cat)

            report[cat['name']] = {
                'matched':          matched,
                'keywords_found':   kw_hits,
                'excluded_found':   excl_hits,
                'require_all':      cat['require_all'],
                'min_required':     cat['min_keywords_match'],
            }

        return report

    # ─── Internal ─────────────────────────────────────────────────────────────

    def _compile_rules(self) -> list[dict]:
        """Normaliza y ordena las reglas por prioridad descendente."""
        compiled = []
        for cat in self.categories:
            compiled.append({
                'name':        cat.get('name', 'Sin nombre'),
                'keywords':    [self._normalize(k) for k in cat.get('keywords', [])],
                'exclude':     [self._normalize(k) for k in cat.get('exclude_keywords', [])],
                'require_all': cat.get('require_all', False),
                'priority':    cat.get('priority', 0),
                'min_keywords_match': cat.get('min_keywords_match', 1)
            })
        compiled.sort(key=lambda c: -c['priority'])
        return compiled

    def _matches(self, text: str, cat: dict) -> bool:
        """Evalúa si un texto cumple las condiciones de una categoría."""
        # Exclusiones tienen máxima precedencia
        if any(self._search(text, excl) for excl in cat['exclude']):
            return False

        if not cat['keywords']:
            return False

        hits = sum(1 for kw in cat['keywords'] if self._search(text, kw))

        if cat['require_all']:
            return hits == len(cat['keywords'])
        else:
            return hits >= max(cat['min_keywords_match'], 1)

    def _search(self, text: str, keyword: str) -> bool:
        """Busca una keyword en el texto respetando las opciones configuradas."""
        if not keyword:
            return False
        if self.whole_word:
            pattern = r'\b' + re.escape(keyword) + r'\b'
            return bool(re.search(pattern, text,
                                  flags=0 if self.case_sensitive else re.IGNORECASE))
        else:
            if self.case_sensitive:
                return keyword in text
            return keyword.lower() in text.lower()

    def _normalize(self, text: str) -> str:
        """Normaliza el texto: elimina acentos y pasa a minúsculas si corresponde."""
        # Descomponer caracteres Unicode (p.ej. é → e + acento)
        nfkd = unicodedata.normalize('NFKD', text)
        ascii_text = ''.join(c for c in nfkd if not unicodedata.combining(c))
        return ascii_text if self.case_sensitive else ascii_text.lower()