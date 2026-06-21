from __future__ import unicode_literals, division, absolute_import, print_function

__license__   = 'GPL v3'
__copyright__ = '2026, Fix Metadata Plugin'

import re

# ---------------------------------------------------------------------------
# Pattern A – dash separator with # index
#   "Blackout - John Milton #10 (John Milton Series)"
#   "The Da Vinci Code - Robert Langdon #2"
#
# Greedy (.*) for the title so that, when the title itself contains dashes,
# the LAST " - Series #N" block is used as the series reference.
# Requires whitespace around the dash to avoid splitting on hyphenated words.
# An optional trailing parenthetical "(…)" is consumed and discarded.
# ---------------------------------------------------------------------------
_DASH_RE = re.compile(
    r'^(.*)\s+-\s+(.+?)\s+#(\d+(?:\.\d+)?)\s*(?:\([^)]*\))?\s*$'
)

# ---------------------------------------------------------------------------
# Pattern B – parenthetical with # index
#   "The Name of the Wind (The Kingkiller Chronicle, #1)"
#   "Blackout (John Milton #10)"
# ---------------------------------------------------------------------------
_PAREN_RE = re.compile(
    r'^(.*)\s*\(([^)]+?),?\s*#(\d+(?:\.\d+)?)\)\s*$'
)

# ---------------------------------------------------------------------------
# Pattern C – language code prefix + plain number index (no #)
#   "(eng) Malka Older - Centenal Cycle 03"
#   "(spa) Título - Nombre Serie 2"
# ---------------------------------------------------------------------------
_LANG_PREFIX_DASH_RE = re.compile(
    r'^\(([a-z]{2,3})\)\s+(.*)\s+-\s+(.+?)\s+(\d{1,4}(?:\.\d+)?)\s*$',
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Pattern D – plain number index (no #) + language code suffix
#   "Malka Older - Centenal Cycle 03 (eng)"
#   "Título - Nombre Serie 2 (spa)"
# ---------------------------------------------------------------------------
_LANG_SUFFIX_DASH_RE = re.compile(
    r'^(.*)\s+-\s+(.+?)\s+(\d{1,4}(?:\.\d+)?)\s+\(([a-z]{2,3})\)\s*$',
    re.IGNORECASE,
)


def extract_series_from_title(title, language=None):
    """
    Attempt to extract embedded series information from *title*.

    Returns ``(clean_title, series_name, series_index)`` when a known pattern
    is found, or ``(None, None, None)`` when no pattern matches.

    *series_index* is returned as a ``float`` (calibre stores it that way).

    Parameters
    ----------
    title : str
        The book title as stored in calibre.
    language : str or None
        The book's language code (e.g. ``'eng'``, ``'spa'``).
        Required for Pattern C: the prefix ``(lang)`` is only stripped when
        it matches *language*.  Pass ``None`` to skip Pattern C entirely.

    Supported patterns
    ------------------
    A)  ``Title - Series Name #N``
        ``Title - Series Name #N (Series Name Series)``
    B)  ``Title (Series Name, #N)``
        ``Title (Series Name #N)``
    C)  ``(lang) Title - Series Name NN``   ← language prefix, no #
    D)  ``Title - Series Name NN (lang)``   ← language suffix, no #
        C and D only matched when *language* is provided and equals the code.
    """
    if not title:
        return None, None, None

    t = title.strip()

    # -- Pattern A -----------------------------------------------------------
    m = _DASH_RE.match(t)
    if m:
        clean  = m.group(1).strip()
        series = m.group(2).strip()
        index  = float(m.group(3))
        if clean and series:
            return clean, series, index

    # -- Pattern B -----------------------------------------------------------
    m = _PAREN_RE.match(t)
    if m:
        clean  = m.group(1).strip()
        series = m.group(2).strip()
        index  = float(m.group(3))
        if clean and series:
            return clean, series, index

    # -- Patterns C & D – only when the caller supplies the book language ----
    if language:
        book_lang = language.lower().strip()

        # C: "(lang) Title - Series NN"  – language code as prefix
        m = _LANG_PREFIX_DASH_RE.match(t)
        if m and m.group(1).lower() == book_lang:
            clean  = m.group(2).strip()
            series = m.group(3).strip()
            index  = float(m.group(4))
            if clean and series:
                return clean, series, index

        # D: "Title - Series NN (lang)"  – language code as suffix
        m = _LANG_SUFFIX_DASH_RE.match(t)
        if m and m.group(4).lower() == book_lang:
            clean  = m.group(1).strip()
            series = m.group(2).strip()
            index  = float(m.group(3))
            if clean and series:
                return clean, series, index

    return None, None, None
