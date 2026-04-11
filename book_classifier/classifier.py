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
      "min_keywords_match": 1,    // mínimo de keywords que deben coincidir
      "keywords": ["regencia", "regency", "~siglo\\s+xix"],
                                  // Prefijo ~ = regex literal (no se escapa ni normaliza)
      "exclude_keywords": [],     // Si aparece alguna → NO clasificar aquí
      "priority": 10              // Mayor prioridad aparece primero en la lista
                                  // (con allow_multiple=false, solo gana la mayor)
    }
  ],
  "options": {
    "case_sensitive": false,
    "whole_word": true,           // true = busca palabras completas (\\b...\\b)
    "allow_multiple": true        // false = solo la categoría de mayor prioridad
  }
}

Notas sobre keywords regex (~):
  - El texto ya está normalizado (sin acentos, minúsculas si case_sensitive=false).
  - Escribe los patrones también sin acentos: ~siglo\\s+xx  (no ~siglo\\s+XX).
  - whole_word NO se aplica a keywords regex; inclúyelo en el propio patrón si hace falta.
"""

import re
import unicodedata


class BookClassifier:
    """Clasifica un libro según un conjunto de reglas JSON."""

    def __init__(self, rules: dict):
        self.categories = rules.get('categories', [])
        opts = rules.get('options', {})

        self.case_sensitive = opts.get('case_sensitive', False)
        self.whole_word     = opts.get('whole_word', True)
        self.allow_multiple = opts.get('allow_multiple', True)

        # Pre-compilar expresiones regulares para rendimiento
        self._compiled = self._compile_rules()

    # ─── Public API ───────────────────────────────────────────────────────────

    def classify(self, text: str) -> list:
        """
        Devuelve la lista de categorías que coinciden con el texto del libro.

        :param text: Texto concatenado de todos los campos del libro.
        :returns: Lista de nombres de categorías coincidentes, ordenadas por prioridad desc.
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
            kw_hits   = [kw for kw in cat['keywords'] if self._search(normalized, kw)]
            excl_hits = [kw for kw in cat['exclude']  if self._search(normalized, kw)]
            matched   = self._matches(normalized, cat)

            report[cat['name']] = {
                'matched':        matched,
                'keywords_found': kw_hits,
                'excluded_found': excl_hits,
                'require_all':    cat['require_all'],
                'min_required':   cat['min_keywords_match'],
            }

        return report

    # ─── Internal ─────────────────────────────────────────────────────────────

    def _compile_rules(self) -> list:
        """Normaliza y ordena las reglas por prioridad descendente."""
        compiled = []
        for cat in self.categories:
            compiled.append({
                'name':               cat.get('name', 'Sin nombre'),
                # Keywords que empiezan por ~ son regex; no se normalizan
                'keywords': [
                    k if k.startswith('~') else self._normalize(k)
                    for k in cat.get('keywords', [])
                ],
                'exclude': [
                    k if k.startswith('~') else self._normalize(k)
                    for k in cat.get('exclude_keywords', [])
                ],
                'require_all':        cat.get('require_all', False),
                'priority':           cat.get('priority', 0),
                'min_keywords_match': cat.get('min_keywords_match', 1),
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
        """
        Busca una keyword en el texto respetando las opciones configuradas.

        Si la keyword empieza por '~', se trata como expresión regular directa
        (no se escapa, no se aplica whole_word automáticamente).
        """
        if not keyword:
            return False

        # ── Modo regex explícito ──────────────────────────────────────────────
        if keyword.startswith('~'):
            pattern = keyword[1:]
            flags = 0 if self.case_sensitive else re.IGNORECASE
            try:
                return bool(re.search(pattern, text, flags=flags))
            except re.error:
                return False

        # ── Modo normal ───────────────────────────────────────────────────────
        if self.whole_word:
            # Usamos lookaround en lugar de \b para manejar correctamente
            # palabras compuestas con guiones/barras (sci-fi, m/m, f/f…).
            pattern = r'(?<!\w)' + re.escape(keyword) + r'(?!\w)'
            flags = 0 if self.case_sensitive else re.IGNORECASE
            return bool(re.search(pattern, text, flags=flags))
        else:
            if self.case_sensitive:
                return keyword in text
            return keyword.lower() in text.lower()

    def _normalize(self, text: str) -> str:
        """Normaliza el texto: elimina acentos/diacríticos y pasa a minúsculas."""
        nfkd = unicodedata.normalize('NFKD', text)
        ascii_text = ''.join(c for c in nfkd if not unicodedata.combining(c))
        return ascii_text if self.case_sensitive else ascii_text.lower()
