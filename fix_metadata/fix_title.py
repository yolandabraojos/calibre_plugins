from __future__ import unicode_literals, division, absolute_import, print_function

__license__   = 'GPL v3'
__copyright__ = '2026, Fix Metadata Plugin'

import re


def clean_title(title, series=None, series_index=None, language=None):
    """
    Remove the series prefix and language suffix that were embedded in the title
    using the book's own metadata values.

    Expected title format:
        SeriesName [N] - Actual Title (lang)

    Where:
        - SeriesName  comes from mi.series
        - N           comes from mi.series_index
        - lang        comes from mi.language  (e.g. 'spa', 'eng')

    Returns just:
        Actual Title

    Falls back to a generic pattern when no metadata is available.

    Examples (with matching metadata):
        series="Dune", index=1, language="spa"
        "Dune [1] - Dune (spa)"  →  "Dune"

        series="Harry Potter", index=1, language="spa"
        "Harry Potter [1] - La Piedra Filosofal (spa)"  →  "La Piedra Filosofal"

        series="Discworld", index=1, language="eng"
        "Discworld [01] - The Colour of Magic (eng)"  →  "The Colour of Magic"
    """
    if not title:
        return title

    result = title.strip()

    # ------------------------------------------------------------------ #
    # Step 1 – strip language suffix  " (spa)"  /  " (eng)"              #
    # ------------------------------------------------------------------ #
    if language:
        # Use the actual code stored in metadata; case-insensitive
        lang_re = re.escape(language.strip())
    else:
        # Fall back: any 2-3 lower-case letter code at the very end
        lang_re = r'[a-zA-Z]{2,3}'

    result = re.sub(
        r'\s*\(' + lang_re + r'\)\s*$',
        '',
        result,
        flags=re.IGNORECASE,
    ).strip()

    # ------------------------------------------------------------------ #
    # Step 2 – strip series prefix  "SeriesName [N] - "                  #
    # ------------------------------------------------------------------ #
    if series:
        # Build a pattern anchored to the actual series name.
        # The index part is matched loosely (any content inside brackets)
        # to cope with zero-padding, decimal formatting, etc.
        series_esc = re.escape(series.strip())
        prefix_re  = r'^' + series_esc + r'\s*\[[^\]]+\]\s*-\s*'
        stripped   = re.sub(prefix_re, '', result, flags=re.IGNORECASE).strip()
        if stripped:          # only accept if something remains
            result = stripped
    else:
        # No series metadata – fall back to the generic heuristic:
        # strip everything up to and including the first "[…] - " block.
        generic = re.sub(r'^.+?\[[^\]]+\]\s*-\s*', '', result).strip()
        if generic and generic != result:
            result = generic

    return result


def would_clean_title(title, series=None, series_index=None, language=None):
    """Returns True if clean_title() would change this title."""
    if not title:
        return False
    return clean_title(title, series, series_index, language) != title.strip()
