from __future__ import unicode_literals, division, absolute_import, print_function

__license__   = 'GPL v3'
__copyright__ = '2026, Fix Metadata Plugin'

import re

# Matches 2-3 consecutive uppercase letters as a standalone word (likely initials without dots)
# e.g. JK, JRR, but NOT KING (4 letters) or full surnames
_BARE_INITIALS = re.compile(r'(?<![A-Za-z])([A-Z]{2,3})(?![a-zA-Z])')


def fix_author(author):
    """
    Fix an author name string:

    1. "Apellido, Nombre"   → "Nombre Apellido"
       "García, Gabriel"    → "Gabriel García"
       "Tolkien, J.R.R."    → "J.R.R. Tolkien"

    2. Initials without spaces between dots:
       "J.K. Rowling"       → "J. K. Rowling"
       "J.R.R. Tolkien"     → "J. R. R. Tolkien"

    3. Initials without dots:
       "JK Rowling"         → "J. K. Rowling"
       "JRR Tolkien"        → "J. R. R. Tolkien"

    4. Dot not followed by space before next word:
       "J.K.Rowling"        → "J. K. Rowling"
    """
    if not author or not author.strip():
        return author

    author = author.strip()

    # --- Step 1: reverse "Apellido, Nombre" ---
    if ',' in author:
        parts = author.split(',', 1)
        apellido = parts[0].strip()
        nombre = parts[1].strip()
        if nombre:
            author = nombre + ' ' + apellido

    # --- Step 2: fix initials ---
    author = _fix_initials(author)

    return author.strip()


def _fix_initials(name):
    """Internal helper that normalises initials inside a name string."""

    # 2a. Expand bare consecutive uppercase letters → dotted initials
    #     JK → J. K.    JRR → J. R. R.
    def expand_bare(m):
        letters = list(m.group(1))
        return '. '.join(letters) + '.'

    name = _BARE_INITIALS.sub(expand_bare, name)

    # 2b. Add space between back-to-back dotted initials
    #     J.K. → J. K.    A.C. → A. C.
    #     Repeat until stable (handles J.R.R. in one pass via loop)
    prev = None
    while prev != name:
        prev = name
        name = re.sub(r'([A-Z]\.)([A-Z]\.)', r'\1 \2', name)

    # 2c. Add space when a dotted initial is directly followed by a surname
    #     J.Rowling → J. Rowling    K.Tolkien → K. Tolkien
    name = re.sub(r'([A-Z]\.)([A-Z][a-z])', r'\1 \2', name)

    # 2d. Add missing dot to a lone initial that is surrounded by spaces
    #     "J K Rowling" → "J. K. Rowling"
    #     Only single uppercase letters that are standalone tokens
    name = re.sub(r'(?<!\w)([A-Z])(?=\s)', r'\1.', name)

    return name


def would_fix_author(author):
    """Returns True if fix_author() would change this string."""
    if not author:
        return False
    return fix_author(author) != author
