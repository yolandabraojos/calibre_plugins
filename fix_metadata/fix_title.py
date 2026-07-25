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
    """Strip redundant descriptor words and a leading Spanish 'Serie' prefix.

    Also strips stray leading/trailing separator characters (``-``, ``–``,
    ``:``, ``;``, ``,``) left over when a regex captured the series name up
    to (but not past) a dash or colon that was actually a separator, not
    part of the name -- e.g. "(Skulduggery Pleasant - Book 3)" must yield
    "Skulduggery Pleasant", never "Skulduggery Pleasant -".
    """
    if not name:
        return name
    s = name.strip().strip(' ,;:-–').strip()
    s = _LEADING_SERIE_RE.sub('', s).strip()
    prev = None
    while prev != s:
        prev = s
        s = _TRAILING_DESC_RE.sub('', s).strip().strip(' ,;:-–').strip()
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

# K2 – "Title (Series Name N): Subtitle"  -- same as K but the parenthetical
#   sits in the MIDDLE of the title, followed by a colon-subtitle instead of
#   end-of-string, e.g. "Alex (Heroes MC Fort Dix 1): MC Romance Suspense".
#   K itself is anchored to "$" right after the paren so it never reaches
#   this shape; the subtitle is captured directly here (group 4) instead of
#   being left for the later colon-subtitle cascade to (mis)handle.
_PAREN_BOOK_NUM_SUBTITLE_RE = re.compile(
    r'^(.*\S)\s*\(([^)]+?),?\s*(?:Book\s+|Bk\s+|#)?' + _NUM +
    r'\)\s*:\s+(.+?)\s*$',
    re.IGNORECASE,
)

# U – "Title (Book N)"  bare parenthetical, NO series name captured
#   "The Southern Trail (Book 4)", "Reaper Of Sorrows (Book 1)"
_PAREN_BARE_BOOK_RE = re.compile(
    r'^(.+?)\s*\(Book\s+' + _NUM + r'\)\s*$', re.IGNORECASE
)

# V – "Title [Book N]"  bare bracket, NO series name captured
#   "My Stepbrother's Baby [Book 1]", "Break Me: The Wolf Hotel [Book 2]"
_BRACKET_BARE_BOOK_RE = re.compile(
    r'^(.+?)\s*\[Book\s+' + _NUM + r'\]\s*$', re.IGNORECASE
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

# M - "[Series Name N] - Title"  (index inside brackets; dash/bullet sep OPTIONAL)
#   "[Jack Morgan #05] - Private Berlin"  and also, with no separator at all,
#   "[Leine Basso 00.5] A Killing Truth"
_BRACKET_NAME_NUM_RE = re.compile(
    r'^\[(.+?)\s+(\d+(?:\.\d+)?)\]\s*(?:[-•·]\s*)?(.+?)\s*$'
)
# N - "Title: [A/An/The] Series Name [descriptor] Book/Volume N[: Subtitle]"
#   (greedy title; word numbers). An optional trailing ": Subtitle" segment is
#   captured separately (group 4) instead of being required to end the string,
#   so "Fighting Midnight: Ankarrah Chronicles Book Two: A Paranormal Urban
#   Fantasy" resolves to title="Fighting Midnight", series="Ankarrah
#   Chronicles", index=2, subtitle="A Paranormal Urban Fantasy" instead of the
#   whole "Ankarrah Chronicles Book Two: A Paranormal Urban Fantasy" being
#   swallowed as a colon-subtitle later.
_COLON_SERIES_BOOK_RE = re.compile(
    r'^(.+):\s+(?:A\s+|An\s+|The\s+)?(.+?),?\s+(?:Book|Bk|Vol\.?|Volume)\s+' + _NUM +
    r'(?:\s*:\s+(.+?))?\s*$',
    re.IGNORECASE,
)
# NB - "Title: Genre Blurb - Series Name - Book N[: Subtitle]"
#   "When Noonday Ends: A Southern Romantic-Suspense Novel - Nantahala -
#   Book Two" -> title="When Noonday Ends", subtitle="A Southern
#   Romantic-Suspense Novel", series="Nantahala", index=2. Must be tried
#   BEFORE N: without the genre-blurb check on group(2), N's lazy capture
#   would otherwise swallow the whole "A Southern Romantic-Suspense Novel -
#   Nantahala" span as if it were all one series name (it only sees "series
#   [connector] Book N", it has no notion of an embedded blurb+dash+series).
_COLON_BLURB_DASH_SERIES_BOOK_RE = re.compile(
    r'^(.+):\s+(.+?)\s+-\s+(.+?)\s+-\s+(?:Book|Bk|Vol\.?|Volume)\s+' + _NUM +
    r'(?:\s*:\s+(.+?))?\s*$',
    re.IGNORECASE,
)
# Z - "Series: (Book|Bk|Vol|Volume) N: Title"  (series-first colon form)
#   "The Atomic Sea: Volume Nine: War of the Abyss" -> series="The Atomic Sea",
#   index=9, title="War of the Abyss".
_COLON_SERIES_VOL_TITLE_RE = re.compile(
    r'^(.+?):\s+(?:Book|Bk|Vol\.?|Volume)\s+' + _NUM + r'\s*:\s+(.+?)\s*$',
    re.IGNORECASE,
)
# O - "Series Name N: Title"  or  "Series Name #N: Title"
_SERIES_NUM_COLON_RE = re.compile(
    r'^(.+?)\s+#?(\d+(?:\.\d+)?)\s*:\s+(.+?)\s*$'
)
# AA - "Title: Series Name N"  (colon-prefixed, bare trailing number, NO
#   "Book"/"Volume" keyword -- e.g. "Swordfall: Fall Trilogy Two").  Weakest
#   of the colon-based series patterns since it has no anchor word, so it is
#   only tried late in the cascade (see find_series_in_title), after all the
#   keyword-anchored colon/dash patterns have had a chance to match.
_TITLE_COLON_SERIES_BARENUM_RE = re.compile(
    r'^(.+?):\s+(.+?)\s+' + _NUM + r'\s*$', re.IGNORECASE,
)
# AB - "Title: Series Name #N"  (colon-prefixed, HASH before the number, no
#   Book/Volume keyword) -- e.g. "The Worst Reunion Ever: Kate & Kylie
#   Mystery #3". Mirrors AA but for the "#N" numbering style, which AA can't
#   reach ("#" isn't a digit so it breaks AA's "\s+NUM$" match).
_TITLE_COLON_SERIES_HASH_RE = re.compile(
    r'^(.+?):\s+(.+?)\s+#(\d+(?:\.\d+)?)\s*$', re.IGNORECASE,
)
# R - "Title - Book N in/of [the] Series Name [Series]" (also ': ' / '(...)')
#   "Coveted - Book 3 in the Gwen Sparks Series", "X (Book 2 of the Y Saga)"
#   Only "the" is consumed as article; "a/an" -> genre blurb, rejected later.
#   Index accepts word numbers too: "Book One of the Broken Mirrors Duology".
_BOOK_N_IN_RE = re.compile(
    r'^(.+?)[\s:,–-]+\(?\s*Book\s+#?' + _NUM + r'\s+(?:in|of)\s+'
    r'(?:the\s+)?(.+?)\)?\s*$',
    re.IGNORECASE,
)
# P - "Series Name #N - Title" / "Series Name #N-Title"  (series-first hash +
#   dash; the dash may or may not have spaces around it -- "Blaze of Glory
#   #1-Death From on High" has none, "Jack Morgan #05 - Private Berlin" has
#   both. The "#" digit anchor keeps this from misfiring on an unrelated
#   internal hyphen.)
_SERIES_HASH_DASH_RE = re.compile(
    r'^(.+?)\s+#(\d+(?:\.\d+)?)\s*-\s*(.+?)\s*$'
)
# Q - "Series Name Book N [-/:] Title"  (series-first "Book N"; N accepts word numbers)
#   Group 1 excludes ":" ("[^:]+?" not ".+?") so this can't reach across a
#   leading "Title: " prefix and swallow it into the "series" capture --
#   e.g. "Fighting Midnight: Ankarrah Chronicles Book Two: A Paranormal
#   Urban Fantasy" must be left for pattern N (below) to handle as
#   title="Fighting Midnight", series="Ankarrah Chronicles", NOT matched
#   here as series="Fighting Midnight: Ankarrah Chronicles". A genuine
#   series-first title never has a colon before its own "Book N" marker.
_SERIES_BOOK_PREFIX_RE = re.compile(
    r'^([^:]+?)\s+(?:Book|Bk)\s+' + _NUM + r'\s*[-–:]\s+(.+?)\s*$',
    re.IGNORECASE,
)
# NIS - "Title[,:] No. N in the ['the ]Series 'SeriesName'[ series]"
#   "Girl on a Train, No. 1 in the 'Tempted by her Student' series"
#   "Big City Massage (Lesbian Seduction): No. 1 in the Series 'Amy's Adventures in New York'"
#   The word "Series"/"series" may appear either BEFORE or AFTER the quoted
#   name (both forms occur in the wild); the quotes around the series name
#   are the strong, reliable anchor here, not the position of that word.
#   The captured name uses a LAZY ".+?" (not "[^'']+") because series names
#   themselves sometimes contain a straight apostrophe, e.g. "Amy's
#   Adventures in New York" -- excluding quote chars from the capture would
#   stop at that internal apostrophe and mangle the name. The lookahead
#   "(?=\s|$)" after the optional " series" is what keeps this safe: it
#   forces the *real* closing quote to be the one followed by a word
#   boundary (end of string, or whitespace before trailing content like a
#   "(lesbian erotica)" tag), not just any quote-shaped character.
_NUM_IN_SERIES_QUOTED_RE = re.compile(
    r'^(.+?)[,:]\s+No\.?\s+' + _NUM + r'\s+in\s+the\s+(?:Series\s+)?'
    r'[\'‘](.+?)[\'’](?:\s+series)?(?=\s|$)',
    re.IGNORECASE,
)
# W - "Series Name, Vol./Volume N"  (no separate title, whole string = series+vol)
#   "Magical Girl Raising Project, Vol. 4", "Grantville Gazette, Volume 91"
_SERIES_VOL_RE = re.compile(
    r'^(.+?),?\s+(?:Vol\.?|Volume)\s+(\d+(?:\.\d+)?)\s*$',
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


def _is_valid_series(name, allow_genre_blurb=False):
    """Return False for names that are not real series (generic, numeric,
    container formats, ebook/version junk, or genre/marketing blurbs).

    *allow_genre_blurb*: set True only when the CALLER already has strong
    independent evidence the candidate is a real series name despite its
    blurb-like shape -- e.g. an explicit "Book N"/"Bk N" keyword sitting
    right after it in the same parenthetical, as in "(A Tom Wagner
    Adventure Book 4)": "A Tom Wagner Adventure" reads like marketing copy
    (starts with "A" + a genre word), but the attached "Book 4" marker is
    something nobody puts on a pure genre blurb, so it's almost certainly
    the actual series title. All the OTHER guards below (generic words,
    pure numbers, container formats, junk prefixes) still apply regardless.
    """
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
    if not allow_genre_blurb and _GENRE_BLURB_RE.match(s):
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

    *series_index* is a ``float``.  *subtitle* is set by pattern G, and by
    pattern N when a colon-subtitle trails the "Book/Volume N" marker
    (e.g. ``"Fighting Midnight: Ankarrah Chronicles Book Two: A Paranormal
    Urban Fantasy"``).

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
        index = _to_index(m.group(2))
        series = _normalize_series_name(m.group(3).strip())
        _arts = ('a', 'an', 'un', 'una')
        first = series.split()[0].lower() if series else ''
        if title_part and series and first not in _arts and _is_valid_series(series):
            return series, index, None

    # -- NIS  "Title[,:] No. N in the ['the ]Series 'SeriesName'[ series]" ---
    m = _NUM_IN_SERIES_QUOTED_RE.match(t)
    if m:
        title_part = m.group(1).strip()
        index = _to_index(m.group(2))
        series = m.group(3).strip()
        if title_part and _is_valid_series(series) and not _looks_like_year(index):
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

    # -- Q  "Series Name Book N - Title" (series-first Book number; word numbers ok)
    m = _SERIES_BOOK_PREFIX_RE.match(t)
    if m:
        series = m.group(1).strip()
        index  = _to_index(m.group(2))
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
        # An explicit "Book "/"Bk " keyword between the captured name and the
        # number is strong evidence of a real series even when the name
        # itself happens to be shaped like a genre blurb, e.g. "(A Tom Wagner
        # Adventure Book 4)" -- "A Tom Wagner Adventure" starts with "A" +
        # the genre word "Adventure" (would normally be rejected as marketing
        # copy), but nobody attaches a literal "Book 4" marker to a pure
        # blurb, so this overrides just the blurb-shape guard, not the rest.
        connector = t[m.end(2):m.start(3)]
        has_book_kw = bool(re.search(r'\b(?:book|bk)\b', connector, re.IGNORECASE))
        if (m.group(1).strip()
                and _is_valid_series(series, allow_genre_blurb=has_book_kw)
                and not _looks_like_year(index)):
            return series, index, None

    # -- K2  "Title (Series Name N): Subtitle" --------------------------------
    # Same shape as K, but a colon-subtitle follows the paren instead of the
    # paren being the end of the string -- "Alex (Heroes MC Fort Dix 1): MC
    # Romance Suspense". Captures the subtitle directly (group 4) so it isn't
    # left for the colon-subtitle cascade to grab the wrong span with.
    m = _PAREN_BOOK_NUM_SUBTITLE_RE.match(t)
    if m:
        series = _normalize_series_name(m.group(2).strip())
        index  = _to_index(m.group(3))
        subt   = m.group(4).strip()
        connector = t[m.end(2):m.start(3)]
        has_book_kw = bool(re.search(r'\b(?:book|bk)\b', connector, re.IGNORECASE))
        if (m.group(1).strip() and subt
                and _is_valid_series(series, allow_genre_blurb=has_book_kw)
                and not _looks_like_year(index)):
            return series, index, subt

    # -- U/V  "Title (Book N)" / "Title [Book N]"  (no series name found) ---
    m = _PAREN_BARE_BOOK_RE.match(t) or _BRACKET_BARE_BOOK_RE.match(t)
    if m:
        title_part = m.group(1).strip()
        index = _to_index(m.group(2))
        if title_part and not _looks_like_year(index):
            return None, index, None

    # -- NB  "Title: Genre Blurb - Series - Book N[: Subtitle]" --------------
    # Tried before N so a genre blurb sitting between the title-colon and the
    # series doesn't get fused into the series name. Only fires when the
    # middle segment (group 2) actually LOOKS like marketing copy
    # (_GENRE_BLURB_RE) -- otherwise a normal series name that happens to
    # contain " - " would wrongly get split in two here.
    m = _COLON_BLURB_DASH_SERIES_BOOK_RE.match(t)
    if m:
        title_part = m.group(1).strip()
        blurb = m.group(2).strip()
        series = _normalize_series_name(m.group(3).strip())
        index = _to_index(m.group(4))
        subt = m.group(5).strip() if m.group(5) else blurb
        if (title_part and _GENRE_BLURB_RE.match(blurb)
                and _is_valid_series(series) and not _looks_like_year(index)):
            return series, index, subt

    # -- N  "Title: [A] Series [descriptor] Book/Volume N[: Subtitle]" -------
    m = _COLON_SERIES_BOOK_RE.match(t)
    if m:
        series = _normalize_series_name(m.group(2).strip())
        index  = _to_index(m.group(3))
        subt   = m.group(4).strip() if m.group(4) else None
        if m.group(1).strip() and _is_valid_series(series):
            return series, index, subt

    # -- Z  "Series: (Book|Volume) N: Title" (series-first colon form) ------
    m = _COLON_SERIES_VOL_TITLE_RE.match(t)
    if m:
        series = _normalize_series_name(m.group(1).strip())
        index  = _to_index(m.group(2))
        clean  = m.group(3).strip()
        if _is_valid_series(series) and clean and not _looks_like_year(index):
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

    # -- AA  "Title: Series Name N" (bare trailing number, no keyword) -------
    #   "Swordfall: Fall Trilogy Two" -> series="Fall Trilogy", index=2.
    #   Weakest colon-based series pattern (no "Book"/"Volume" anchor word).
    #   Series kept RAW (no _normalize_series_name): unlike patterns A/B/K/W,
    #   a trailing "Trilogy"/"Duology"/etc. here is very likely the actual
    #   series name the reader would recognise ("Fall Trilogy"), not a
    #   redundant descriptor -- mirrors patterns H/J/O, which are equally
    #   weak/generic and also skip normalisation for the same reason.
    m = _TITLE_COLON_SERIES_BARENUM_RE.match(t)
    if m:
        title_part = m.group(1).strip()
        series = m.group(2).strip()
        index  = _to_index(m.group(3))
        if title_part and _is_valid_series(series) and not _looks_like_year(index):
            return series, index, None

    # -- AB  "Title: Series Name #N" (hash before number, no keyword) --------
    #   "The Worst Reunion Ever: Kate & Kylie Mystery #3" -> series="Kate &
    #   Kylie Mystery", index=3. Kept RAW like AA -- no _normalize_series_name.
    m = _TITLE_COLON_SERIES_HASH_RE.match(t)
    if m:
        title_part = m.group(1).strip()
        series = m.group(2).strip()
        index  = _to_index(m.group(3))
        if title_part and _is_valid_series(series) and not _looks_like_year(index):
            return series, index, None

    # -- W  "Series Name, Vol./Volume N"  (whole title = series + volume) ---
    m = _SERIES_VOL_RE.match(t)
    if m:
        series = _normalize_series_name(m.group(1).strip())
        index  = _to_index(m.group(2))
        if _is_valid_series(series) and not _looks_like_year(index):
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

    # -- X  "Series - N Title"  (dash BEFORE the index, no author anchor) ----
    #   e.g. "Jackman & Evans - 09 Solace House", "Nancy Drew Files - 010
    #   Buried Secrets", "Alvarez Family Murder Mysteries - 4 DEAD ... If
    #   Only".  Mirrors pattern J (dash AFTER the index) with the dash on the
    #   other side.  These titles typically ALSO end in " - Author"; callers
    #   are expected to run strip_known_author_suffix() on *title* before
    #   calling find_series_in_title(), otherwise this (like every other
    #   pattern anchored to the end of the string) will never match.
    m = re.match(r'^(.+?)\s+-\s+(\d{1,3}(?:\.\d+)?)\s+(\S.*?)\s*$', t)
    if m:
        series = m.group(1).strip()
        index  = float(m.group(2))
        clean  = m.group(3).strip()
        if _is_valid_series(series) and clean and not _looks_like_year(index):
            return series, index, None

    # -- Y  Bare leading index, no series at all: "N - Title" (dash REQUIRED) -
    #   e.g. "05 - Warrior Priest", "03 - The Eternal Rose".  There is no
    #   author/series anchor here, so this is inherently the weakest pattern
    #   in the cascade -- checked empirically against a ~34k-row real-world
    #   library export (_datos_ejemplo/sample.csv): requiring the dash gave
    #   1 true positive and 0 false positives in the first 8000 titles,
    #   while the same pattern WITHOUT a required dash ("N Title", plain
    #   space) gave 18 hits and every single one was a false positive --
    #   ordinary titles that happen to start with a number ("10 Ways to
    #   Accidentally Fall in Love", "27 Dates", "7 Noches de Pecado", "100
    #   puertas", even "1462 South Broadway", a street address). So the
    #   dash-less form was deliberately dropped: "03 The Raging Storm" (no
    #   dash) will NOT be auto-detected even though it's a real example from
    #   this plugin's own test data -- that's an accepted false negative in
    #   exchange for not drowning the review dialog in false positives.
    m = re.match(r'^(\d{1,3}(?:\.\d+)?)\s*-\s*(\S.*?)\s*$', t)
    if m:
        index = float(m.group(1))
        clean = m.group(2).strip()
        if clean and not _looks_like_year(index):
            return None, index, None

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

# A colon-subtitle that is ONLY a collection/format descriptor -- optionally
# preceded by "The" or "Complete" -- is not a real subtitle, it is part of
# the title: "Whatever He Wants: The Complete Series", "The Essential
# Elements: Boxed Set".
_SUBTITLE_CONTAINER_RE = re.compile(
    r'^(?:the\s+)?complete\s+(?:series|trilogy|duology|collection|saga)$'
    r'|^(?:the\s+)?(?:boxed?\s*set|omnibus|bundle|anthology|collection)$',
    re.IGNORECASE,
)


def find_subtitle_in_title(title):
    """
    Return the subtitle embedded as ``Main Title: Subtitle`` in *title*,
    or ``None`` when no clean colon-separated subtitle is found.

    Conservative by design — the title itself is left untouched by callers,
    only the ``#subtitle`` column is filled:

      * splits on the LAST ``": "`` (colon + space) — when a title carries
        two or more colons, e.g. ``"Istoria Online: Square One: A LitRPG
        Adventure"``, everything up to the second-to-last colon is the main
        title (``"Istoria Online: Square One"``) and only the final segment
        is the subtitle (``"A LitRPG Adventure"``); the earlier interior
        colon is part of the title itself, not a second subtitle boundary,
      * both the main part and the subtitle part must be non-empty,
      * the subtitle must not look like embedded series structure
        (no ``" - "``, ``#`` or ``[`` ), to avoid capturing patterns like
        ``Star Trek: The Original Series - 020 - ...``,
      * a trailing parenthetical (e.g. ``(Book 2)``) is stripped from the
        subtitle,
      * a subtitle that is itself just a collection/format descriptor
        (``"The Complete Series"``, ``"Boxed Set"``, ...) is rejected —
        that text belongs to the title, not a real subtitle.
    """
    if not title:
        return None

    t = title.strip()
    if ': ' not in t:
        return None

    main, _, sub = t.rpartition(': ')
    main = main.strip()
    sub  = sub.strip()

    if not main or not sub:
        return None

    # Reject subtitles that carry series-like structure.
    if ' - ' in sub or '#' in sub or '[' in sub:
        return None

    # Drop a trailing "(...)" note such as "(Book 2)" or "(A Novel)".
    sub = re.sub(r'\s*\([^)]*\)\s*$', '', sub).strip()

    # Drop a dangling ":" left over when the removed paren was directly
    # preceded by a second colon, e.g. "Hiding from Monsters: A High School
    # Bully Romance: (Blackwood Academy Book 1)" -> subtitle should be
    # "A High School Bully Romance", not "A High School Bully Romance:".
    sub = sub.rstrip(' :;-–').strip()

    if len(sub) < 3:
        return None

    # Reject bare collection/format descriptors ("The Complete Series",
    # "Boxed Set", "Box Set", "Omnibus", ...): these belong in the title
    # ("Whatever He Wants: The Complete Series"), not split out as a
    # subtitle.
    if _SUBTITLE_CONTAINER_RE.match(sub):
        return None

    return sub


def find_dash_genre_subtitle_in_title(title):
    """
    Return a genre/marketing-blurb subtitle attached with ``" - "`` at the
    end of *title* -- e.g. ``"Wanted By The Billionaire Cowboy - A Second
    Chance Romance"`` -> ``"A Second Chance Romance"``.

    Unlike :func:`find_subtitle_in_title` (colon-based, broad), this only
    fires when the trailing segment has genre-blurb SHAPE -- starts with
    "A"/"An" and contains one of the romance/mystery/... keywords (see
    ``_GENRE_BLURB_RE``) -- so it can never mistake a real series-dash
    reference (``"Blackout - John Milton #10"``) for a subtitle: a dash
    alone is too weak a signal on its own, the blurb shape is what makes it
    safe.
    """
    if not title:
        return None
    t = title.strip()
    if ' - ' not in t:
        return None
    main, _, sub = t.rpartition(' - ')
    main = main.strip()
    sub = sub.rstrip(' :;-–').strip()
    if not main or not sub:
        return None
    if not _GENRE_BLURB_RE.match(sub):
        return None
    if len(sub) < 3:
        return None
    return sub


def find_paren_genre_subtitle_in_title(title):
    """
    Return a genre/marketing-blurb subtitle wrapped in a trailing ``(...)``
    with NO other separator -- e.g. ``"Where there's a Will... (A Novel)"``
    -> ``"A Novel"``.

    Only fires when the paren content has genre-blurb SHAPE (see
    ``_GENRE_BLURB_RE``); any other trailing paren (language code, edition
    note, a universe/imprint tag -- see :func:`find_generic_series_in_title`)
    is left alone and handled elsewhere.
    """
    if not title:
        return None
    t = title.strip()
    m = re.search(r'\(([^()]+)\)\s*$', t)
    if not m:
        return None
    main = t[:m.start()].strip()
    sub = m.group(1).strip()
    if not main or not sub:
        return None
    if not _GENRE_BLURB_RE.match(sub):
        return None
    if len(sub) < 3:
        return None
    return sub


def whole_title_is_genre_blurb(title):
    """
    True when *title* -- in its ENTIRETY, no separator to split on -- is
    itself just a generic descriptive blurb, e.g. ``"An Erotic Short Story
    Bundle"`` (left over after ``"Futanarium 3: An Erotic Short Story
    Bundle"`` had its ``"Futanarium 3: "`` series prefix stripped). Reuses
    ``_GENRE_BLURB_RE`` -- same shape test as the dash/paren subtitle
    detectors, just applied to the whole string instead of a trailing
    segment. Meant to be checked only when a series WAS found elsewhere in
    the title, as the trigger for falling back to "Series Index" as the
    title (see make_clean_title's *series*/*index* fallback).
    """
    if not title:
        return False
    return bool(_GENRE_BLURB_RE.match(title.strip()))


# ===========================================================================
# Step 2c – find_generic_series_in_title  ("Serie_Gen": universe/imprint tag
# with NO number, e.g. "(Elginvale High)", "(American Haunts)")
# ===========================================================================

# A trailing "(...)" that is purely a language code, a publication year, a
# "(c.N)" copy marker, or ends in "Edition" is handled elsewhere (language
# code / make_clean_title's unconditional year+edition strip) and must NOT
# also be claimed here.
_GEN_SERIES_LANG_ONLY_RE = re.compile(r'^[a-z]{2,3}$', re.IGNORECASE)
_GEN_SERIES_EDITION_RE = re.compile(r'\bedition\s*$', re.IGNORECASE)
_GEN_SERIES_YEAR_ONLY_RE = re.compile(r'^\d{4}$')
_GEN_SERIES_COPY_MARKER_RE = re.compile(r'^c\.?\s*\d+$', re.IGNORECASE)


def find_generic_series_in_title(title):
    """
    Return a trailing parenthetical annotation that looks like a
    universe/imprint/sub-series TAG WITHOUT a number -- meant for the
    ``#serie_gen`` custom column, separate from the numbered ``series``
    field.

    Examples::

        "The Library: Where Life Checks Out (American Haunts)" -> "American Haunts"
        "Tormented Part 2: A Dark High School Bully Romance (Elginvale High)"
            -> "Elginvale High"
        "Voodoo (Royal Bastards MC: Ankeny IA)" -> "Royal Bastards MC: Ankeny IA"

    Returns ``None`` when the trailing paren is something else entirely
    (language code, publication year, "(c.N)" copy marker, "...Edition",
    a genre/marketing blurb like "(An Alpha Billionaire Romance)", or --
    critically -- anything containing a digit, since that is a real
    numbered series/book reference and belongs to ``find_series_in_title``
    instead, not here). Only ONE trailing paren group is considered; nested
    or multiple trailing parens are left alone.
    """
    if not title:
        return None

    t = title.strip()
    m = re.search(r'\(([^()]+)\)\s*$', t)
    if not m:
        return None

    content = m.group(1).strip()
    if not content:
        return None

    if _GEN_SERIES_LANG_ONLY_RE.match(content):
        return None
    if _GEN_SERIES_EDITION_RE.search(content):
        return None
    if _GEN_SERIES_YEAR_ONLY_RE.match(content):
        return None
    if _GEN_SERIES_COPY_MARKER_RE.match(content):
        return None
    # Anything with a digit is a real (numbered) series/book reference --
    # that belongs to find_series_in_title, not to the generic/no-number tag.
    if re.search(r'\d', content):
        return None
    if _SUBTITLE_CONTAINER_RE.match(content):
        return None
    if not _is_valid_series(content):
        return None

    return content


def strip_generic_series_paren(title, serie_gen):
    """Remove a trailing ``(serie_gen)`` annotation from *title*, exactly as
    returned by :func:`find_generic_series_in_title`. No-op if *serie_gen*
    is falsy or does not actually appear as a trailing paren."""
    if not title or not serie_gen:
        return title
    t = title.strip()
    return re.sub(r'\s*\(' + re.escape(serie_gen.strip()) + r'\)\s*$',
                  '', t, flags=re.IGNORECASE).strip()


# ===========================================================================
# Step 3 – make_clean_title
# ===========================================================================

def strip_known_author_suffix(title, author=None, author_sort=None):
    """Strip a trailing " - Author" / "by Author" / "(Author)" from *title*,
    anchored to the known author name(s) (display form and the swapped
    "Last, First" -> "First Last" variant). No-op if neither is provided or
    neither matches. Used both standalone (to normalise a title BEFORE
    series/language detection, since most find_series_in_title patterns
    anchor to the end of the string and a trailing author defeats them) and
    internally by make_clean_title.
    """
    t = (title or '').strip()
    if not t:
        return t
    auth_variants = []
    for a in (author, author_sort):
        if a and a.strip():
            auth_variants.append(a.strip())
            if ',' in a:
                last, first = a.split(',', 1)
                swapped = (first.strip() + ' ' + last.strip()).strip()
                if swapped:
                    auth_variants.append(swapped)
    seen = set()
    for nm in auth_variants:
        k = nm.lower()
        if not nm or k in seen:
            continue
        seen.add(k)
        p = re.escape(nm)
        t = re.sub(r'\s*[-–—]\s*' + p + r'\s*$', '', t, flags=re.IGNORECASE).strip()
        t = re.sub(r'\s+by\s+' + p + r'\s*$', '', t, flags=re.IGNORECASE).strip()
        t = re.sub(r'\s*\(\s*' + p + r'\s*\)\s*$', '', t, flags=re.IGNORECASE).strip()
    return t


def make_clean_title(title, series=None, index=None, language=None,
                     author=None, author_sort=None, subtitle=None,
                     serie_gen=None):
    """
    Return *title* stripped of all embedded metadata that was found in it:
    language code, author/author-sort prefix, series prefix/suffix, subtitle,
    generic/no-number series tag (``serie_gen``, see
    :func:`find_generic_series_in_title`).

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

    # -- Generic/no-number series tag "(Serie_Gen)" ---------------------------
    # e.g. "(Elginvale High)", "(American Haunts)" -- see
    # find_generic_series_in_title(). Stripped from wherever it sits (it is
    # usually the very last parenthetical, but callers may pass the ORIGINAL
    # title here even though detection already stripped their own working
    # copy, so this has to run again defensively).
    if serie_gen:
        t = re.sub(r'\s*\(' + re.escape(serie_gen.strip()) + r'\)\s*$',
                   '', t, flags=re.IGNORECASE).strip()

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
    t = strip_known_author_suffix(t, author=author, author_sort=author_sort)

    # -- Leading index with no series  (Pattern L: "Author - NN Title") ------
    # After the author prefix is stripped, a 1-3 digit leading number is the
    # series index, not part of the title.  Only stripped when an index was
    # found but no series name (so normal titles keep any leading number).
    if index is not None and not series:
        t = re.sub(r'^\d{1,3}(?:\.\d+)?\s*-?\s*', '', t).strip()
        # Bare "(Book N)" / "[Book N]" suffix (Patterns U/V) – no series text
        # to anchor on, so this is stripped unconditionally in this branch.
        t = re.sub(r'\s*\(Book\s+' + idx_re + r'\)\s*$', '', t, flags=re.IGNORECASE).strip()
        t = re.sub(r'\s*\[Book\s+' + idx_re + r'\]\s*$', '', t, flags=re.IGNORECASE).strip()

    # -- Series ---------------------------------------------------------------
    if series:
        name = re.escape(series.strip())
        art   = r'(?:the\s+|a\s+|an\s+|la\s+|el\s+|los\s+|las\s+|serie\s+|series\s+)?'
        desc  = r'(?:\s+' + _ANY_DESC + r')*'
        s_pat = art + name + desc
        idx_w = _NUM

        # "Title, No. N in the ['the ]Series 'SeriesName'[ series]"  (Pattern NIS)
        # Keeps group 1 (the real title prefix) via backreference; anything
        # AFTER the quoted series name (e.g. a trailing "(lesbian erotica)"
        # genre tag) is left untouched for the subtitle/serie_gen steps.
        t = re.sub(r'^(.+?)[,:]\s+No\.?\s+' + idx_w + r'\s+in\s+the\s+(?:Series\s+)?'
                   r'[\'‘]' + name + r'[\'’](?:\s+series)?\s*',
                   r'\1 ', t, flags=re.IGNORECASE).strip()

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
        # Pattern P prefix -- dash may or may not have spaces around it
        # ("Series #1-Title" as well as "Series #05 - Title"), must match
        # _SERIES_HASH_DASH_RE's detection regex.
        t = re.sub(r'^' + s_pat + r'\s+#' + idx_re + r'\s*-\s*',
                   '', t, flags=re.IGNORECASE).strip()
        # NOTE: idx_w (word-number-aware _NUM), not idx_re -- this must match
        # Pattern Q's detection regex (_SERIES_BOOK_PREFIX_RE), which accepts
        # "Book Three" as well as "Book 3". Using digit-only idx_re here left
        # titles like "NO ROAD HOME Book Three: Risen" un-stripped (series was
        # still detected correctly, but the "Book Three:" prefix stayed stuck
        # to the title instead of being removed with the series name).
        t = re.sub(r'^' + s_pat + r'\s+(?:Book|Bk)\s+' + idx_w + r'\s*[-–:]\s+',
                   '', t, flags=re.IGNORECASE).strip()
        # "Series: (Book|Volume) N: "  prefix (Pattern Z: series-first colon form)
        t = re.sub(r'^' + s_pat + r'\s*:\s+(?:Book|Bk|Vol\.?|Volume)\s+' + idx_w +
                   r'\s*:\s+',
                   '', t, flags=re.IGNORECASE).strip()
        t = re.sub(r'^' + s_pat + r'\s*[:,]?\s+#?' + idx_re + r'\s*:\s+',
                   '', t, flags=re.IGNORECASE).strip()
        t = re.sub(r'^' + s_pat + r'\s*[:,]?\s+' + idx_re + r'\s+-\s+',
                   '', t, flags=re.IGNORECASE).strip()

        # "Series N " bare prefix, no separator (Pattern F2 after author strip)
        t = re.sub(r'^' + s_pat + r'\s+' + idx_re + r'\s+',
                   '', t, flags=re.IGNORECASE).strip()
        # "Series - N " prefix, dash BEFORE the index (Pattern X)
        t = re.sub(r'^' + s_pat + r'\s+-\s+' + idx_re + r'\s+',
                   '', t, flags=re.IGNORECASE).strip()

        # SUFFIX forms
        # "Blurb - Series - Book N[: Subtitle]"  (Pattern NB) -- strips the
        # blurb+series+bookN span together with whatever's in *subtitle*
        # (the blurb itself, when there's no separate trailing subtitle).
        if subtitle:
            t = re.sub(r'\s*:\s+' + re.escape(subtitle.strip()) + r'\s+-\s+' + s_pat +
                       r'\s+-\s+(?:Book|Bk|Vol\.?|Volume)\s+' + idx_w +
                       r'(?:\s*:\s+.+)?\s*$',
                       '', t, flags=re.IGNORECASE).strip()
        # "- Book N in/of [the] Series [Series]"  (Pattern R; N accepts word numbers)
        t = re.sub(r'[\s:,–-]+\(?\s*Book\s+#?' + idx_w + r'\s+(?:in|of)\s+'
                   r'(?:the\s+)?' + s_pat + r'\)?\s*$',
                   '', t, flags=re.IGNORECASE).strip()
        # ": Series[,/:/-] Book/Volume N[: Subtitle]"  (Pattern N; optional
        # trailing colon-subtitle is consumed too, whatever its exact text --
        # the caller already extracted it separately via *subtitle*). The
        # connector before "Book/Volume" accepts comma, semicolon, colon or
        # dash -- not just a comma -- to match what the DETECTION regex
        # (_COLON_SERIES_BOOK_RE) already tolerates there (it absorbs any of
        # these into the lazy series capture and _normalize_series_name trims
        # them back off), e.g. "Alice Non-Biological: The Girls on the Hill:
        # Book 2" and "A New Paige: Stained Souls MC - Book 2" both need this.
        # The connector needs "\s*" (not just an optional single char) on
        # BOTH sides -- "Stained Souls MC - Book 2" has a real space before
        # the dash too ("MC" + " - " + "Book"), which a single optional
        # separator char right after s_pat can't absorb on its own.
        t = re.sub(r'\s*:\s+' + s_pat + r'\s*[,;:\-–]?\s+(?:Book|Bk|Vol\.?|Volume)\s+' + idx_w +
                   r'(?:\s*:\s+.+)?\s*$',
                   '', t, flags=re.IGNORECASE).strip()
        t = re.sub(r'\s+-\s+' + s_pat + r'\s+#' + idx_re + r'(?:\s*\([^)]*\))?\s*$',
                   '', t, flags=re.IGNORECASE).strip()
        t = re.sub(r'\s*\(' + s_pat + r',?\s*#' + idx_re + r'\)\s*$',
                   '', t, flags=re.IGNORECASE).strip()
        # Allows a bare "-"/"–" between the series name and "Book N" too, not
        # just a comma (Pattern K: "(Skulduggery Pleasant - Book 3)").
        t = re.sub(r'\s*\(' + s_pat + r'\s*[,\-–]?\s*(?:Book\s+|Bk\s+)?' + idx_w +
                   r'\)\s*(?:\s*\([^)]*\))?\s*$',
                   '', t, flags=re.IGNORECASE).strip()
        # Pattern K2: "(Series N): Subtitle" -- paren mid-title followed by a
        # colon-subtitle instead of end-of-string, e.g. "Alex (Heroes MC Fort
        # Dix 1): MC Romance Suspense". Both the paren AND the subtitle text
        # that follows it get removed together (the subtitle lives in its own
        # field, not the title).
        if subtitle:
            t = re.sub(r'\s*\(' + s_pat + r'\s*[,\-–]?\s*(?:Book\s+|Bk\s+)?' + idx_w +
                       r'\)\s*:\s+' + re.escape(subtitle.strip()) + r'\s*$',
                       '', t, flags=re.IGNORECASE).strip()
        t = re.sub(r'\s+-\s+' + s_pat + r'\s+' + idx_re + r'\s*$',
                   '', t, flags=re.IGNORECASE).strip()
        # ": Series N"  bare colon suffix, no keyword (Pattern AA)
        t = re.sub(r'\s*:\s+' + s_pat + r'\s+' + idx_w + r'\s*$',
                   '', t, flags=re.IGNORECASE).strip()
        # ": Series #N"  bare colon suffix, hash before number (Pattern AB)
        t = re.sub(r'\s*:\s+' + s_pat + r'\s+#' + idx_re + r'\s*$',
                   '', t, flags=re.IGNORECASE).strip()

        # INLINE bracket  "[Series N]"
        t = re.sub(r'\s*\[' + s_pat + r'\s+' + idx_re + r'\]\s*',
                   '', t, flags=re.IGNORECASE).strip()

    # NOTE (v1.7.8, Yolanda's feedback): Pattern W ("Series Name, Vol./Volume
    # N" as the ENTIRE title, e.g. "Grantville Gazette, Volume 91") used to
    # strip the ", Volume N" suffix here too, reducing the title down to just
    # "Grantville Gazette" -- but a title that IS "Series, Volume N" with
    # nothing else is a normal, expected title text on its own; series/index
    # are already captured as separate metadata by find_series_in_title, so
    # there is no good reason to also blank the title down to a bare series
    # name. Deliberately NOT stripping here anymore -- the title stays as
    # originally written for Pattern W matches.

    # -- Subtitle  "(subtitle)"  (Pattern G) ----------------------------------
    if subtitle:
        t = re.sub(r'\s*\(' + re.escape(subtitle.strip()) + r'\)\s*$',
                   '', t, flags=re.IGNORECASE).strip()

    # -- Trailing dangling separator ------------------------------------------
    # A stray ":"/"-"/"–" left at the very end once its trailing content
    # (series/subtitle/serie_gen parenthetical, etc.) has been stripped away,
    # e.g. "Justice Unserved: (Nathan Doe Series Book 1)" -> paren removed ->
    # "Justice Unserved:" -> this rule -> "Justice Unserved". Only strips
    # separator/whitespace chars, so it never eats real title text.
    t = t.rstrip(' :;-–').strip()

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
