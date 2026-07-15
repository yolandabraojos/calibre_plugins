from __future__ import unicode_literals, division, absolute_import, print_function

__license__   = 'GPL v3'
__copyright__ = '2026, Fix Metadata Plugin'

"""
Tag canonicalisation to a controlled Spanish vocabulary ``Grupo · Valor``.

The messy, machine-generated tags found in the library (``Themes.*``,
``English.Romance.*``, ``Temas.*``, ``_Genre.*`` …, mixing English/Spanish,
separators and hierarchy) are mapped onto the same ``Grupo · Valor`` scheme
used by the Book Classifier ("Temas").

Mapping data lives in ``tags_map.json`` (next to this module):

    {
      "rules": { "Grupo · Valor": "regex de palabras clave EN/ES", ... },
      "drop":  ["hoja_normalizada", ...]
    }

Rules are evaluated **in order** and the *first* one that matches wins, so put
specific tropes/subgenres before generic genres.  Anything that is already in
canonical form (contains " · ") is kept untouched; unknown tags are preserved
so no information is lost, and reported so the map can be extended.

No Calibre dependencies: pure and unit-testable.
"""

import os
import re
import json
import logging
import unicodedata

logger = logging.getLogger('FIX_METADATA_PLUGIN')

_MAP_FILENAME = 'tags_map.json'
_CANON_SEP = ' · '     # marks an already-canonical "Grupo · Valor" tag

# Action codes returned by :func:`classify_tag`.
ACT_CANON   = 'canon'     # already canonical -> keep unchanged
ACT_MAPPED  = 'mapped'    # matched a trope/theme rule -> replaced
ACT_GENRE   = 'genre'     # matched a "Genero · X" rule -> replaced
ACT_DROP    = 'drop'      # junk -> removed
ACT_UNKNOWN = 'unknown'   # no rule -> kept as-is, flagged for review

# Path prefixes whose genre lives in the hierarchy, not the leaf.
_STRUCTURAL_GENRE_PREFIXES = ('biblioteca', 'libreria')


def _deacc(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s or '')
                   if unicodedata.category(c) != 'Mn')


def normalize_leaf(tag):
    """Normalised comparison key: last hierarchy segment, no accents/prefixes."""
    if not tag:
        return ''
    parts = [seg for seg in tag.split('.') if seg.strip()]
    leaf = parts[-1] if parts else tag
    leaf = _deacc(leaf).lower()
    # collapse every non-alphanumeric run (spaces, _, -, en/em dashes, /, (), +...)
    leaf = re.sub(r'[^0-9a-z]+', ' ', leaf)
    return leaf.strip()


def full_norm(tag):
    """Normalised form of the WHOLE tag (hierarchy included), for fallback
    matching when the leaf alone loses context (e.g. 'Historical
    Fiction.Modern.19th Century')."""
    if not tag:
        return ''
    t = _deacc(tag).lower()
    return re.sub(r'[^0-9a-z]+', ' ', t).strip()


def default_map_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), _MAP_FILENAME)


def _load_json_resource(name):
    """Load a bundled JSON regardless of how Calibre loaded the plugin.

    Calibre runs plugins from the installed ZIP with a custom loader whose
    ``__file__`` points *inside* the zip, so a plain ``open()`` raises
    FileNotFoundError.  Order: 1) user config dir (lets the user override the
    map without reinstalling)  2) pkgutil  3) the plugin's own zip via
    ``load_resources`` (the official Calibre API)  4) a file next to this
    module (running the tests outside Calibre).
    """
    # 1) user override in the Calibre config directory
    try:
        from calibre.utils.config import config_dir
        p = os.path.join(config_dir, name)
        if os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    # 2) data packaged with the plugin (pkgutil; not always available)
    try:
        import pkgutil
        pkg = __package__ or 'calibre_plugins.fix_metadata'
        data = pkgutil.get_data(pkg, name)
        if data:
            return json.loads(data.decode('utf-8'))
    except Exception:
        pass
    # 3) read straight from the installed plugin zip (reliable inside Calibre)
    try:
        from calibre.customize.ui import find_plugin
        plugin = find_plugin('Fix Metadata')
        if plugin is not None:
            data = plugin.load_resources([name]).get(name)
            if data:
                return json.loads(data.decode('utf-8'))
    except Exception:
        pass
    # 4) file next to this module (tests outside Calibre)
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, name), 'r', encoding='utf-8') as f:
        return json.load(f)


def load_tags_map(path=None):
    """Load and compile the tag map.

    Returns ``(rules, drop, drop_res)``: *rules* an ordered list of
    ``(canonical, compiled_regex)``, *drop* a set of normalised leaves, and
    *drop_res* a list of compiled regexes matched against the leaf.
    A missing/invalid file yields empty structures (the feature no-ops).
    """
    try:
        if path is not None:
            with open(path, encoding='utf-8') as f:
                raw = json.load(f)
        else:
            raw = _load_json_resource(_MAP_FILENAME)
    except Exception as e:
        logger.warning("No se pudo cargar %s: %s", _MAP_FILENAME, e)
        return [], set(), []

    rules = []
    for canon, pattern in (raw.get('rules') or {}).items():
        if not canon or not pattern:
            continue
        try:
            rules.append((canon, re.compile(_deacc(pattern), re.IGNORECASE)))
        except re.error as e:
            logger.warning("Regex inválida para %s: %s", canon, e)
    drop = {normalize_leaf(d) for d in (raw.get('drop') or []) if d}
    drop_res = []
    for pat in (raw.get('drop_patterns') or []):
        try:
            drop_res.append(re.compile(_deacc(pat), re.IGNORECASE))
        except re.error as e:
            logger.warning("drop_pattern inválido %r: %s", pat, e)
    return rules, drop, drop_res


def classify_tag(tag, rules, drop, drop_res=()):
    """Classify a single raw tag.

    Returns ``(action, value)``:
        ('canon',   tag)        already canonical, unchanged
        ('mapped',  canonical)  mapped to a trope/theme
        ('genre',   canonical)  mapped to a "Genero · X"
        ('drop',    None)       junk, remove
        ('unknown', tag)        no rule matched, keep as-is
    """
    t = (tag or '').strip()
    if not t:
        return (ACT_DROP, None)
    if _CANON_SEP in t:
        return (ACT_CANON, t)
    leaf = normalize_leaf(t)
    if not leaf:
        return (ACT_DROP, None)
    if leaf in drop:
        return (ACT_DROP, None)
    full = full_norm(t)
    for _dre in drop_res:
        if _dre.search(full):
            return (ACT_DROP, None)
    # Library/shelf prefixes (``_Biblioteca.<Genero>.<Subcat>`` etc.) carry the
    # genre in the PATH, not the leaf ("Contemporanea" as a leaf would mislead),
    # so for these we match the whole path and skip the leaf stage.
    first = full.split(' ', 1)[0]
    force_full = first in _STRUCTURAL_GENRE_PREFIXES
    if not force_full:
        # 1) precise match on the leaf (last hierarchy segment)
        for canon, rx in rules:
            if rx.search(leaf):
                act = ACT_GENRE if canon.startswith('Genero' + ' · ') else ACT_MAPPED
                return (act, canon)
    # 2) match on the full hierarchy (recovers genre/context from prefixes)
    if force_full or full != leaf:
        for canon, rx in rules:
            if rx.search(full):
                act = ACT_GENRE if canon.startswith('Genero' + ' · ') else ACT_MAPPED
                return (act, canon)
    return (ACT_UNKNOWN, t)


def clean_tags(raw_tags, rules, drop, drop_res=()):
    """Canonicalise a list of raw tags for one book.

    Returns ``(new_tags, info)`` where *new_tags* is the de-duplicated, sorted
    result and *info* is a dict with the per-book breakdown::

        {'unknown': [tags...], 'dropped': [tags...], 'changed': bool}

    ``new_tags`` preserves already-canonical and unknown tags (no data loss).
    """
    seen = set()
    new_tags = []
    unknown, dropped = [], []

    def _add(v):
        if v and v not in seen:
            seen.add(v)
            new_tags.append(v)

    for tag in raw_tags:
        act, val = classify_tag(tag, rules, drop, drop_res)
        if act == ACT_DROP:
            dropped.append(tag)
        elif act == ACT_UNKNOWN:
            unknown.append(val)
            _add(val)
        else:
            _add(val)

    new_tags.sort(key=lambda s: _deacc(s).lower())
    orig = [t.strip() for t in raw_tags if t and t.strip()]
    changed = new_tags != orig
    return new_tags, {'unknown': unknown, 'dropped': dropped, 'changed': changed}
