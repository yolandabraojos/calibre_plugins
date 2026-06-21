from __future__ import unicode_literals, division, absolute_import, print_function

__license__   = 'GPL v3'
__copyright__ = '2026, Fix Metadata Plugin'

import re
import logging

logger = logging.getLogger('FIX_METADATA_PLUGIN')

# Matches a standard UUID: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)

# Valid Amazon ASIN: exactly 10 alphanumeric characters (uppercase letters + digits)
_ASIN_RE = re.compile(r'^[A-Z0-9]{10}$')

# Regional Amazon identifier keys that should be merged into 'amazon'
_AMAZON_REGIONAL = ('amazon_ca', 'amazon_es', 'amazon_uk')

# ISBN variant key patterns (case-insensitive):
#   isbn-13, isbn 13, isbn13, isbn_13, isbn-10, isbn 10, isbn10
_ISBN_VARIANT_SUFFIX_RE = re.compile(r'^isbn[-_ ]?1[03]$', re.IGNORECASE)
#   isbn<digits>  e.g. isbn0310861691  (isbn followed by 9-13 digits – the number itself)
_ISBN_VARIANT_NUMBER_RE = re.compile(r'^isbn[-_ ]?([0-9]{9,13})$', re.IGNORECASE)
#   urn:isbn, urnisbn/, urn-isbn:, urn_isbn/, urnisbn/9780007370740 …
_ISBN_URN_RE = re.compile(
    r'^urn[:\-_/]?isbn[/:\-_]?([0-9]*)$', re.IGNORECASE
)


def _is_valid_asin(value):
    return bool(_ASIN_RE.match(value.upper())) if value else False


def _normalize_isbn_value(value):
    """Strip a leading 'ISBN' literal (case-insensitive) from a value string."""
    v = value.strip()
    if v.upper().startswith('ISBN'):
        v = v[4:].strip('-_ /')
    return v or value.strip()


def _classify_isbn_variant(key):
    """
    Return (is_variant, suggested_value_override) for an identifier key.

    *suggested_value_override* is a non-empty string only when the correct
    ISBN digits are embedded in the key itself (e.g. 'isbn0310861691'),
    so the caller should use that instead of the stored value.
    Returns (False, None) when the key is not an ISBN variant.
    """
    k = key.strip()

    # Exact match – already canonical
    if k.lower() == 'isbn':
        return False, None

    # isbn-13 / isbn 13 / isbn13 / isbn-10 / isbn10 …
    if _ISBN_VARIANT_SUFFIX_RE.match(k):
        return True, None

    # isbn<digits>  – digits may be the actual ISBN embedded in the key
    m = _ISBN_VARIANT_NUMBER_RE.match(k)
    if m:
        return True, m.group(1)   # digits from key name

    # urn-style: urnisbn/9780007370740 or urn:isbn:9780007351619 …
    m = _ISBN_URN_RE.match(k)
    if m:
        embedded = m.group(1)     # digits after the slash/colon (may be empty)
        return True, embedded or None

    return False, None


def fix_identifiers(identifiers):
    """
    Apply all identifier-fixing rules to a calibre identifiers dict.

    Returns (new_identifiers, changes) where *changes* is a list of
    human-readable strings describing every modification made.

    Rules applied (in order):
    1.  asin / mobi-asin  →  copy to 'amazon' if missing, then delete them.
    2.  UUID-style keys/values (e.g. '246ad44a-…')  →  deleted.
    3.  key == value  (e.g. '9780007351619':'9780007351619')  →  'isbn':value.
    4.  amazon_ca / amazon_es / amazon_uk  →  merged into 'amazon' (first found
        wins when 'amazon' is absent), then deleted.
    5.  'amazon' key with invalid ASIN value  →  deleted.
    6.  Malformed ISBN keys  →  normalised to 'isbn':
        isbn-13, isbn 13, isbn13, isbn-10, isbn10,
        isbn<digits> (e.g. isbn0310861691:ISBN0310861691),
        urnisbn/<digits> and similar URN forms.
    """
    ids = dict(identifiers)   # work on a copy
    changes = []

    # ------------------------------------------------------------------ #
    # Rule 1 – asin / mobi-asin → amazon                                  #
    # ------------------------------------------------------------------ #
    for key in ('asin', 'mobi-asin'):
        if key in ids:
            value = ids[key]
            if 'amazon' not in ids:
                ids['amazon'] = value
                changes.append(f"Copied '{key}:{value}' → 'amazon:{value}'")
            del ids[key]
            changes.append(f"Removed '{key}:{value}'")

    # ------------------------------------------------------------------ #
    # Rule 4 – regional amazon variants → amazon                          #
    # (done before UUID/key==value so the value is preserved first)       #
    # ------------------------------------------------------------------ #
    for key in _AMAZON_REGIONAL:
        if key in ids:
            value = ids[key]
            if 'amazon' not in ids:
                ids['amazon'] = value
                changes.append(f"Promoted '{key}:{value}' → 'amazon:{value}'")
            del ids[key]
            changes.append(f"Removed '{key}:{value}'")

    # ------------------------------------------------------------------ #
    # Rule 2 – remove UUID-style identifiers                              #
    # ------------------------------------------------------------------ #
    uuid_keys = [k for k, v in ids.items() if _UUID_RE.match(k) or _UUID_RE.match(v)]
    for k in uuid_keys:
        changes.append(f"Removed UUID identifier '{k}:{ids[k]}'")
        del ids[k]

    # ------------------------------------------------------------------ #
    # Rule 3 – key == value  →  isbn:value                                #
    # ------------------------------------------------------------------ #
    # Collect separately to avoid mutating dict while iterating
    kv_equal = [(k, v) for k, v in ids.items() if k == v]
    for k, v in kv_equal:
        del ids[k]
        if 'isbn' not in ids:
            ids['isbn'] = v
            changes.append(f"Renamed '{k}:{v}' → 'isbn:{v}'")
        else:
            changes.append(f"Removed duplicate '{k}:{v}' (isbn:{ids['isbn']} kept)")

    # ------------------------------------------------------------------ #
    # Rule 5 – amazon with invalid ASIN → delete                          #
    # ------------------------------------------------------------------ #
    if 'amazon' in ids and not _is_valid_asin(ids['amazon']):
        changes.append(f"Removed invalid amazon ASIN '{ids['amazon']}'")
        del ids['amazon']

    # ------------------------------------------------------------------ #
    # Rule 6 – normalise malformed ISBN keys → isbn                       #
    # Covers: isbn-13, isbn 13, isbn13, isbn-10, isbn10,                  #
    #         isbn<digits> (e.g. isbn0310861691),                         #
    #         urnisbn/<digits> and similar URN forms.                      #
    # ------------------------------------------------------------------ #
    isbn_variants = [(k, v) for k, v in ids.items()
                     if _classify_isbn_variant(k)[0]]
    for k, stored_value in isbn_variants:
        _, embedded_digits = _classify_isbn_variant(k)

        # Determine the best ISBN value:
        # 1. digits embedded in the key name (most reliable for isbn<digits>)
        # 2. value after stripping any 'ISBN' prefix
        if embedded_digits:
            isbn_value = embedded_digits
        else:
            isbn_value = _normalize_isbn_value(stored_value)

        del ids[k]

        if 'isbn' not in ids:
            ids['isbn'] = isbn_value
            changes.append(f"Renamed '{k}:{stored_value}' → 'isbn:{isbn_value}'")
        else:
            # isbn already present – just drop the duplicate variant
            changes.append(f"Removed duplicate ISBN variant '{k}:{stored_value}' "
                           f"(isbn:{ids['isbn']} kept)")

    return ids, changes
