#!/usr/bin/env python
# -*- coding: utf-8 -*-
# GoodreadsFast - calibre metadata source plugin
# Searches Goodreads via the live autocomplete endpoint (works without ISBN)
# Based on the "Goodreads" plugin by Grant Drake (GPL v3).
from __future__ import unicode_literals, division, absolute_import, print_function

__license__ = 'GPL v3'
__copyright__ = '2026, Yolanda Braojos'

import time, json, re, math
try:
    from urllib.parse import quote
except ImportError:
    from urllib import quote
try:
    from queue import Empty, Queue
except ImportError:
    from Queue import Empty, Queue

from calibre import as_unicode
from calibre.ebooks import normalize
from calibre.ebooks.metadata import check_isbn
from calibre.ebooks.metadata.sources.base import Source, fixcase, fixauthors
from calibre.utils.icu import lower


class GoodreadsFast(Source):

    name = 'Goodreads Fast'
    description = ('Downloads metadata and covers from Goodreads using the live '
                  'autocomplete search. Finds books by title/author even without ISBN.')
    author = 'Yolanda Braojos (based on Goodreads by Grant Drake)'
    version = (1, 8, 10)
    minimum_calibre_version = (2, 0, 0)

    capabilities = frozenset(['identify', 'cover'])
    touched_fields = frozenset(['title', 'authors', 'identifier:goodreads',
        'identifier:isbn', 'rating', 'comments', 'publisher', 'pubdate',
        'tags', 'series', 'languages'])
    has_html_comments = True
    supports_gzip_transfer_encoding = True

    ID_NAME = 'goodreads'
    BASE_URL = 'https://www.goodreads.com'
    AUTOCOMPLETE_URL = 'https://www.goodreads.com/book/auto_complete?format=json&q='
    MIN_MATCH_SCORE = 4.0   # reject weak matches so a bad query variant falls through
    MAX_SEARCH_QUERIES = 8  # cap autocomplete requests when fanning out variants

    # Titles that are not the actual book edition we want.
    #
    # NOTE: " / " used to be in this list, on the assumption that a
    # slash-joined title always means an unrelated bundle of separately
    # catalogued books. That is wrong for a whole genre: category-romance
    # 3-in-1 anthologies (Harlequin/Mills & Boon and similar) are legitimately
    # catalogued on Goodreads as a single book whose own title is exactly
    # "Umbrella Title: Story One / Story Two / Story Three" -- e.g. "Royals:
    # For Their Royal Heir: An Heir Fit for a King / The Pregnant Princess /
    # The Prince's Secret Baby". The blanket marker rejected that candidate
    # before it was ever scored, even though its head segment ("Royals")
    # matched the query exactly. The title-similarity gate already rejects a
    # real mismatch on its own merits, so the marker was pure downside.
    JUNK_MARKERS = ('bundle', 'box set', 'boxset', 'boxed set', 'reading list',
        'guia de lectura', 'guía de lectura', 'resumen y', 'study guide',
        'summary of', 'summary and', 'sparknotes', 'omnibus', 'collection',
        'audiobook bundle', 'cliffsnotes')

    # Parentheticals naming a series or its index -- stripped from titles before
    # matching (e.g. "(Harry Potter, #2)", "(Dune Chronicles Book 1)"). Plain
    # volume notes like "(Part Two)" carry none of these markers and are kept.
    _SERIES_PAREN_RE = re.compile(
        r'[\(\[\{][^)\]}]*'
        r'(?:#|,|\bbook\b|\bvol\b|\bvolume\b|\bseries\b|\bserie\b|\bsaga\b|'
        r'\bcycle\b|\btrilog\w*|\bduolog\w*|\btome\b|\btomo\b|\blibro\b|'
        r'\blivre\b|\bband\b|\breihe\b|\bn[oº]\b|nº)'
        r'[^)\]}]*[\)\]\}]', re.IGNORECASE)

    @property
    def user_agent(self):
        try:
            from calibre.utils.random_ua import random_common_chrome_user_agent
            return random_common_chrome_user_agent()
        except Exception:
            return ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

    # ---------- calibre Source boilerplate ----------

    def get_book_url(self, identifiers):
        goodreads_id = identifiers.get(self.ID_NAME, None)
        if goodreads_id:
            return ('goodreads', goodreads_id,
                    '%s/book/show/%s' % (self.BASE_URL, goodreads_id))

    def id_from_url(self, url):
        match = re.match(self.BASE_URL + r"/book/show/(\d+).*", url)
        if match:
            return (self.ID_NAME, match.groups(0)[0])
        return None

    def get_details_url(self, goodreads_id):
        # The extensionless book page is behind AWS WAF; the .xml URL serves the
        # same Next.js page including the __NEXT_DATA__ json we parse.
        return '%s/book/show/%s.xml' % (self.BASE_URL, goodreads_id)

    def get_cached_cover_url(self, identifiers):
        url = None
        goodreads_id = identifiers.get(self.ID_NAME, None)
        if goodreads_id is None:
            isbn = identifiers.get('isbn', None)
            if isbn is not None:
                goodreads_id = self.cached_isbn_to_identifier(isbn)
        if goodreads_id is not None:
            url = self.cached_identifier_to_cover_url(goodreads_id)
        return url

    def clean_downloaded_metadata(self, mi):
        docase = mi.language == 'eng' or mi.is_null('language')
        if docase and mi.title:
            mi.title = fixcase(mi.title)
        mi.authors = fixauthors(mi.authors)
        mi.isbn = check_isbn(mi.isbn)

    # ---------- autocomplete search ----------

    def _autocomplete(self, log, query_text, timeout):
        url = self.AUTOCOMPLETE_URL + quote(query_text.encode('utf-8'))
        log.info('Autocomplete query: %s' % url)
        try:
            raw = self.browser.open_novisit(url, timeout=timeout).read()
        except Exception:
            log.exception('Autocomplete request failed for: %s' % url)
            return []
        if not raw:
            return []
        try:
            return json.loads(raw)
        except Exception:
            log.exception('Failed to parse autocomplete JSON')
            return []

    _NUM_WORDS = frozenset((
        'one two three four five six seven eight nine ten eleven twelve '
        'first second third fourth fifth sixth seventh eighth ninth tenth '
        'eleventh twelfth').split())

    # Words that only ever name a volume/part/edition, never real title
    # content. A segment made up entirely of these (plus numbers/ordinals) --
    # e.g. "Volume Two", "Book 3" -- must not be trusted as a standalone exact
    # match: many unrelated books from the very same (or a different) author
    # reuse the identical omnibus/part label.
    _VOLUME_WORDS = frozenset((
        'volume vol book part tome tomo libro band edition installment '
        'omnibus').split())

    # Canonical digit form for every word in _NUM_WORDS, so "two" and "2" (or
    # "second" and "2") compare equal regardless of which way Goodreads or the
    # query happens to spell a volume/part number.
    _NUM_WORD_TO_DIGIT = dict(zip(
        'one two three four five six seven eight nine ten eleven twelve '
        'first second third fourth fifth sixth seventh eighth ninth tenth '
        'eleventh twelfth'.split(),
        ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12'] * 2))

    def _number_tokens(self, text):
        # Extract number/ordinal tokens from the RAW title string. We must not
        # use get_title_tokens here: calibre strips parenthesised text, so a
        # title like "... (Part Two)" would lose the distinguishing "two".
        # Every match is normalized to a canonical digit string (see
        # _NUM_WORD_TO_DIGIT) so different spellings of the same number never
        # look like a mismatch.
        out = set()
        for t in re.split(r'[^0-9a-z]+', (text or '').lower()):
            if not t:
                continue
            if t.isdigit():
                out.add(str(int(t)))
            elif t in self._NUM_WORD_TO_DIGIT:
                out.add(self._NUM_WORD_TO_DIGIT[t])
            else:
                # Ordinal abbreviations glued to their digits: "2nd" -> "2",
                # "3rd" -> "3", "21st" -> "21". calibre never splits these off,
                # so without this branch a query like "The 2nd Life" would carry
                # no number token and could not disambiguate against an unrelated
                # "The Second Life".
                mo = re.match(r'^(\d+)(?:st|nd|rd|th)$', t)
                if mo:
                    out.add(str(int(mo.group(1))))
        return out

    def _is_structural_segment(self, tokens):
        """True if a token set carries no real title content -- just a
        volume/part label like {"volume","two"} or {"book","3"}."""
        if not tokens:
            return True
        return all(t in self._VOLUME_WORDS or t in self._NUM_WORDS or t.isdigit()
                    for t in tokens)

    def _strip_series_paren(self, text):
        """Remove a parenthetical that names a series or gives its index, so it
        does not distort title matching. Plain "(Part Two)" notes are kept."""
        if not text:
            return text
        return self._SERIES_PAREN_RE.sub(' ', text)

    def _deparen_inline(self, title):
        """Remove only the bracket CHARACTERS of parentheticals that are glued to
        a word (e.g. "(Un)Lucky" -> "UnLucky") and contain no digits, so the
        query keeps them. Spaced/series parentheticals ("(Series, #2)") are left
        for the later bracket-strip step."""
        if not title:
            return title
        out = []
        i = 0
        for m in re.finditer(r'[\(\[\{]([^)\]}]*)[\)\]\}]', title):
            out.append(title[i:m.start()])
            inner = m.group(1)
            prev = title[m.start() - 1] if m.start() > 0 else ' '
            nxt = title[m.end()] if m.end() < len(title) else ' '
            if not re.search(r'[0-9#]', inner) and (prev.isalnum() or nxt.isalnum()):
                out.append(inner)          # glue: keep inner letters, drop brackets
            else:
                out.append(m.group(0))     # keep as-is (series/edition); stripped later
            i = m.end()
        out.append(title[i:])
        return ''.join(out)

    def _clean_query_title(self, title, strip_subtitle):
        if not title:
            return ''
        t = normalize(title)
        t = self._deparen_inline(t)
        t = re.sub(r'[\(\[\{][^)\]}]*[\)\]\}]', ' ', t)   # drop remaining (series) brackets
        if strip_subtitle:
            head = re.split(r'\s*:\s*', t, 1)[0]
            if len(head.strip()) >= 3:
                t = head
        t = t.replace("'", '').replace('\u2019', '')          # glue apostrophes
        t = re.sub(r'[^0-9A-Za-z]+', ' ', t)                   # other punctuation -> space
        return ' '.join(t.split())

    def _clean_author(self, authors):
        if not authors:
            return ''
        a = authors[0].replace("'", '').replace('\u2019', '')
        a = re.sub(r'[^0-9A-Za-z]+', ' ', a)
        return ' '.join(a.split())

    def _title_cores(self, title):
        """Candidate title strings to search: the head segment, the tail segment
        and the whole title. Handles messy calibre titles where the real title
        may be BEFORE or AFTER separators like ':' or ' - ' (e.g. a series prefix
        such as "Fate of Wizardoms - Wizardoms: Rise of a Wizard Queen")."""
        full = self._clean_query_title(title, False)
        segs = re.split(r'\s*:\s*|\s+[-\u2013\u2014]\s+', normalize(title or ''))
        segs = [self._clean_query_title(x, False) for x in segs]
        segs = [x for x in segs if len(x) >= 3]
        cores = []
        def add(x):
            if x and x not in cores:
                cores.append(x)
        if segs:
            add(segs[0])            # head (usual case: title first)
        if len(segs) > 1:
            add(segs[-1])           # tail (series-prefixed titles)
        for mid in segs[1:-1]:      # middle segments: the real title may be
            add(mid)                # buried between a series prefix and a suffix
        add(full)                   # everything, as a last resort
        return cores

    def _author_variants(self, authors):
        """Ordered author query strings: the primary author first, then each of
        the other authors on its own. Lets a book credited to several authors
        still be found when Goodreads lists only one of them."""
        variants = []
        def add(a):
            a = ' '.join((a or '').split())
            if a and a not in variants:
                variants.append(a)
        if authors:
            add(' '.join(self.get_author_tokens([authors[0]])))
            for au in authors[1:]:
                add(' '.join(self.get_author_tokens([au])))
        if not variants:
            variants.append('')
        return variants

    def _query_variants(self, title, authors):
        """Ordered, de-duplicated autocomplete query strings, best first.

        1. Subtitle-stripped title (head core) + primary author.
        2. Other title cores (tail / full) + primary author.
        3. Retries when nothing matches: title cores alone, then title + each
           of the OTHER authors, then a progressively shorter title, so a book
           with a long/complex title or several authors is still found."""
        author_variants = self._author_variants(authors)
        primary_author = author_variants[0]
        cores = self._title_cores(title)     # head (subtitle stripped) is first
        variants = []
        def add(q):
            q = ' '.join((q or '').split())
            if q and q not in variants:
                variants.append(q)
        # 1 & 2: each title core with the primary author.
        for core in cores:
            add((core + ' ' + primary_author) if primary_author else core)
        # 3a: title cores alone (drop the author entirely).
        if primary_author:
            for core in cores:
                add(core)
        # 3b: retry with each of the other authors, simplest title first.
        for au in author_variants[1:]:
            for core in cores:
                add(core + ' ' + au)
        # 3c: progressively simplified head title (first few words).
        head = cores[0] if cores else self._clean_query_title(title, True)
        words = head.split()
        for n in (4, 3, 2):
            if len(words) > n:
                short = ' '.join(words[:n])
                add((short + ' ' + primary_author) if primary_author else short)
                add(short)
        return variants

    def _author_token_set(self, authors):
        """Set of lowercased tokens across ALL query authors."""
        toks = set()
        if authors:
            for a in authors:
                for t in self.get_author_tokens([a]):
                    toks.add(lower(t))
        return toks

    def _title_core_sets(self, title):
        """Token set for each query title core (head / tail / middle / full)."""
        sets = []
        for core in self._title_cores(title):
            s = frozenset(lower(t) for t in self.get_title_tokens(core, strip_subtitle=False))
            if s and s not in sets:
                sets.append(s)
        return sets

    def _cand_title_variants(self, bare_ns):
        """Token set for each candidate title segment: head (subtitle
        stripped), tail, any middle segment, and the full bare title.
        Goodreads often folds a subtitle into bookTitleBare (e.g. "Foo: 50
        Loving States, Wisconsin", or a series name glued in front like
        "Series - Volume 2: Subtitle"), which would otherwise make a real
        match look weak against a short query core -- letting an unrelated,
        wrongly-authored but identically-titled book win via the
        unconditional "exact" gate."""
        segs = re.split(r'\s*:\s*|\s+[-\u2013\u2014]\s+', bare_ns or '')
        segs = [s.strip() for s in segs if len(s.strip()) >= 3]
        variants = []
        seen = set()
        def add(s, allow_structural=True):
            # Glue apostrophes exactly like _clean_query_title does for the
            # query side ("She's" -> "Shes"). calibre's get_title_tokens does
            # NOT split on/strip an internal apostrophe, so without this the
            # query token "shes" never equals the candidate token "she's" and
            # an otherwise-perfect match loses enough similarity to miss the
            # acceptance gate.
            s_glued = (s or '').replace("'", '').replace('\u2019', '')
            toks = frozenset(lower(t) for t in self.get_title_tokens(s_glued, strip_subtitle=False))
            if not toks or toks in seen:
                return
            if not allow_structural and self._is_structural_segment(toks):
                return
            seen.add(toks)
            variants.append(toks)
        if segs:
            add(segs[0], allow_structural=False)          # head
            if len(segs) > 1:
                add(segs[-1], allow_structural=False)      # tail
            for mid in segs[1:-1]:                          # any segment(s)
                add(mid, allow_structural=False)            # in between
        add(bare_ns)
        return variants

    def _title_similarity(self, core_sets, cand_variants):
        """Best overlap of any candidate title segment with any query core.
        sim = |intersection| / max(len(core), len(cand)); exact = a core equals
        the segment's token set. On a tie, the larger/more complete segment
        wins (more specific, e.g. prefer the full title over a bare head)."""
        best_key = (False, 0.0, 0)
        for cand_set in cand_variants:
            if not cand_set:
                continue
            for core in core_sets:
                inter = len(core & cand_set)
                if not inter:
                    continue
                sim = inter / float(max(len(core), len(cand_set)))
                key = (core == cand_set, sim, len(cand_set))
                if key > best_key:
                    best_key = key
        return best_key[1], best_key[0]

    def _author_similarity(self, qa_tokens, aname):
        """Fraction of the candidate author's tokens present among the query
        authors: a shared surname alone scores low, a full-name match scores 1."""
        cand = [lower(t) for t in self.get_author_tokens([aname])] if aname else []
        if not cand or not qa_tokens:
            return 0.0
        return sum(1 for t in cand if t in qa_tokens) / float(len(cand))

    def _match_of(self, cand, core_sets, qa_tokens):
        """(title_similarity, exact, author_similarity) for one candidate."""
        bare = cand.get('bookTitleBare') or cand.get('title') or ''
        aname = ((cand.get('author') or {}).get('name')) or ''
        cand_variants = self._cand_title_variants(self._strip_series_paren(bare))
        tsim, exact = self._title_similarity(core_sets, cand_variants)
        return tsim, exact, self._author_similarity(qa_tokens, aname)

    def _rank_candidates(self, log, results, title, authors):
        """Score every autocomplete candidate; return [(score, cand)] desc.

        Title similarity is the PRIMARY signal. The author is a strong bonus but
        never a hard veto: collaborative works and pen names are often credited
        to a different author on Goodreads, so a book must not be discarded just
        because the author field differs. A candidate is accepted only when its
        title clearly matches, so a coincidental shared surname cannot pull in an
        unrelated book (e.g. "A Farewell to Arfs" by Spencer Quinn for a query of
        "A Farewell to Charms" by Kate Karyus Quinn)."""
        core_sets = self._title_core_sets(title)
        qa_tokens = self._author_token_set(authors)
        q_nums = self._number_tokens(self._strip_series_paren(title))
        q_lower = lower(title or '')
        active_junk = tuple(j for j in self.JUNK_MARKERS if j not in q_lower)

        scored = []
        for r in results:
            try:
                bare = r.get('bookTitleBare') or r.get('title') or ''
                aname = ((r.get('author') or {}).get('name')) or ''
            except Exception:
                continue
            if aname == 'NOT A BOOK':
                continue
            if any(j in lower(bare) for j in active_junk):
                continue
            bare_ns = self._strip_series_paren(bare)
            cand_variants = self._cand_title_variants(bare_ns)
            tsim, exact = self._title_similarity(core_sets, cand_variants)
            amatch = self._author_similarity(qa_tokens, aname)

            # Acceptance gate: a (near-)exact title, or a good title backed by a
            # matching author. Weak title overlap is always rejected.
            if not (exact or tsim >= 0.85 or (amatch >= 0.5 and tsim >= 0.7)):
                continue

            score = tsim * 10.0
            if exact:
                score += 6.0
            score += 4.0 * amatch
            # Volume/part disambiguation: only a real conflict is penalized --
            # both sides name a number and they disagree (e.g. query "Book 2"
            # vs candidate "Book One"). A number present on only one side is
            # not a conflict and must not be penalized (e.g. an unrelated "50"
            # baked into a Goodreads subtitle the query never mentions).
            c_nums = self._number_tokens(bare_ns)
            if q_nums and c_nums and not (q_nums & c_nums):
                score -= 6.0
            try:
                rc = int(r.get('ratingsCount') or 0)
            except Exception:
                rc = 0
            # Popularity only reinforces an already-decent title match; it must
            # never rescue a weak one.
            if tsim >= 0.7 and rc > 0:
                score += min(2.0, math.log10(rc + 1))
            elif rc <= 0:
                score -= 1.0

            log.info('candidate id=%s score=%.2f tsim=%.2f amatch=%.2f rc=%s title=%r'
                     % (r.get('bookId'), score, tsim, amatch, rc, bare))
            if score >= self.MIN_MATCH_SCORE:
                scored.append((score, r))

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored

    def _same_book(self, cand, target_cand, target_workid):
        """True if cand is an edition of the SAME book as target: same work
        (by workId when available) AND same normalised title + number tokens
        (so we never cross into a different-language edition or a bundle)."""
        aname = ((cand.get('author') or {}).get('name')) or ''
        if aname == 'NOT A BOOK':
            return False
        bare = cand.get('bookTitleBare') or cand.get('title') or ''
        tbare = target_cand.get('bookTitleBare') or target_cand.get('title') or ''
        # Allow junk markers the target book's own title carries (a bundle is a
        # valid sibling edition when the target itself is that bundle).
        active_junk = tuple(j for j in self.JUNK_MARKERS if j not in lower(tbare))
        if any(j in lower(bare) for j in active_junk):
            return False
        same_title = (
            ' '.join(lower(t) for t in self.get_title_tokens(bare, strip_subtitle=True))
            == ' '.join(lower(t) for t in self.get_title_tokens(tbare, strip_subtitle=True))
            and self._number_tokens(bare) == self._number_tokens(tbare))
        wid = cand.get('workId')
        if target_workid and wid:
            return wid == target_workid and same_title
        return same_title

    def _edition_group(self, target_cand, pool_order, max_editions=3):
        """Ids of up to N editions of the same book as target_cand, target first.
        pool_order is a list of (bookId, candidate) in preference order."""
        target_workid = target_cand.get('workId')
        tid = target_cand.get('bookId')
        ids = [tid] if tid else []
        for bid, cand in pool_order:
            if len(ids) >= max_editions:
                break
            if bid in ids:
                continue
            if self._same_book(cand, target_cand, target_workid):
                ids.append(bid)
        return ids

    def _gather(self, log, abort, title, authors, timeout):
        """Query several autocomplete variants for one (title, authors) reading,
        accumulate the distinct candidates and return them ranked best-first.
        Stops early on a STRONG match (near-exact title + matching author)."""
        core_sets = self._title_core_sets(title)
        qa_tokens = self._author_token_set(authors)
        raw_pool = []
        raw_seen = set()
        nq = 0
        for qt in self._query_variants(title, authors):
            if abort.is_set():
                break
            if not qt:
                continue
            res = self._autocomplete(log, qt, timeout)
            nq += 1
            if res:
                for c in res:
                    bid = c.get('bookId')
                    if bid and bid not in raw_seen:
                        raw_seen.add(bid)
                        raw_pool.append(c)
                ranked = self._rank_candidates(log, raw_pool, title, authors)
                if ranked:
                    tsim, exact, amatch = self._match_of(ranked[0][1], core_sets, qa_tokens)
                    if (exact or tsim >= 0.95) and amatch >= 0.5:
                        break
            if nq >= self.MAX_SEARCH_QUERIES:
                break
        return self._rank_candidates(log, raw_pool, title, authors)

    def _search_ids(self, log, abort, title, authors, identifiers, timeout):
        """Return a list of goodreads ids (editions of the one book), best first.
        Gathers autocomplete candidates across several query variants and picks
        the globally best-matching book, so a weak/wrong early hit cannot lock in
        the result. ISBN, when present, pins the exact book -- but only once its
        OWN title/author actually agree with what we are looking for; a
        misattributed or mistyped ISBN must not silently override a real
        title+author match. If nothing matches, retries once with the title
        and author fields SWAPPED (some libraries store them the wrong way
        round)."""
        isbn = check_isbn(identifiers.get('isbn', None))

        pool = []          # list of (bookId, candidate) in preference order
        seen = set()
        def add(cand):
            bid = cand.get('bookId')
            if bid and bid not in seen:
                seen.add(bid)
                pool.append((bid, cand))

        isbn_cand = None

        # 1. ISBN query finds a candidate. It only pins the edition once its
        #    own title/author agree with the query -- the same acceptance gate
        #    used everywhere else. Goodreads ISBN data (or the source file's
        #    own ISBN) is sometimes simply wrong for a different book.
        if isbn:
            if abort.is_set():
                return []
            res = self._autocomplete(log, isbn, timeout)
            if res:
                for c in res:
                    add(c)
                core_sets = self._title_core_sets(title)
                qa_tokens = self._author_token_set(authors)
                tsim, exact, amatch = self._match_of(res[0], core_sets, qa_tokens)
                if exact or tsim >= 0.85 or (amatch >= 0.5 and tsim >= 0.7):
                    isbn_cand = res[0]
                else:
                    log.info('ISBN %s resolved to %r but the title/author do '
                              'not match (tsim=%.2f amatch=%.2f) -- ignoring '
                              'the ISBN pin and searching by title instead'
                              % (isbn, res[0].get('bookTitleBare'), tsim, amatch))

        # 2. Normal search; if it finds nothing, retry with title <-> author
        #    swapped. The strict title gate keeps the swapped retry from pulling
        #    in unrelated books, so it is a safe last resort.
        attempts = [(title, authors)]
        if title and authors:
            attempts.append((' '.join(authors), [title]))
        ranked = []
        for atitle, aauthors in attempts:
            if abort.is_set():
                return []
            ranked = self._gather(log, abort, atitle, aauthors, timeout)
            if ranked:
                title, authors = atitle, aauthors
                break

        for _, c in ranked:
            add(c)

        # 3. Decide the target book: a title-confirmed ISBN hit wins outright;
        #    otherwise the best title match. An ISBN hit whose title didn't
        #    agree is NOT used as a last-resort guess -- an honest "no match"
        #    is better than a confidently wrong one.
        if isbn_cand is not None:
            target_cand = isbn_cand
        elif ranked:
            target_cand = ranked[0][1]
        else:
            return []

        group = self._edition_group(target_cand, pool)
        log.info('edition group for %r: %s'
                 % (target_cand.get('bookTitleBare'), group))
        return group

    def identify(self, log, result_queue, abort, title=None, authors=None,
                 identifiers={}, timeout=30):
        log.debug('identify - title=%s, authors=%s, identifiers=%s'
                  % (title, authors, identifiers))
        goodreads_id = identifiers.get(self.ID_NAME, None)
        if goodreads_id:
            ids = [goodreads_id]
        else:
            try:
                ids = self._search_ids(log, abort, title, authors, identifiers, timeout)
            except Exception as e:
                log.exception('Goodreads search failed')
                return as_unicode(e)

        if not ids:
            log.error('No Goodreads match for title=%r authors=%r' % (title, authors))
            return
        if abort.is_set():
            return

        matches = [self.get_details_url(i) for i in ids]
        log.info('Fetching %d edition(s): %s' % (len(matches), ids))

        from calibre_plugins.goodreads_fast.worker import Worker
        temp_queue = Queue()
        workers = [Worker(url, temp_queue, self.browser, log, i, self)
                   for i, url in enumerate(matches)]
        for w in workers:
            w.start()
            time.sleep(0.1)
        while not abort.is_set():
            alive = False
            for w in workers:
                w.join(0.2)
                if abort.is_set():
                    break
                if w.is_alive():
                    alive = True
            if not alive:
                break
        if abort.is_set():
            return

        results = []
        while True:
            try:
                results.append(temp_queue.get_nowait())
            except Empty:
                break
        if not results:
            return

        # When several editions of the same book were fetched, prefer the one
        # with the richest description (then a cover). Emit all so the user can
        # still choose in single-book mode.
        def richness(mi):
            clen = len(mi.comments) if getattr(mi, 'comments', None) else 0
            cover = 1 if getattr(mi, 'has_cover', False) else 0
            return (clen, cover)
        results.sort(key=richness, reverse=True)
        for idx, mi in enumerate(results):
            mi.source_relevance = idx
            result_queue.put(mi)
        if len(results) > 1:
            log.info('Emitted %d editions; best comments len=%d'
                     % (len(results), len(results[0].comments or '')))
        return None

    def download_cover(self, log, result_queue, abort,
                       title=None, authors=None, identifiers={}, timeout=30, get_best_cover=False):
        cached_url = self.get_cached_cover_url(identifiers)
        if cached_url is None:
            log.info('No cached cover found, running identify')
            rq = Queue()
            self.identify(log, rq, abort, title=title, authors=authors, identifiers=identifiers)
            if abort.is_set():
                return
            results = []
            while True:
                try:
                    results.append(rq.get_nowait())
                except Empty:
                    break
            results.sort(key=self.identify_results_keygen(
                title=title, authors=authors, identifiers=identifiers))
            for mi in results:
                cached_url = self.get_cached_cover_url(mi.identifiers)
                if cached_url is not None:
                    break
        if cached_url is None:
            log.info('No cover found')
            return
        if abort.is_set():
            return
        log('Downloading cover from:', cached_url)
        try:
            cdata = self.browser.open_novisit(cached_url, timeout=timeout).read()
            result_queue.put((self, cdata))
        except Exception:
            log.exception('Failed to download cover from:', cached_url)
