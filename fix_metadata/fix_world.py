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


def _load_json_resource(name):
    """Load a bundled JSON regardless of how Calibre loaded the plugin.

    Calibre runs plugins from the installed ZIP with a loader whose __file__
    points inside the zip, so a plain open() fails.  Order: config dir (user
    override), pkgutil, the plugin zip via load_resources, then a local file.
    """
    try:
        from calibre.utils.config import config_dir
        p = os.path.join(config_dir, name)
        if os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    try:
        import pkgutil
        pkg = __package__ or 'calibre_plugins.fix_metadata'
        data = pkgutil.get_data(pkg, name)
        if data:
            return json.loads(data.decode('utf-8'))
    except Exception:
        pass
    try:
        from calibre.customize.ui import find_plugin
        plugin = find_plugin('Fix Metadata')
        if plugin is not None:
            data = plugin.load_resources([name]).get(name)
            if data:
                return json.loads(data.decode('utf-8'))
    except Exception:
        pass
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, name), 'r', encoding='utf-8') as f:
        return json.load(f)


def load_world_map(path=None):
    """
    Load the universe map and return a reverse index ``{series_key: universe}``.

    Accepts the on-disk format ``{universe: [series, ...]}``.  Missing or
    invalid files yield an empty index (the feature simply does nothing rather
    than breaking the plugin).
    """
    rev = {}
    try:
        if path is not None:
            with open(path, encoding='utf-8') as f:
                raw = json.load(f)
        else:
            raw = _load_json_resource(_MAP_FILENAME)
    except Exception as e:
        logger.warning("No se pudo cargar %s: %s", _MAP_FILENAME, e)
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
