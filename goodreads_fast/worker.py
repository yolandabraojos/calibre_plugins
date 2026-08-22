#!/usr/bin/env python
# -*- coding: utf-8 -*-
# GoodreadsFast worker - parses the Goodreads book page __NEXT_DATA__ json and
# scrapes the book's popular shelves to build richer, vote-weighted tags.
# Adapted from the "Goodreads" plugin worker by Grant Drake (GPL v3) and the
# shelf/tag logic of "Goodreads More Tags" by Michon van Dooren (BSD 3-clause).
from __future__ import unicode_literals, division, absolute_import, print_function

__license__ = 'GPL v3'
__copyright__ = '2026, Yolanda Braojos'

import socket, re, datetime, json, time
from collections import Counter
from threading import Thread

from lxml.html import tostring, fromstring

from calibre.ebooks.metadata.book.base import Metadata
from calibre.library.comments import sanitize_comments_html
from calibre.utils.localization import canonicalize_lang
from calibre.utils.cleantext import clean_ascii_chars
from calibre.utils.date import utcfromtimestamp

# ---- fixed behaviour (previously configurable in the original plugins) ----
GET_ALL_AUTHORS = False      # only real "Author" role contributors
FIRST_PUBLISHED = True       # use the work's first-published date, not the edition

# ---- shelf -> tag settings (ported from Goodreads More Tags defaults) ----
SHELVES_URL = 'https://www.goodreads.com/book/shelves/{identifier}'
SHELF_THRESHOLD_ABSOLUTE = 10     # min combined votes for a tag
SHELF_THRESHOLD_PCT = 30          # keep tags with >= 30% of the base
SHELF_THRESHOLD_PCT_OF = [3, 4]   # base = average of the 3rd and 4th place tags
SHELF_TIMEOUT = 8                 # shelves are optional enrichment; don't let them stall

# Codigos HTTP que NO significan "este libro no existe", sino que el borde de
# Goodreads (AWS WAF) o el servidor han rechazado ESTA peticion. Se reintenta.
TRANSIENT_HTTP_CODES = frozenset((408, 425, 429, 500, 502, 503, 504))

# Goodreads guarda la sinopsis por EDICION, no por obra. Es muy frecuente que la
# ficha con mas votos (la que gana el ranking) no tenga sinopsis real -- literal
# "Coming soon..." -- mientras que otra edicion de la MISMA obra si la tiene.
# Caso comprobado: "Blade" de Eva Kent, obra 110186032: la ficha 85746064
# (Kindle, 268 votos) dice "Coming soon...", y la 138295429 (Paperback) trae la
# sinopsis completa. Cuando la nuestra no trae descripcion de verdad se mira la
# lista de ediciones de la obra y se toma prestada la primera buena.
WORK_EDITIONS_URL = 'https://www.goodreads.com/work/editions/{legacy_work_id}'
EDITIONS_TIMEOUT = 8              # la lista de ediciones es opcional, no debe atascar
MAX_SIBLING_EDITIONS = 3          # cuantas fichas hermanas se llegan a descargar
MIN_REAL_DESCRIPTION = 60         # caracteres de texto plano para considerarla real
PLACEHOLDER_DESCRIPTION_RE = re.compile(
    r'^(coming soon|coming shortly|to be announced|tba|synopsis coming|'
    r'description coming|no description|not yet available|proximamente|'
    r'sin sinopsis|sin descripcion)\b', re.I)

SHELF_MAPPINGS = {
    'adult': ['Adult'], 'adult-fiction': ['Adult'], 'adventure': ['Adventure'],
    'anthologies': ['Anthologies'], 'art': ['Art'], 'biography': ['Biography'],
    'business': ['Business'], 'chick-lit': ['Chick-lit'], 'childrens': ['Childrens'],
    'classics': ['Classics'], 'comedy': ['Humour'], 'comics': ['Comics'],
    'comics-manga': ['Comics'], 'contemporary': ['Contemporary'], 'cookbooks': ['Cookbooks'],
    'crime': ['Crime'], 'dystopia': ['Dystopia'], 'dystopian': ['Dystopia'],
    'essays': ['Writing'], 'epic-fantasy': ['Fantasy'], 'fantasy': ['Fantasy'],
    'feminism': ['Feminism'], 'gardening': ['Gardening'], 'gay': ['Gay'],
    'graphic-novels': ['Comics'], 'graphic-novels-comics': ['Comics'],
    'graphic-novels-comics-manga': ['Comics'], 'health': ['Health'],
    'high-fantasy': ['Fantasy'], 'historical': ['Historical'],
    'historical-fiction': ['Historical', 'Fiction'], 'history': ['History'],
    'horror': ['Horror'], 'humor': ['Humour'], 'inspirational': ['Inspirational'],
    'lgbt': ['Gay'], 'literary-fiction': ['Literary Fiction', 'Fiction'],
    'manga': ['Comics'], 'memoir': ['Biography'], 'modern': ['Modern'],
    'music': ['Music'], 'mystery': ['Mystery'], 'non-fiction': ['Non-Fiction'],
    'paranormal': ['Paranormal'], 'philosophy': ['Philosophy'], 'poetry': ['Poetry'],
    'politics': ['Politics'], 'psychology': ['Psychology'], 'reference': ['Reference'],
    'religion': ['Religion'], 'romance': ['Romance'],
    'sci-fi-and-fantasy': ['Science Fiction', 'Fantasy'],
    'sci-fi-fantasy': ['Science Fiction', 'Fantasy'], 'science': ['Science'],
    'science-fiction': ['Science Fiction'],
    'science-fiction-fantasy': ['Science Fiction', 'Fantasy'],
    'self-help': ['Self Help'], 'sf-fantasy': ['Science Fiction', 'Fantasy'],
    'short-stories': ['Short Stories'], 'sociology': ['Sociology'],
    'spirituality': ['Spirituality'], 'suspense': ['Suspense'], 'thriller': ['Thriller'],
    'travel': ['Travel'], 'urban-fantasy': ['Urban Fantasy', 'Fantasy'],
    'vampires': ['Vampires'], 'war': ['War'], 'western': ['Western'],
    'writing': ['Writing'], 'ya': ['Young Adult'], 'young-adult': ['Young Adult'],
}


TAG_BLOCKLIST = frozenset((
    'audiobook', 'audiobooks', 'audio', 'book club', 'book-club', 'ebook',
    'e-book', 'kindle', 'owned', 'owned-books', 'books-i-own', 'own', 'to-read',
    'to read', 'currently-reading', 'currently reading', 'favorites',
    'favourites', 'favorite', 'wishlist', 'series', 'dnf', 'did-not-finish',
    're-read', 'reread', 'tbr', 'library', 'unfinished', 'abandoned', 'default',
    'my-books', 'general', 'novels',
))

class TagList(Counter):
    """A list of tags with the number of people that 'voted' for the tag."""
    def apply_threshold(self, threshold):
        for key, count in list(self.items()):
            if count < threshold:
                del self[key]

    def get_places(self, places):
        items = self.most_common(max(places))
        return [items[p - 1] if p <= len(items) else None for p in places]


def parse_html(raw):
    try:
        from html5_parser import parse
    except ImportError:
        import html5lib
        return html5lib.parse(raw, treebuilder='lxml', namespaceHTMLElements=False)
    else:
        return parse(raw)


class Worker(Thread):
    '''Get book details from a Goodreads book page in a separate thread.'''

    def __init__(self, url, result_queue, browser, log, relevance, plugin, timeout=20):
        Thread.__init__(self)
        self.daemon = True
        self.url, self.result_queue = url, result_queue
        self.log, self.timeout = log, timeout
        self.relevance, self.plugin = relevance, plugin
        self.browser = browser.clone_browser()
        self.cover_url = self.goodreads_id = self.isbn = None

        lm = {
            'eng': ('English', 'Englisch'),
            'fra': ('French', 'Français'),
            'ita': ('Italian', 'Italiano'),
            'dut': ('Dutch',),
            'deu': ('German', 'Deutsch'),
            'spa': ('Spanish', 'Español', 'Espaniol'),
            'jpn': ('Japanese', '日本語'),
            'por': ('Portuguese', 'Português'),
        }
        self.lang_map = {}
        for code, names in lm.items():
            for name in names:
                self.lang_map[name] = code

    def run(self):
        try:
            retry = True
            retryCount = 0
            # Goodreads a veces devuelve una pagina sin el JSON del libro, o un
            # 503 del WAF de Amazon en 0,3 s (rechazo en el borde, no caida del
            # servicio). Reintentamos, pero pocas veces: 11 intentos alargaban
            # mucho los libros irrecuperables. 4 es suficiente.
            # Backoff antes de cada reintento (no antes del primero): si el WAF
            # corta, esperar ayuda mas que golpear la misma URL al instante.
            while retry and retryCount < 4:
                if retryCount:
                    time.sleep(min(4.0, 1.0 * (2 ** (retryCount - 1))))  # 1 s, 2 s, 4 s
                retryCount += 1
                self.log('Get details attempt #%d' % retryCount)
                retry = self.get_details()
        except Exception:
            self.log.exception('get_details failed for url: %r' % self.url)

    def _http_code(self, e):
        '''Codigo HTTP de una excepcion de mechanize/urllib, o None.'''
        getcode = getattr(e, 'getcode', None)
        if callable(getcode):
            try:
                return getcode()
            except Exception:
                pass
        code = getattr(e, 'code', None)
        return code if isinstance(code, int) else None

    def _other_url_flavour(self, url):
        '''Goodreads sirve la MISMA pagina Next.js (con su __NEXT_DATA__) en
        /book/show/<id> y en /book/show/<id>.xml. El WAF de Amazon acepta o
        rechaza cada variante por separado y de forma erratica, asi que cuando
        una da 503 la otra suele responder. Alternamos entre las dos.'''
        if url.endswith('.xml'):
            return url[:-4]
        m = re.match(r'^(.*/book/show/\d+)(?:[-/][^?#]*)?$', url)
        if m:
            return m.group(1) + '.xml'
        return url

    def get_details(self):
        try:
            self.log.info('Goodreads book url: %r' % self.url)
            raw = self.browser.open_novisit(self.url, timeout=self.timeout).read().strip()
        except Exception as e:
            code = self._http_code(e)
            if code == 404:
                self.log.error('URL malformed: %r' % self.url)
                return False
            attr = getattr(e, 'args', [None])
            attr = attr if attr else [None]
            if isinstance(attr[0], socket.timeout):
                self.log.error('Goodreads timed out. Try again later.')
                return False
            if code in TRANSIENT_HTTP_CODES:
                # NO es "el libro no existe": el borde de Goodreads ha
                # rechazado esta peticion. Antes se devolvia False, asi que el
                # bucle de reintentos de run() moria en el intento #1 pese a
                # estar escrito justo para este caso. Ademas se alterna la
                # variante de URL, porque el WAF acepta o rechaza cada una por
                # separado.
                other = self._other_url_flavour(self.url)
                self.log.error('Goodreads devolvio HTTP %s en %r; se reintenta con %r'
                               % (code, self.url, other))
                self.url = other
                return True
            self.log.exception('Failed to make details query: %r' % self.url)
            return False

        raw_utf8 = raw.decode('utf-8', errors='replace')
        if '<title>404 - ' in raw_utf8:
            self.log.error('URL malformed: %r' % self.url)
            return False

        try:
            root = parse_html(raw_utf8)
        except Exception:
            self.log.exception('Failed to parse goodreads details page: %r' % self.url)
            return False

        try:
            title_node = root.xpath('//title')
            if title_node:
                page_title = title_node[0].text
                if page_title is None or page_title.strip().find('search results for') != -1:
                    self.log.error('Got a search results page, not details: %r' % self.url)
                    return
        except Exception:
            self.log.exception('Failed to read goodreads page title: %r' % self.url)
            return

        try:
            (book_json, series_json, contributors_list_json, work_json) = self.parse_book_json(root)
            if not book_json:
                self.log('No book_json found in this response, retrying for another response')
                return True
            self.parse_details(root, book_json, series_json, contributors_list_json, work_json)
        except Exception:
            self.log.exception('Failed reading book json from: %r' % self.url)
            return False

    # ---------- sinopsis prestada de otra edicion de la misma obra ----------

    def _description_text(self, html):
        '''Texto plano de una sinopsis en HTML, para poder medirla.'''
        if not html:
            return ''
        text = re.sub(r'<[^>]+>', ' ', html)
        text = text.replace('&nbsp;', ' ').replace('&#160;', ' ')
        return re.sub(r'\s+', ' ', text).strip()

    def _is_real_description(self, html):
        '''False para las fichas sin sinopsis de verdad: vacias, marcadores tipo
        "Coming soon..." o cuatro palabras sueltas.'''
        text = self._description_text(html)
        if not text:
            return False
        if PLACEHOLDER_DESCRIPTION_RE.match(text):
            return False
        return len(text) >= MIN_REAL_DESCRIPTION

    def editions_url(self, work_json):
        '''URL de la lista de ediciones de la obra. El propio JSON la trae en
        Work.editions.webUrl; si no, se compone con el legacyId de la obra
        (el id numerico antiguo, que es el que usa /work/editions/).'''
        if not work_json:
            return None
        try:
            url = (work_json.get('editions') or {}).get('webUrl')
            if url:
                return url
        except Exception:
            pass
        legacy = work_json.get('legacyId')
        if legacy:
            return WORK_EDITIONS_URL.format(legacy_work_id=legacy)
        return None

    def sibling_edition_ids(self, url, own_id, want_lang):
        '''Ids de las demas ediciones de la obra, en el orden de la pagina.
        Se descartan las de otro idioma cuando la ficha lo declara ("Edition
        language: German"), para no traerse la sinopsis en aleman de un libro
        en ingles.'''
        try:
            data = self.browser.open_novisit(
                url, timeout=min(self.timeout, EDITIONS_TIMEOUT)).read()
            root = fromstring(clean_ascii_chars(
                data.decode('utf-8', errors='replace').strip()))
        except Exception:
            self.log.warn('No se pudo leer la lista de ediciones: %s' % url)
            return []
        ids = []
        for row in root.xpath('//div[contains(@class, "elementList")]'):
            try:
                href = row.xpath('.//a[contains(@class, "bookTitle")]/@href')
                if not href:
                    continue
                m = re.search(r'/show/(\d+)', href[0])
                if not m:
                    continue
                bid = m.group(1)
                if bid == own_id or bid in ids:
                    continue
                if want_lang:
                    ml = re.search(r'Edition language:\s*([^\n<]+)',
                                   row.text_content())
                    if ml:
                        name = ml.group(1).strip()
                        code = self.lang_map.get(name) or canonicalize_lang(name)
                        if code and code != want_lang:
                            continue
                ids.append(bid)
            except Exception:
                continue
        return ids

    def fetch_edition_description(self, book_id):
        '''Sinopsis de otra ficha, o None. Solo se parsea la descripcion: el
        resto de metadatos sigue viniendo de la ficha elegida.'''
        url = self.plugin.get_details_url(book_id)
        for attempt in (0, 1):
            try:
                raw = self.browser.open_novisit(url, timeout=self.timeout).read().strip()
            except Exception as e:
                if attempt == 0 and self._http_code(e) in TRANSIENT_HTTP_CODES:
                    url = self._other_url_flavour(url)
                    time.sleep(0.5)
                    continue
                return None
            try:
                (book_json, _s, _c, _w) = self.parse_book_json(
                    parse_html(raw.decode('utf-8', errors='replace')))
                if not book_json:
                    return None
                html = self.parse_comments(book_json)
                return html if self._is_real_description(html) else None
            except Exception:
                return None
        return None

    def borrow_description(self, work_json, own_id, mi):
        url = self.editions_url(work_json)
        if not url:
            return None
        want_lang = getattr(mi, 'language', None)
        if want_lang in (None, '', 'und'):
            want_lang = None
        ids = self.sibling_edition_ids(url, own_id, want_lang)[:MAX_SIBLING_EDITIONS]
        if not ids:
            return None
        self.log.info('[%s] sin sinopsis propia; se prueban las ediciones '
                      'hermanas de la obra: %s' % (own_id, ids))
        for bid in ids:
            html = self.fetch_edition_description(bid)
            if html:
                self.log.info('[%s] sinopsis tomada de la edicion %s' % (own_id, bid))
                return html
        self.log.info('[%s] ninguna edicion hermana tiene sinopsis' % own_id)
        return None

    def parse_book_json(self, root):
        script_node = root.xpath('//script[@id="__NEXT_DATA__"]')
        if not script_node:
            self.log.info('No __NEXT_DATA__ json found on page')
            return (None, None, None, None)
        try:
            book_props_json = json.loads(script_node[0].text)
            apolloState = book_props_json["props"]["pageProps"]["apolloState"]
            if len(apolloState.keys()) == 0:
                self.log.info('Empty apolloState node')
                return (None, None, None, None)

            book_json = None
            series_json = None
            contributors_list_json = []
            work_json = None
            for key in apolloState.keys():
                if key.startswith("Book:"):
                    if "title" in apolloState[key]:
                        book_json = apolloState[key]
                elif key.startswith("Series:") and series_json is None:
                    series_json = apolloState[key]
                elif key.startswith("Contributor:"):
                    contributors_list_json.append(apolloState[key])
                elif key.startswith("Work:"):
                    work_json = apolloState[key]
            return (book_json, series_json, contributors_list_json, work_json)
        except Exception:
            self.log.exception('Failed to parse book json')
            return (None, None, None, None)

    def parse_details(self, root, book_json, series_json, contributors_list_json, work_json):
        title = None
        authors = []
        try:
            goodreads_id = self.parse_goodreads_id(self.url)
        except Exception:
            self.log.exception('Error parsing goodreads id for url: %r' % self.url)
            goodreads_id = None

        try:
            if book_json:
                title = self.parse_title(book_json)
        except Exception:
            self.log.exception('Error parsing title')

        try:
            if book_json:
                authors = self.parse_authors(book_json, contributors_list_json)
        except Exception:
            self.log.exception('Error parsing authors')

        if not title or not authors or not goodreads_id:
            self.log.error('Could not parse title/authors/id from: %r' % self.url)
            return

        mi = Metadata(title, authors)
        mi.set_identifier('goodreads', goodreads_id)
        self.goodreads_id = goodreads_id

        try:
            series = series_index = None
            if book_json:
                (series, series_index) = self.parse_series(book_json, series_json)
            if series is not None:
                mi.series = series
                mi.series_index = series_index
        except Exception:
            self.log.exception('Error parsing series')

        try:
            isbn = None
            if book_json:
                isbn = self.parse_isbn(book_json)
            if isbn is not None:
                self.isbn = mi.isbn = isbn
        except Exception:
            self.log.exception('Error parsing ISBN')

        try:
            if work_json:
                mi.rating = self.parse_rating(work_json)
        except Exception:
            self.log.exception('Error parsing rating')

        try:
            comments = None
            if book_json:
                comments = self.parse_comments(book_json)
            if comments:
                mi.comments = comments
        except Exception:
            self.log.exception('Error parsing comments')

        try:
            if book_json:
                self.cover_url = self.parse_cover(book_json)
        except Exception:
            self.log.exception('Error parsing cover')
        mi.has_cover = bool(self.cover_url)

        # Tags: union of vote-weighted shelf tags and Goodreads genres, cleaned.
        try:
            shelf_tags = []
            if self.goodreads_id:
                shelf_tags = self.fetch_shelf_tags(self.goodreads_id) or []
            genre_tags = self.parse_tags(book_json) if book_json else []
            tags = self.merge_tags(shelf_tags, genre_tags)
            if tags:
                mi.tags = tags
        except Exception:
            self.log.exception('Error parsing tags')

        try:
            if book_json:
                mi.publisher = self.parse_publisher(book_json)
                mi.pubdate = self.parse_publish_date(book_json, work_json, FIRST_PUBLISHED)
        except Exception:
            self.log.exception('Error parsing publisher/date')

        try:
            lang = None
            if book_json:
                lang = self.parse_language(book_json)
            if lang is not None:
                mi.language = lang
        except Exception:
            self.log.exception('Error parsing language')

        # Va DESPUES del idioma a proposito: para no traerse la sinopsis de una
        # edicion en otra lengua hay que saber antes en que lengua esta esta.
        try:
            if not self._is_real_description(getattr(mi, 'comments', None)):
                borrowed = self.borrow_description(work_json, goodreads_id, mi)
                if borrowed:
                    mi.comments = borrowed
        except Exception:
            self.log.exception('Error borrowing description from sibling editions')

        mi.source_relevance = self.relevance
        if self.goodreads_id is not None:
            if self.isbn is not None:
                self.plugin.cache_isbn_to_identifier(self.isbn, self.goodreads_id)
            if self.cover_url is not None:
                self.plugin.cache_identifier_to_cover_url(self.goodreads_id, self.cover_url)
        self.plugin.clean_downloaded_metadata(mi)
        self.result_queue.put(mi)

    # ---------- shelves -> tags ----------

    def merge_tags(self, *tag_lists):
        """Union of tag lists: case-insensitive dedup, drops format/status noise."""
        seen = set()
        result = []
        for tags in tag_lists:
            for t in tags:
                if not t:
                    continue
                key = t.strip().lower()
                if key in seen or key in TAG_BLOCKLIST:
                    continue
                seen.add(key)
                result.append(t.strip())
        return result

    def fetch_shelf_tags(self, goodreads_id):
        url = SHELVES_URL.format(identifier=goodreads_id)
        try:
            self.log.info('[%s] Retrieving shelves from %s' % (goodreads_id, url))
            data = self.browser.open_novisit(url, timeout=min(self.timeout, SHELF_TIMEOUT)).read()
        except Exception:
            self.log.warn('[%s] Failed to retrieve shelves: %s' % (goodreads_id, url))
            return None
        try:
            data = data.decode('utf-8', errors='replace').strip()
            root = fromstring(clean_ascii_chars(data))
        except Exception:
            self.log.exception('[%s] Failed to parse shelves page' % goodreads_id)
            return None

        shelves = {}
        for shelf in root.xpath('//div[contains(@class, "shelfStat")]'):
            try:
                name = shelf.xpath('.//a[contains(@class, "actionLinkLite")]')[0].text_content().strip()
                count_text = shelf.xpath('.//div[contains(@class, "smallText")]')[0].text_content().strip()
                count = int(count_text.split()[0].replace(',', ''))
                shelves[name] = count
            except Exception:
                continue
        if not shelves:
            self.log.warn('[%s] No shelf info found on shelves page' % goodreads_id)
            return None

        tags = TagList()
        for name, count in shelves.items():
            for tag in SHELF_MAPPINGS.get(name, []):
                tags[tag] += count
        if not tags:
            return None

        tags.apply_threshold(SHELF_THRESHOLD_ABSOLUTE)
        places = list(filter(bool, tags.get_places(SHELF_THRESHOLD_PCT_OF)))
        base = (sum(i[1] for i in places) / len(places)) if places else 0
        tags.apply_threshold(base * SHELF_THRESHOLD_PCT / 100.0)
        result = [t for t, _ in tags.most_common()]
        self.log.info('[%s] Shelf tags: %s' % (goodreads_id, ', '.join(result)))
        return result or None

    # ---------- field parsers ----------

    def parse_goodreads_id(self, url):
        return re.search(r'/show/(\d+)', url).groups(0)[0]

    def parse_title(self, book_json):
        return book_json.get("title")

    def parse_series(self, book_json, series_json):
        if series_json is None or "title" not in series_json:
            return (None, None)
        series_name = series_json["title"]
        if "bookSeries" not in book_json:
            return (None, None)
        for book_series in book_json["bookSeries"]:
            if "userPosition" not in book_series:
                return (None, None)
            try:
                series_index = float(book_series["userPosition"])
            except Exception:
                return (None, None)
            return (series_name, series_index)
        return (None, None)

    def parse_authors(self, book_json, contributors_list_json):
        authors = []
        author_contributor_ids = []
        if book_json.get("primaryContributorEdge") is None:
            return authors
        primary = book_json["primaryContributorEdge"]
        role = primary["role"]
        if role in ("Author", "Pseudonym") or GET_ALL_AUTHORS:
            author_contributor_ids.append(primary["node"]["__ref"][12:])
        if book_json.get("secondaryContributorEdges") is not None:
            for secondary in book_json["secondaryContributorEdges"]:
                if secondary["role"] == "Author" or GET_ALL_AUTHORS:
                    author_contributor_ids.append(secondary["node"]["__ref"][12:])
        if not author_contributor_ids and not GET_ALL_AUTHORS:
            author_contributor_ids.append(primary["node"]["__ref"][12:])
        for contributor_json in contributors_list_json:
            if contributor_json.get("name") is None:
                continue
            if contributor_json["id"] in author_contributor_ids:
                authors.append(contributor_json["name"])
        return authors

    def parse_rating(self, work_json):
        stats = work_json.get("stats") if work_json else None
        if not stats or "averageRating" not in stats:
            return None
        try:
            return float(stats["averageRating"])
        except Exception:
            return None

    def parse_comments(self, book_json):
        description = book_json.get("description")
        if not description:
            return None
        return sanitize_comments_html(description)

    def parse_cover(self, book_json):
        img_url = book_json.get("imageUrl")
        if not img_url:
            return None
        try:
            info = self.browser.open_novisit(img_url, timeout=self.timeout).info()
            if int(info.get('Content-Length')) > 1000:
                return img_url
        except Exception:
            self.log.warning('Could not verify cover image: %s' % img_url)
        return None

    def parse_isbn(self, book_json):
        details = book_json.get("details") or {}
        return details.get("isbn13") or details.get("isbn")

    def parse_publisher(self, book_json):
        details = book_json.get("details") or {}
        return details.get("publisher")

    def parse_publish_date(self, book_json, work_json, first_published):
        epoch_time = None
        details = book_json.get("details") or {}
        if "publicationTime" in details:
            epoch_time = details["publicationTime"]
        if first_published and work_json:
            wdetails = work_json.get("details") or {}
            if wdetails.get("publicationTime"):
                epoch_time = wdetails["publicationTime"]
        if epoch_time:
            try:
                epoch_time = int(epoch_time) // 1000
                return utcfromtimestamp(epoch_time)
            except Exception:
                self.log.error('Failed to convert pub date: %r' % epoch_time)
        return None

    def parse_tags(self, book_json):
        if "bookGenres" not in book_json:
            return []
        genre_tags = []
        for bg in book_json["bookGenres"]:
            if "genre" in bg:
                genre_tags.append(bg["genre"]["name"])
        return genre_tags

    def parse_language(self, book_json):
        details = book_json.get("details") or {}
        if "language" in details and details["language"]:
            lang_name = details["language"].get("name")
            if not lang_name:
                return None
            ans = self.lang_map.get(lang_name, None)
            if ans:
                return ans
            return canonicalize_lang(lang_name)
        return None
