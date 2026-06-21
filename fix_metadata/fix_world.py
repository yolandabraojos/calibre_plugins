from __future__ import unicode_literals, division, absolute_import, print_function

__license__   = 'GPL v3'
__copyright__ = '2026, Fix Metadata Plugin'

"""
Universe (#world) lookup from a curated series -> universe dictionary.

The mapping lives in ``world_map.json`` (next to this module) in the
human-friendly form ``{ "Universe Name": ["Series A", "Series B", ...] }``,
so it can be extended by hand without touching code.  At load time it is
flattened into a case-insensitive reverse index ``series -> universe``.

No Calibre dependencies: pure and unit-testable.
"""

import os
import json
import logging

logger = logging.getLogger('FIX_METADATA_PLUGIN')

_MAP_FILENAME = 'world_map.json'


def _key(series):
    """Normalised lookup key: lower-case, whitespace-collapsed."""
    return ' '.join((series or '').lower().split())


def default_map_path():
    """Absolute path to the bundled world_map.json (next to this file)."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), _MAP_FILENAME)


def load_world_map(path=None):
    """
    Load the universe map and return a reverse index ``{series_key: universe}``.

    Accepts the on-disk format ``{universe: [series, ...]}``.  Missing or
    invalid files yield an empty index (the feature simply does nothing rather
    than breaking the plugin).
    """
    if path is None:
        path = default_map_path()
    rev = {}
    try:
        with open(path, encoding='utf-8') as f:
            raw = json.load(f)
    except Exception as e:
        logger.warning("No se pudo cargar %s: %s", path, e)
        return rev
    for universe, series_list in (raw or {}).items():
        if not universe or not isinstance(series_list, (list, tuple)):
            continue
        for s in series_list:
            k = _key(s)
            if k:
                rev[k] = universe
    return rev


def world_for_series(series, rev_map):
    """Return the universe for *series* (case-insensitive) or None."""
    if not series or not rev_map:
        return None
    return rev_map.get(_key(series))
