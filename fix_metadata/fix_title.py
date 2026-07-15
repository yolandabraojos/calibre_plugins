from __future__ import unicode_literals, division, absolute_import, print_function

__license__   = 'GPL v3'
__copyright__ = '2026, Fix Metadata Plugin'

import re

# ===========================================================================
# Number words and series-name normalisation
# ===========================================================================

_WORD_NUM = {
    'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6,
    'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10, 'eleven': 11, 'twelve': 12,
}
_NUM = (r'(\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten|'
        r'eleven|twelve)')


def _to_index(raw):
    """Convert a captured number token (digits or English word) to float."""
    if raw is None:
        return None
    w = _WORD_NUM.get(raw.lower())
    return float(w) if w is not None else float(raw)


# Descriptors stripped from a detected series name (redundant labels). EXCLUDED
# on purpose: chronicle(s), cycle, saga, anthology, quartet -> often integral.
# Leading articles are also kept.
_SERIES_DESCRIPTOR = (
    r'(?:series|novellas?|novels?|shorts?|trilogy|trilog[ií]a|duet|'
    r'sequence|collection|omnibus|box\s*set)'
)
_TRAILING_DESC_RE = re.compile(r'[\s,]+' + _SERIES_DESCRIPTOR + r'[\s,]*$',
                               re.IGNORECASE)
_LEADING_SERIE_RE = re.compile(r'^serie[s]?\s+', re.IGNORECASE)

# Permissive descriptor cluster for STRIPPING a series ref out of a title.
_ANY_DESC = (r'(?:series|serie|novellas?|novels?|shorts?|trilogy|trilog[ií]a|'
             r'duet|sequence|collection|omnibus|box\s*set|chronicles?|cycle|'
             r'saga|anthology)')


def _normalize_series_name(name):
    """Strip redundant descriptor words and a leading Spanish 'Serie' prefix."""
    if not name:
        return name
    s = name.strip().strip(',;:').strip()
    s = _LEADING_SERIE_RE.sub('', s).strip()
    prev = None
    while prev != s:
        prev = s
        s = _TRAILING_DESC_RE.sub('', s).strip().strip(',').strip()
    return s or name.strip()


# ===========================================================================
# Compiled patterns used by find_series_in_title
# ===========================================================================

# A – "Title - Series Name #N"  or  "Title - Series Name #N (anything)"
_DASH_HASH_RE = re.compile(
    r'^(.*)\s+-\s+(.+?)\s+#(\d+(?:\.\d+)?)\s*(?:\([^)]*\))?\s*$'
)

# B – "Title (Series Name, #N)"  or  "Title (Series Name #N)"
_PAREN_HASH_RE = re.compile(
    r'^(.*)\s*\(([^)]+?),?\s*#(\d+(?:\.\d+)?)\)\s*$'
)

# K – "Title (Series Name Book N)"  or  "Title (Series Name, Book N)"
#   "Laundry Lady's Love (Ladies of Sanctuary House Book 1)"
#   Also matches plain "(Series Name N)" without any keyword.
#   Non-greedy group(2) stops at the earliest "Book N)" or " N)" boundary,
#   so "Ladies of Sanctuary House" is captured, not "Ladies of Sanctuary House Book".
_PAREN_BOOK_NUM_RE = re.compile(
    r'^(.*\S)\s*\(([^)]+?),?\s*(?:Book\s+|Bk\s+|#)?' + _NUM +
    r'\)\s*(?:\([^)]*\))?\s*$',
    re.IGNORECASE,
)

# I – "Series Name [N] - Title"  or  "Series Name [N] - Title (lang)"
#   Calibre's own "embed series in title" format.  The optional trailing
#   (lang) is consumed silently; language detection is done separately.
_BRACKET_INDEX_RE = re.compile(
    r'^(.+?)\s*\[(\d+(?:\.\d+)?)\]\s*-\s*(.+?)(?:\s*\([a-z]{2,3}\))?\s*$',
    re.IGNORECASE,
)

# S - "[Series Name #N] - Title"  (index inside brackets WITH a "#"; dash sep)
#   "[Jack Morgan #05] - Private Berlin"
_BRACKET_HASH_PREFIX_RE = re.compile(
    r'^\[([^\]#]+?)\s*#(\d+(?:\.\d+)?)\]\s*-\s*(.+?)\s*$'
)

# T - "(Series Name N) Title"  (plain parenthetical PREFIX, no "#"/keyword)
#   "(For His Pleasure 11) His Every Word"
#   "(Marco Didio Falco 10) A Los Leones(c.1)"
#   A lookahead requires at least one letter inside the parens so a bare
#   year like "(2012) Evie Undercover" is correctly left alone (that is a
#   publication date, not a series).
_PAREN_PREFIX_NUM_RE = re.compile(
    r'^\((?=[^)]*[A-Za-zÀ-ÿ])([^)]+?)\s+(\d+(?:\.\d+)?)\)\s*-?\s*(.+?)\s*$'
)

# C – "(lang) Title - Series Name NN"  (language prefix, plain number)
_LANG_PREFIX_DASH_RE = re.compile(
    r'^\(([a-z]{2,3})\)\s+(.*)\s+-\s+(.+?)\s+(\d{1,4}(?:\.\d+)?)\s*$',
    re.IGNORECASE,
)

# D – "Title - Series Name NN (lang)"  (language suffix, plain number)
_LANG_SUFFIX_DASH_RE = re.compile(
    r'^(.*)\s+-\s+(.+?)\s+(\d{1,4}(?:\.\d+)?)\s+\(([a-z]{2,3})\)\s*$',
    re.IGNORECASE,
)

# H – "Series - NNN - Title"  (series first, standalone number between dashes)
#   "Star Trek: The Original Series - 020 - The Tears of the Singers"
_SERIES_NUM_TITLE_RE = re.compile(
    r'^(.+?)\s+-\s+(\d{1,4}(?:\.\d+)?)\s+-\s+(.+?)\s*$'
)

# J – "Series Name N - Title"  (series name with inline number, single dash separator)
#   "City Of Fire Trilogy 1 - Dreamland"
_SERIES_INLINE_NUM_RE = re.compile(
    r'^(.+?)\s+(\d{1,4}(?:\.\d+)?)\s+-\s+(.+?)\s*$'
)

# L – "Author - NN Title"  (author prefix + leading index, NO series name)
#   "Linsey Hall - 05 Rise of the Fae"  →  index 5, title "Rise of the Fae"
#   Built dynamically from the author inside find_series_in_title.
#   Index limited to 1-3 digits so 4-digit years (e.g. "1984") stay in the title.

# M - "[Series Name N] - Title"  (index inside brackets; dash or bullet sep)
_BRACKET_NAME_NUM_RE = re.compile(
    r'^\[(.+?)\s+(\d+(?:\.\d+)?)\]\s*[-•·]\s*(.+?)\s*$'
)
# N - "Title: [A/An/The] Series Name [descriptor] Book N"  (greedy title; word numbers)
_COLON_SERIES_BOOK_RE = re.compile(
    r'^(.+):\s+(?:A\s+|An\s+|The\s+)?(.+?),?\s+(?:Book|Bk)\s+' + _NUM + r'\s*$',
    re.IGNORECASE,
)
# O - "Series Name N: Title"  or  "Series Name #N: Title"
_SERIES_NUM_COLON_RE = re.compile(
    r'^(.+?)\s+#?(\d+(?:\.\d+)?)\s*:\s+(.+?)\s*$'
)
# R - "Title - Book N in/of [the] Series Name [Series]" (also ': ' / '(...)')
#   "Coveted - Book 3 in the Gwen Sparks Series", "X (Book 2 of the Y Saga)"
#   Only "the" is consumed as article; "a/an" -> genre blurb, rejected later.
_BOOK_N_IN_RE = re.compile(
    r'^(.+?)[\s:,–-]+\(?\s*Book\s+(\d+(?:\.\d+)?)\s+(?:in|of)\s+'
    r'(?:the\s+)?(.+?)\)?\s*$',
    re.IGNORECASE,
)
# P - "Series Name #N - Title"  (series-first hash + dash)
_SERIES_HASH_DASH_RE = re.compile(
    r'^(.+?)\s+#(\d+(?:\.\d+)?)\s+-\s+(.+?)\s*$'
)
# Q - "Series Name Book N [-/:] Title"  (series-first "Book N")
_SERIES_BOOK_PREFIX_RE = re.compile(
    r'^(.+?)\s+(?:Book|Bk)\s+(\d+(?:\.\d+)?)\s*[-–:]\s+(.+?)\s*$',
    re.IGNORECASE,
)

# Generic words that are never a real series name (avoids "(Book 2)" → series "Book")
_GENERIC_SERIES = {
    'book', 'books', 'vol', 'vol.', 'volume', 'volumes',
    'part', 'parts', 'libro', 'libros', 'tomo', 'tomos',
    'parte', 'partes', 'no', 'no.', 'num', 'num.', 'number',
}


def _looks_like_year(idx):
    """True if *idx* is implausibly large for a real series index (>= 1000).
    Real series indices are well under 1000, so any 4-digit number is almost
    always a year captured by mistake ("Box Set ... 2018", "NIMWAY HALL: 1794").
    """
    try:
        return float(idx) >= 1000
    except (TypeError, ValueError):
        return False


# Container/format words: a series name that is really a box set, bundle, etc.
_CONTAINER_RE = re.compile(r'\b(box\s*set|boxed\s*set|boxset|bundle|omnibus|anthology)\b',
                           re.IGNORECASE)
# Junk prefixes (ebook/version markers captured by mistake).
_JUNK_PREFIX_RE = re.compile(r'(?i)^(mobi|epub|azw3?|kindle|calibre|kf8|pack)\b')
# Genre / marketing blurb captured as a series name
#   "A sexy, funny mystery/romance, Cottonmouth", "a contemporary mfff adventure"
_GENRE_BLURB_RE = re.compile(
    r'(?i)^(a|an)\b.*\b(romance|romantic|mystery|thriller|novella|novel|fiction|'
    r'fantasy|adventure|harem|saga|tale|tales|story|stories|collection)\b')


def _is_valid_series(name):
    """Return False for names that are not real series (generic, numeric,
    container formats, ebook/version junk, or genre/marketing blurbs)."""
    if not name:
        return False
    s = name.strip()
    if not s:
        return False
    if s.lower() in _GENERIC_SERIES:
        return False
    # Pure number (e.g. a stray year captured from "(2010)") is not a series name.
    if re.fullmatch(r'\d+(?:\.\d+)?', s):
        return False
    # Need at least two letters (rejects "#", "c.", "1/2", "v.9").
    if len(re.findall(r'[^\W\d_]', s, re.UNICODE)) < 2:
        return False
    if _CONTAINER_RE.search(s):
        return False
    if _JUNK_PREFIX_RE.match(s):
        return False
    if _GENRE_BLURB_RE.match(s):
        return False
    return True


# ===========================================================================
# Step 1 – find_series_in_title
# ===========================================================================

def find_series_in_title(title, language=None, author=None, author_sort=None):
    """
    Scan *title* for an embedded series reference and return the series data.

    Returns ``(series_name, series_index, subtitle)`` when a pattern matches,
    or ``(None, None, None)`` when nothing is found.

    *series_index* is a ``float``.  *subtitle* is only set by pattern G.

    Patterns are evaluated in specificity order to avoid weak matches
    shadowing strong ones:

    A)  ``Title - Series Name #N``            ← requires ``#``
    B)  ``Title (Series Name, #N)``           ← requires ``(…#N)``
    K)  ``Title (Series Name Book N)``        ← parenthetical with "Book" keyword or plain N
        e.g. ``Laundry Lady's Love (Ladies of Sanctuary House Book 1)``
    I)  ``Series Name [N] - Title``           ← calibre bracket-index format
        (optional trailing lang code ignored)
    S)  ``[Series Name #N] - Title``          ← bracketed prefix WITH "#"
    T)  ``(Series Name N) Title``             ← parenthetical prefix, no "#"
        (a bare year like "(2012) Title" is left alone, not a series)
    C)  ``(lang) Title - Series Name NN``     ← language-code prefix
    D)  ``Title - Series Name NN (lang)``     ← language-code suffix
        C and D only matched when *language* is provided and matches.
    G)  ``AuthorSort - Title [Series N] (Subtitle)``
        Only matched when *author_sort* is provided and matches the prefix.
    F)  ``Author - Series NN - Title``        ← author anchor before series
        Only matched when *author* is provided and matches the prefix.
    H)  ``Series - NNN - Title``              ← two-separator structural pattern
        e.g. ``Star Trek: The Original Series - 020 - The Tears of the Singers``
        Matched before J so the two-separator form takes priority.
    J)  ``Series Name N - Title``            ← single-separator with inline number
        e.g. ``City Of Fire Trilogy 1 - Dreamland``
        Matched after H; checked before E so numeric titles aren't lost.
    E)  ``Author - Title``                    ← weakest: author prefix only
        Returns ``(None, None, None)`` – title is cleaned but no series set.
        Only matched when *author* is provided and matches the prefix.
    """
    if not title:
        return None, None, None

    t = title.strip()

    # -- R  "Title - Book N in/of [the] Series" -------------------------------
    m = _BOOK_N_IN_RE.match(t)
    if m:
        title_part = m.group(1).strip()
        index = float(m.group(2))
        series = _normalize_series_name(m.group(3).strip())
        _arts = ('a', 'an', 'un', 'una')
        first = series.split()[0].lower() if series else ''
        if title_part and series and first not in _arts and _is_valid_series(series):
            return series, index, None

    # -- A -------------------------------------------------------------------
    m = _DASH_HASH_RE.match(t)
    if m:
        series = _normalize_series_name(m.group(2).strip())
        index  = float(m.group(3))
        if m.group(1).strip() and _is_valid_series(series):
            return series, index, None

    # -- B -------------------------------------------------------------------
    m = _PAREN_HASH_RE.match(t)
    if m:
        series = _normalize_series_name(m.group(2).strip())
        index  = float(m.group(3))
        if m.group(1).strip() and _is_valid_series(series):
            return series, index, None

    # -- P  "Series Name #N - Title" (series-first hash + dash) --------------
    m = _SERIES_HASH_DASH_RE.match(t)
    if m:
        series = m.group(1).strip()
        index  = float(m.group(2))
        clean  = m.group(3).strip()
        if _is_valid_series(series) and clean and not _looks_like_year(index):
            return series, index, None

    # -- Q  "Series Name Book N - Title" (series-first Book number) ----------
    m = _SERIES_BOOK_PREFIX_RE.match(t)
    if m:
        series = m.group(1).strip()
        index  = float(m.group(2))
        clean  = m.group(3).strip()
        if _is_valid_series(series) and clean and not _looks_like_year(index):
            return series, index, None

    # -- K -------------------------------------------------------------------
    # "Title (Series Name Book N)"  or  "Title (Series Name N)"
    # Reject generic/numeric captures so "(Book 2)" or "(2010)" are not mistaken
    # for a series.
    m = _PAREN_BOOK_NUM_RE.match(t)
    if m:
        series = _normalize_series_name(m.group(2).strip())
        index  = _to_index(m.group(3))
        if (m.group(1).strip() and _is_valid_series(series)
                and not _looks_like_year(index)):
            return series, index, None

    # -- N  "Title: [A] Series [descriptor] Book N" --------------------------
    m = _COLON_SERIES_BOOK_RE.match(t)
    if m:
        series = _normalize_series_name(m.group(2).strip())
        index  = _to_index(m.group(3))
        if m.group(1).strip() and _is_valid_series(series):
            return series, index, None

    # -- M  "[Series Name N] - Title" ----------------------------------------
    m = _BRACKET_NAME_NUM_RE.match(t)
    if m:
        series = m.group(1).strip()
        index  = float(m.group(2))
        clean  = m.group(3).strip()
        if _is_valid_series(series) and clean and not _looks_like_year(index):
            return series, index, None

    # -- I -------------------------------------------------------------------
    m = _BRACKET_INDEX_RE.match(t)
    if m:
        series = m.group(1).strip()
        index  = float(m.group(2))
        clean  = m.group(3).strip()
        if _is_valid_series(series) and clean and not _looks_like_year(index):
            return series, index, None

    # -- S  "[Series Name #N] - Title" ---------------------------------------
    m = _BRACKET_HASH_PREFIX_RE.match(t)
    if m:
        series = m.group(1).strip()
        index  = float(m.group(2))
        clean  = m.group(3).strip()
        if _is_valid_series(series) and clean and not _looks_like_year(index):
            return series, index, None

    # -- T  "(Series Name N) Title"  (no "#") --------------------------------
    m = _PAREN_PREFIX_NUM_RE.match(t)
    if m:
        series = m.group(1).strip()
        index  = float(m.group(2))
        clean  = m.group(3).strip()
        if _is_valid_series(series) and clean and not _looks_like_year(index):
            return series, index, None

    # -- C & D  (require book language) -------------------------------------
    if language:
        book_lang = language.lower().strip()

        m = _LANG_PREFIX_DASH_RE.match(t)
        if m and m.group(1).lower() == book_lang:
            series = m.group(3).strip()
            index  = float(m.group(4))
            if m.group(2).strip() and series:
                return series, index, None

        m = _LANG_SUFFIX_DASH_RE.match(t)
        if m and m.group(4).lower() == book_lang:
            series = m.group(2).strip()
            index  = float(m.group(3))
            if m.group(1).strip() and series:
                return series, index, None

    # -- G  (require known author sort name) --------------------------------
    if author_sort:
        s = re.escape(author_sort.strip())
        m = re.match(
            r'^' + s + r'\s+-\s+(.+?)\s+\[(.+?)\s+(\d{1,4}(?:\.\d+)?)\]\s*(?:\(([^)]*)\))?\s*$',
            t, re.IGNORECASE,
        )
        if m:
            clean    = m.group(1).strip()
            series   = m.group(2).strip()
            index    = float(m.group(3))
            subtitle = m.group(4).strip() if m.group(4) else None
            if clean and series:
                return series, index, subtitle

    # -- F  (require known author display name) -----------------------------
    if author:
        a = re.escape(author.strip())
        m = re.match(
            r'^' + a + r'\s+-\s+(.+?)\s+(\d{1,4}(?:\.\d+)?)\s+-\s+(.+?)\s*$',
            t, re.IGNORECASE,
        )
        if m:
            series = m.group(1).strip()
            index  = float(m.group(2))
            clean  = m.group(3).strip()
            if series and clean:
                return series, index, None

    # -- H -------------------------------------------------------------------
    m = _SERIES_NUM_TITLE_RE.match(t)
    if m:
        series = m.group(1).strip().rstrip(':,').strip()
        index  = float(m.group(2))
        clean  = m.group(3).strip()
        if _is_valid_series(series) and clean and not _looks_like_year(index):
            return series, index, None

    # -- J -------------------------------------------------------------------
    # "Series Name N - Title"  e.g. "City Of Fire Trilogy 1 - Dreamland"
    # Checked after H (two-separator) so H takes priority when applicable.
    m = _SERIES_INLINE_NUM_RE.match(t)
    if m:
        series = m.group(1).strip().rstrip(':,').strip()
        index  = float(m.group(2))
        clean  = m.group(3).strip()
        if _is_valid_series(series) and clean and not _looks_like_year(index):
            return series, index, None

    # -- O  "Series Name N: Title" / "Series Name #N: Title" -----------------
    m = _SERIES_NUM_COLON_RE.match(t)
    if m:
        series = m.group(1).strip().rstrip(':,').strip()
        index  = float(m.group(2))
        clean  = m.group(3).strip()
        if _is_valid_series(series) and clean and not _looks_like_year(index):
            return series, index, None

    # -- F2  (require author) "Author - Series Name N Title" (no dash before title) -
    #   "Karen Hawkins - MacLean 1 How to Abduct a Highland Lord"
    #   series = words before the number, index = number, title = words after.
    if author:
        a = re.escape(author.strip())
        m = re.match(r'^' + a + r'\s+-\s+([A-Za-z][^\d]*?)\s+(\d{1,3})\s+(\S.+)$',
                     t, re.IGNORECASE)
        if m:
            series = m.group(1).strip().rstrip(':,').strip()
            index  = float(m.group(2))
            clean  = m.group(3).strip()
            _articles = ('the', 'a', 'an', 'la', 'el', 'los', 'las',
                         'un', 'una', 'le', 'les', 'der', 'die', 'das')
            if (series and series.lower() not in _articles
                    and _is_valid_series(series) and clean):
                return series, index, None

    # -- L  (require known author) – "Author - NN Title": index only, no series -
    # e.g. "Linsey Hall - 05 Rise of the Fae" → index 5, title "Rise of the Fae".
    # Index limited to 1-3 digits so 4-digit years are not treated as an index.
    if author:
        a = re.escape(author.strip())
        m = re.match(
            r'^' + a + r'\s+-\s+(\d{1,3}(?:\.\d+)?)\s+(\S.*?)\s*$',
            t, re.IGNORECASE,
        )
        if m:
            index = float(m.group(1))
            clean = m.group(2).strip()
            if clean:
                # series is None on purpose: calibre keeps the index, series left blank
                return None, index, None

    # -- E  (require known author display name) – no series, title-only clean
    if author:
        a = re.escape(author.strip())
        m = re.match(r'^' + a + r'\s+-\s+(.+?)\s*$', t, re.IGNORECASE)
        if m and m.group(1).strip():
            return None, None, None   # signal: author prefix found, no series

    return None, None, None


# ===========================================================================
# Step 2 – find_language_in_title
# ===========================================================================

def find_language_in_title(title):
    """
    Return the 2-3 letter language code embedded as ``(xxx)`` in *title*,
    or ``None`` if none is found.

    Checks the end of the string first (most common), then the start.
    """
    t = title.strip()
    m = re.search(r'\(([a-z]{2,3})\)\s*$', t, re.IGNORECASE)
    if m:
        return m.group(1).lower()
    m = re.match(r'^\(([a-z]{2,3})\)\s+', t, re.IGNORECASE)
    if m:
        return m.group(1).lower()
    return None


# ===========================================================================
# Step 2b – find_subtitle_in_title  ("Main Title: Subtitle")
# ===========================================================================

def find_subtitle_in_title(title):
    """
    Return the subtitle embedded as ``Main Title: Subtitle`` in *title*,
    or ``None`` when no clean colon-separated subtitle is found.

    Conservative by design — the title itself is left untouched by callers,
    only the ``#subtitle`` column is filled:

      * splits on the FIRST ``": "`` (colon + space),
      * both the main part and the subtitle part must be non-empty,
      * the subtitle must not look like embedded series structure
        (no ``" - "``, ``#`` or ``[`` ), to avoid capturing patterns like
        ``Star Trek: The Original Series - 020 - ...``,
      * a trailing parenthetical (e.g. ``(Book 2)``) is stripped from the
        subtitle.
    """
    if not title:
        return None

    t = title.strip()
    if ': ' not in t:
        return None

    main, _, sub = t.partition(': ')
    main = main.strip()
    sub  = sub.strip()

    if not main or not sub:
        return None

    # Reject subtitles that carry series-like structure.
    if ' - ' in sub or '#' in sub or '[' in sub:
        return None

    # Drop a trailing "(...)" note such as "(Book 2)" or "(A Novel)".
    sub = re.sub(r'\s*\([^)]*\)\s*$', '', sub).strip()

    if len(sub) < 3:
        return None

    return sub


# ===========================================================================
# Step 3 – make_clean_title
# ===========================================================================

def make_clean_title(title, series=None, index=None, language=None,
                     author=None, author_sort=None, subtitle=None):
    """
    Return *title* stripped of all embedded metadata that was found in it:
    language code, author/author-sort prefix, series prefix/suffix, subtitle.

    Each parameter should be what was *found in the title* (from steps 1 & 2),
    not the effective metadata value — so we only strip what is actually there.

    Returns the original title unchanged if stripping would produce an empty
    string (safety fallback).
    """
    if not title:
        return title

    t = title.strip()
    idx_re = r'\d+(?:\.\d+)?'

    # -- Language code -------------------------------------------------------
    if language:
        lang_pat = re.escape(language.strip())
        t = re.sub(r'^\(' + lang_pat + r'\)\s+',   '', t, flags=re.IGNORECASE).strip()
        t = re.sub(r'\s*\(' + lang_pat + r'\)\s*$', '', t, flags=re.IGNORECASE).strip()

    # -- Edition note "(Spanish Edition)" / bare language code "(spa)" ------
    # Stripped unconditionally: these never belong in the clean title.
    t = re.sub(r'\s*\([A-Za-z][A-Za-z ]*\bEdition\)\s*$', '', t, flags=re.IGNORECASE).strip()
    t = re.sub(r'\s*\([a-z]{2,3}\)\s*$', '', t).strip()
    t = re.sub(r'^\([a-z]{2,3}\)\s+', '', t).strip()

    # -- Bare publication year "(YYYY)" --------------------------------------
    # Stripped unconditionally: a lone 4-digit number in parens is a date,
    # never a series (mirrors _looks_like_year's >=1000 heuristic).
    t = re.sub(r'^\(\d{4}\)\s+', '', t).strip()
    t = re.sub(r'\s*\(\d{4}\)\s*$', '', t).strip()

    # -- Copy/version marker "(c.1)", "(c.2)", ... ---------------------------
    # Stripped unconditionally: a leftover duplicate-copy marker, not content.
    t = re.sub(r'\s*\(c\.?\s*\d+\)\s*$', '', t, flags=re.IGNORECASE).strip()

    # -- Author sort prefix  "AuthorSort - " ---------------------------------
    if author_sort:
        t = re.sub(r'^' + re.escape(author_sort.strip()) + r'\s+-\s+',
                   '', t, flags=re.IGNORECASE).strip()

    # -- Author display prefix  "Author - " ----------------------------------
    if author:
        t = re.sub(r'^' + re.escape(author.strip()) + r'\s+-\s+',
                   '', t, flags=re.IGNORECASE).strip()

    # -- Author as SUFFIX / "by Author" / "(Author)" -------------------------
    # Anchored to the known author(s): only text that exactly equals the author
    # name is removed, so legitimate titles are never touched.  Handles the
    # display form and the "Last, First" -> "First Last" variant.
    _auth_variants = []
    for _a in (author, author_sort):
        if _a and _a.strip():
            _auth_variants.append(_a.strip())
            if ',' in _a:
                _last, _first = _a.split(',', 1)
                _swapped = (_first.strip() + ' ' + _last.strip()).strip()
                if _swapped:
                    _auth_variants.append(_swapped)
    _seen_auth = set()
    for _nm in _auth_variants:
        _k = _nm.lower()
        if not _nm or _k in _seen_auth:
            continue
        _seen_auth.add(_k)
        _p = re.escape(_nm)
        # "Title - Author"  /  "Title - Author"  /  "Title -- Author"  (suffix)
        t = re.sub(r'\s*[-–—]\s*' + _p + r'\s*$', '', t, flags=re.IGNORECASE).strip()
        # "Title by Author"
        t = re.sub(r'\s+by\s+' + _p + r'\s*$', '', t, flags=re.IGNORECASE).strip()
        # "Title (Author)"
        t = re.sub(r'\s*\(\s*' + _p + r'\s*\)\s*$', '', t, flags=re.IGNORECASE).strip()

    # -- Leading index with no series  (Pattern L: "Author - NN Title") ------
    # After the author prefix is stripped, a 1-3 digit leading number is the
    # series index, not part of the title.  Only stripped when an index was
    # found but no series name (so normal titles keep any leading number).
    if index is not None and not series:
        t = re.sub(r'^\d{1,3}(?:\.\d+)?\s+', '', t).strip()

    # -- Series ---------------------------------------------------------------
    if series:
        name = re.escape(series.strip())
        art   = r'(?:the\s+|a\s+|an\s+|la\s+|el\s+|los\s+|las\s+|serie\s+|series\s+)?'
        desc  = r'(?:\s+' + _ANY_DESC + r')*'
        s_pat = art + name + desc
        idx_w = _NUM

        # PREFIX forms (most specific first)
        # "[Series #N] - "  (Pattern S: bracket + hash prefix)
        t = re.sub(r'^\[' + s_pat + r'\s*#' + idx_re + r'\]\s*-\s*',
                   '', t, flags=re.IGNORECASE).strip()
        # "(Series N) "  (Pattern T: plain parenthetical prefix, no "#")
        t = re.sub(r'^\(' + s_pat + r'\s+' + idx_re + r'\)\s*-?\s*',
                   '', t, flags=re.IGNORECASE).strip()
        t = re.sub(r'^\[' + s_pat + r'\s+' + idx_re + r'\]\s*[-•·]\s*',
                   '', t, flags=re.IGNORECASE).strip()
        t = re.sub(r'^' + s_pat + r'\s*\[' + idx_re + r'\]\s*-\s*',
                   '', t, flags=re.IGNORECASE).strip()
        t = re.sub(r'^' + s_pat + r'\s*[:,]?\s+-\s+' + idx_re + r'\s+-\s+',
                   '', t, flags=re.IGNORECASE).strip()
        t = re.sub(r'^' + s_pat + r'\s+#' + idx_re + r'\s+-\s+',
                   '', t, flags=re.IGNORECASE).strip()
        t = re.sub(r'^' + s_pat + r'\s+(?:Book|Bk)\s+' + idx_re + r'\s*[-–:]\s+',
                   '', t, flags=re.IGNORECASE).strip()
        t = re.sub(r'^' + s_pat + r'\s*[:,]?\s+#?' + idx_re + r'\s*:\s+',
                   '', t, flags=re.IGNORECASE).strip()
        t = re.sub(r'^' + s_pat + r'\s*[:,]?\s+' + idx_re + r'\s+-\s+',
                   '', t, flags=re.IGNORECASE).strip()

        # "Series N " bare prefix, no separator (Pattern F2 after author strip)
        t = re.sub(r'^' + s_pat + r'\s+' + idx_re + r'\s+',
                   '', t, flags=re.IGNORECASE).strip()

        # SUFFIX forms
        # "- Book N in/of [the] Series [Series]"  (Pattern R)
        t = re.sub(r'[\s:,–-]+\(?\s*Book\s+' + idx_re + r'\s+(?:in|of)\s+'
                   r'(?:the\s+)?' + s_pat + r'\)?\s*$',
                   '', t, flags=re.IGNORECASE).strip()
        t = re.sub(r'\s*:\s+' + s_pat + r',?\s+(?:Book|Bk)\s+' + idx_w + r'\s*$',
                   '', t, flags=re.IGNORECASE).strip()
        t = re.sub(r'\s+-\s+' + s_pat + r'\s+#' + idx_re + r'(?:\s*\([^)]*\))?\s*$',
                   '', t, flags=re.IGNORECASE).strip()
        t = re.sub(r'\s*\(' + s_pat + r',?\s*#' + idx_re + r'\)\s*$',
                   '', t, flags=re.IGNORECASE).strip()
        t = re.sub(r'\s*\(' + s_pat + r',?\s*(?:Book\s+|Bk\s+)?' + idx_w +
                   r'\)\s*(?:\s*\([^)]*\))?\s*$',
                   '', t, flags=re.IGNORECASE).strip()
        t = re.sub(r'\s+-\s+' + s_pat + r'\s+' + idx_re + r'\s*$',
                   '', t, flags=re.IGNORECASE).strip()

        # INLINE bracket  "[Series N]"
        t = re.sub(r'\s*\[' + s_pat + r'\s+' + idx_re + r'\]\s*',
                   '', t, flags=re.IGNORECASE).strip()

    # -- Subtitle  "(subtitle)"  (Pattern G) ----------------------------------
    if subtitle:
        t = re.sub(r'\s*\(' + re.escape(subtitle.strip()) + r'\)\s*$',
                   '', t, flags=re.IGNORECASE).strip()

    return t if t else title.strip()


# ===========================================================================
# Legacy helpers (kept for any external callers)
# ===========================================================================

def _strip_lang(title, language=None):
    t = title.strip()
    code_pat = re.escape(language.strip()) if language else r'[a-zA-Z]{2,3}'
    t = re.sub(r'\s*\(' + code_pat + r'\)\s*$', '', t, flags=re.IGNORECASE).strip()
    t = re.sub(r'^\(' + code_pat + r'\)\s+',   '', t, flags=re.IGNORECASE).strip()
    return t


def clean_title(title, series=None, series_index=None, language=None):
    """
    Remove the ``SeriesName [N] - `` prefix and ``(lang)`` suffix embedded by
    calibre's own series-in-title format.  Uses the book's existing metadata
    to anchor the strip.
    """
    if not title:
        return title
    result = title.strip()
    result = _strip_lang(result, language)
    if series:
        series_esc = re.escape(series.strip())
        prefix_re  = r'^' + series_esc + r'\s*\[[^\]]+\]\s*-\s*'
        stripped   = re.sub(prefix_re, '', result, flags=re.IGNORECASE).strip()
        if stripped:
            result = stripped
    else:
        generic = re.sub(r'^.+?\[[^\]]+\]\s*-\s*', '', result).strip()
        if generic and generic != result:
            result = generic
    return result


def would_clean_title(title, series=None, series_index=None, language=None):
    """Return ``True`` if :func:`clean_title` would modify *title*."""
    if not title:
        return False
    return clean_title(title, series, series_index, language) != title.strip()
