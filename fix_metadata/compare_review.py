#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Reusable wrapper around calibre's native CompareMany review dialog.
#
# Instead of the plugin's bespoke QTableWidget review dialogs, the "Fix ..."
# actions build, for every affected book, a proposed Metadata object (`newmi`)
# and hand the batch to CompareMany: the same side-by-side "original vs
# proposed" review that Smart Metadata uses.  The user can edit, revert,
# accept-all or reject per book, then we apply only what was accepted.
from __future__ import unicode_literals, division, absolute_import, print_function

__license__   = 'GPL v3'
__copyright__ = '2026, Fix Metadata Plugin'

import logging

logger = logging.getLogger('FIX_METADATA_PLUGIN')

try:
    from qt.core import QDialog
except Exception:
    from PyQt5.Qt import QDialog


def review_changes(gui, db, proposals, fields,
                   window_title='Review changes', intro_msg=None):
    """Show CompareMany for a batch of proposed metadata changes.

    Parameters
    ----------
    gui : the calibre GUI (parent widget).
    db  : ``gui.current_db`` (legacy DB; exposes ``field_metadata``/``new_api``).
    proposals : ordered mapping ``{book_id: newmi}`` where *newmi* is the
        proposed :class:`Metadata` (a copy of the current metadata with the
        changed fields applied).  Order is preserved in the dialog.
    fields : tuple of field names to display in the diff, e.g.
        ``('title', 'series', 'languages')`` or ``('title', '#subtitle')``.
        Custom columns are supported as long as they exist in
        ``db.field_metadata``.
    window_title, intro_msg : strings shown in the dialog.

    Returns
    -------
    ``(accepted, rejected)`` where

    * ``accepted`` is an ``OrderedDict`` ``{book_id: mi}`` with the merged
      metadata the caller should write (only books the user accepted), or
      ``None`` if the whole dialog was cancelled.
    * ``rejected`` is a ``set`` of book ids the user explicitly rejected (for
      optional "mark for review"), or ``None`` when cancelled.
    """
    from collections import OrderedDict
    from calibre.gui2.metadata.diff import CompareMany

    ids = [bid for bid in proposals.keys()]
    if not ids:
        return OrderedDict(), set()

    def get_metadata(book_id):
        # CompareMany calls this per book and expects (oldmi, newmi).
        oldmi = db.get_metadata(book_id, index_is_id=True,
                                get_user_categories=False)
        return oldmi, proposals[book_id]

    d = CompareMany(
        ids, get_metadata, db.field_metadata, parent=gui,
        window_title=window_title,
        intro_msg=intro_msg,
        reject_button_tooltip='Reject the proposed changes for this book',
        accept_all_tooltip='Accept the proposed changes for all remaining books',
        reject_all_tooltip='Reject the proposed changes for all remaining books',
        revert_tooltip='Revert the proposed value for: %s',
        db=db, fields=fields,
    )
    # CompareMany always sizes itself to (almost) fill the screen -- see
    # calibre's gui2/metadata/diff.py, which picks a height between 650 and
    # 1000px regardless of how many fields are being compared. With just a
    # couple of one-line fields (our case: title/series/languages or
    # title/#subtitle) that leaves a big empty gap under the fields. Clamp
    # the height to something proportional to the number of fields so the
    # dialog doesn't look half-empty. Only ever shrinks; never grows past
    # whatever calibre/the user already sized it to.
    try:
        compact_height = 260 + 110 * len(fields)
        if d.height() > compact_height:
            d.resize(d.width(), compact_height)
    except Exception:
        logger.debug('Could not resize CompareMany dialog', exc_info=True)
    try:
        accepted_ok = (d.exec() == QDialog.DialogCode.Accepted)
    except AttributeError:
        # Older Qt binding without DialogCode enum.
        accepted_ok = (d.exec() == QDialog.Accepted)

    if not accepted_ok:
        return None, None

    acc = getattr(d, 'accepted_map', None)
    if acc is None:
        acc = getattr(d, 'accepted', {}) or {}

    accepted = OrderedDict()
    for book_id, pair in acc.items():
        try:
            _changed, mi = pair
        except Exception:
            continue
        # mi is None  -> the user rejected this book.
        # mi not None  -> accepted (with or without further manual edits);
        #                 apply it as-is so any in-dialog edit is honoured.
        if mi is not None:
            accepted[book_id] = mi

    rejected = set(getattr(d, 'rejected_ids', set()) or set())
    # Belt and braces: anything not accepted counts as rejected.
    for bid in ids:
        if bid not in accepted:
            rejected.add(bid)
    return accepted, rejected
