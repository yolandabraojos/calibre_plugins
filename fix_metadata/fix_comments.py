from __future__ import unicode_literals, division, absolute_import, print_function

__license__   = 'GPL v3'
__copyright__ = '2026, Fix Metadata Plugin'

"""
Comment (synopsis / description) quality checks.

Calibre stores the ``comments`` field as HTML.  This module strips the HTML
to plain text and flags comments that look wrong, without ever changing them
(a synopsis cannot be auto-repaired).  The action layer marks the affected
books so they can be reviewed by hand.

Issue codes (returned by :func:`analyze_comment`):

    vacio      -> empty / no usable text
    corto      -> below MIN_CHARS characters or MIN_WORDS words
    largo      -> above MAX_CHARS characters (likely full text / TOC / credits)
    repetido   -> a sentence/paragraph is duplicated inside the same comment
    basura     -> boilerplate ("sinopsis no disponible"), URLs, download-site
                  watermarks or mojibake (broken encoding), OR front/back
                  matter such as "About the Author", "Praise for ...",
                  "Editorial Reviews" or an "Excerpt" appended after the
                  synopsis -- that appended material is not a synopsis and
                  counts as junk.  Note this is about the appended SECTIONS,
                  not about HTML markup itself: a comment is never flagged
                  as basura merely for containing HTML tags/formatting.

Cross-book duplicates (same synopsis shared by several books) are detected in
the action layer using :func:`duplicate_fingerprint`; that adds the code
``duplicado``.

No Calibre dependencies: pure and unit-testable.
"""

import re
import unicodedata
import logging
from collections import Counter

try:
    from html import unescape as _html_unescape
except Exception:                      # pragma: no cover - very old Python
    def _html_unescape(s):
        return s

logger = logging.getLogger('FIX_METADATA_PLUGIN')

# ---------------------------------------------------------------------------
# Tunable thresholds (measured on the HTML-stripped plain text).
# ---------------------------------------------------------------------------
MIN_CHARS = 200        # a real synopsis is normally longer than this
MIN_WORDS = 30         # ...and has at least this many words
MAX_CHARS = 5000       # above this it is probably not a synopsis at all
_SEGMENT_MIN = 40      # min length of a sentence/paragraph to count as a repeat
_FP_MIN = 60           # min normalised length to consider for cross-book dupes

# ---------------------------------------------------------------------------
# Issue codes
# ---------------------------------------------------------------------------
ISSUE_EMPTY     = 'vacio'
ISSUE_SHORT     = 'corto'
ISSUE_LONG      = 'largo'
ISSUE_REPEAT    = 'repetido'
ISSUE_JUNK      = 'basura'
ISSUE_DUPLICATE = 'duplicado'   # assigned by the action layer (cross-book)

ALL_ISSUES = (ISSUE_EMPTY, ISSUE_SHORT, ISSUE_LONG,
              ISSUE_REPEAT, ISSUE_JUNK, ISSUE_DUPLICATE)

# Human-readable labels (Spanish) for the summary dialog.
ISSUE_LABELS = {
    ISSUE_EMPTY:     'Vacío',
    ISSUE_SHORT:     'Muy corto',
    ISSUE_LONG:      'Muy largo',
    ISSUE_REPEAT:    'Repetición interna',
    ISSUE_JUNK:      'Basura / boilerplate',
    ISSUE_DUPLICATE: 'Duplicado entre libros',
}

# ---------------------------------------------------------------------------
# HTML -> plain text
# ---------------------------------------------------------------------------
_SCRIPT_STYLE_RE = re.compile(r'(?is)<\s*(script|style)[^>]*>.*?<\s*/\s*\1\s*>')
_BR_RE   = re.compile(r'(?i)<\s*br\s*/?\s*>')
_BLOCK_RE = re.compile(r'(?i)</\s*(p|div|li|h[1-6]|tr|blockquote)\s*>')
_TAG_RE  = re.compile(r'<[^>]+>')
_WS_RE   = re.compile(r'\s+')


def strip_html(html):
    """Return the plain-text content of a comment (HTML tags removed)."""
    if not html:
        return ''
    text = _SCRIPT_STYLE_RE.sub(' ', html)
    text = _BR_RE.sub('\n', text)
    text = _BLOCK_RE.sub('\n', text)
    text = _TAG_RE.sub(' ', text)
    text = _html_unescape(text)
    # collapse runs of spaces/tabs but keep line breaks for segment splitting
    text = re.sub(r'[ \t\x0b\x0c\r]+', ' ', text)
    text = re.sub(r'\n\s*\n+', '\n', text)
    return text.strip()


def normalize_text(text):
    """Lower-case, NFKC, whitespace-collapsed form for comparisons."""
    if not text:
        return ''
    text = unicodedata.normalize('NFKC', text)
    return _WS_RE.sub(' ', text).strip().lower()


# ---------------------------------------------------------------------------
# Junk / boilerplate / mojibake detection
# ---------------------------------------------------------------------------
_JUNK_PHRASES = (
    'sinopsis no disponible', 'descripcion no disponible',
    'descripción no disponible', 'resena no disponible',
    'reseña no disponible', 'no hay sinopsis', 'sin sinopsis',
    'sin descripcion', 'sin descripción', 'no disponible',
    'proximamente', 'próximamente', 'lorem ipsum',
    'descripcion del libro no disponible',
)

# Watermarks left by download sites / scanners.
_SITE_MARKS = (
    'epublibre', 'lectulandia', 'libgen', 'z-library', 'zlibrary',
    'planetalibro', 'espaebook', 'elejandria', 'oxforddownloads',
    'descarga gratis', 'descargar gratis', 'telegram',
)

_URL_RE = re.compile(r'https?://|www\.', re.IGNORECASE)
# Common mojibake signatures from mis-decoded UTF-8/Latin-1 and the U+FFFD
# replacement character.
_MOJIBAKE_RE = re.compile(
    r'�|Ã[\x80-\xbf©±¡³­­¿½¼]|Â[ ©°º»½¿]|â€|â€™|â€œ|â€\x9d|Ã‚')


def _looks_like_junk(text, norm):
    if not norm:
        return False
    for p in _JUNK_PHRASES:
        if p in norm:
            return True
    for m in _SITE_MARKS:
        if m in norm:
            return True
    if _URL_RE.search(text):
        return True
    if _MOJIBAKE_RE.search(text):
        return True
    return False


# ---------------------------------------------------------------------------
# Front/back-matter sections (About the Author, Praise, Reviews, Excerpt)
# ---------------------------------------------------------------------------
# Publishers/aggregators (Amazon, Goodreads...) often append this kind of
# material after the real synopsis.  It is NOT a synopsis, so it counts as
# junk (basura) -- but it should also not be counted as part of the
# synopsis for the corto/largo length checks, which are computed on the
# text before it.  Detected as short, heading-like lines; the block-level
# tags in the original HTML already become newlines via strip_html, so a
# heading that was e.g. "<p><b>Praise for The Book</b></p>" ends up on its
# own line in the plain text.  This is about the appended section content,
# not about HTML markup: a comment's HTML formatting is never, by itself,
# a reason to call it junk.
_SECTION_LINE_MAXLEN = 60
_SECTION_LINE_PATTERNS = (
    ('about_author', re.compile(
        r'^about\s+(the|this)\s+authors?\b|^meet\s+the\s+authors?\b', re.I)),
    ('praise', re.compile(
        r'^praise\s+for\b|^praise\s*[:\-]?\s*$', re.I)),
    ('reviews', re.compile(
        r'^(editorial|from\s+the|advance)\s+reviews?\b|^reviews?\s*[:\-]?\s*$', re.I)),
    ('excerpt', re.compile(
        r'^(an?\s+)?excerpts?\b|^from\s+the\s+book\s*[:\-]?\s*$', re.I)),
)


def detect_extra_sections(text):
    """Find front/back-matter section headings in already-stripped ``text``.

    Returns ``(labels, cutoff)``: *labels* is the sorted tuple of section
    keys found (a subset of ``about_author``, ``praise``, ``reviews``,
    ``excerpt``); *cutoff* is the character offset of the first one within
    ``text``, or ``None`` if none were found.
    """
    labels = set()
    cutoff = None
    pos = 0
    for line in text.split('\n'):
        stripped = line.strip()
        if stripped and len(stripped) <= _SECTION_LINE_MAXLEN:
            for label, pat in _SECTION_LINE_PATTERNS:
                if pat.match(stripped):
                    labels.add(label)
                    if cutoff is None:
                        cutoff = pos
                    break
        pos += len(line) + 1
    return tuple(sorted(labels)), cutoff


# ---------------------------------------------------------------------------
# Internal repetition detection
# ---------------------------------------------------------------------------
_SEG_SPLIT_RE = re.compile(r'[.!?\n]+')


def _has_internal_repeat(norm):
    """True if a substantial sentence/paragraph appears more than once."""
    if not norm:
        return False
    segs = [s.strip() for s in _SEG_SPLIT_RE.split(norm)]
    segs = [s for s in segs if len(s) >= _SEGMENT_MIN]
    if segs:
        counts = Counter(segs)
        if any(c >= 2 for c in counts.values()):
            return True
    # Fallback: whole synopsis pasted twice back-to-back (no sentence enders).
    n = len(norm)
    if n >= 2 * _SEGMENT_MIN:
        half = n // 2
        a = norm[:half].strip()
        b = norm[half:].strip()
        if a and a == b:
            return True
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def analyze_comment(html):
    """Return a sorted list of issue codes for a single comment (no cross-book).

    Order of preference: an empty comment yields only ``vacio``.

    If front/back matter (About the Author / Praise / Reviews / Excerpt,
    see :func:`detect_extra_sections`) is found: it counts as ``basura``
    (it is not a synopsis), and the corto/largo length checks are computed
    on the text *before* the first such section (the real synopsis) rather
    than on the whole comment.  This is about the appended sections, not
    about HTML markup -- a comment is never flagged as basura merely for
    containing HTML tags/formatting.
    """
    text = strip_html(html)
    norm = normalize_text(text)
    if not norm:
        return [ISSUE_EMPTY]

    issues = []
    sections, cutoff = detect_extra_sections(text)
    # Only trust the cutoff as "end of synopsis" if there is a meaningful
    # amount of text before it; a heading in the first few characters isn't
    # preceded by an actual synopsis to measure.
    core_text = text
    if sections and cutoff is not None and cutoff >= 20:
        core_text = text[:cutoff].rstrip()
    core_norm = normalize_text(core_text)

    n_chars = len(core_text)
    n_words = len(core_norm.split())

    if n_chars < MIN_CHARS or n_words < MIN_WORDS:
        issues.append(ISSUE_SHORT)
    if n_chars > MAX_CHARS:
        issues.append(ISSUE_LONG)
    if _has_internal_repeat(norm):
        issues.append(ISSUE_REPEAT)
    if _looks_like_junk(text, norm) or sections:
        issues.append(ISSUE_JUNK)
    return issues


def duplicate_fingerprint(html):
    """Return a fingerprint string for cross-book duplicate detection.

    Returns ``None`` for empty or too-short comments (those are handled by the
    per-book checks and should not be grouped as duplicates).
    """
    norm = normalize_text(strip_html(html))
    if len(norm) < _FP_MIN:
        return None
    return norm
