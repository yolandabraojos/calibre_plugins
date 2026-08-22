# -*- coding: utf-8 -*-
"""Tests del plugin `goodreads_fast`.

`worker.py` y `__init__.py` importan Calibre, asi que aqui se inyectan
modulos `calibre.*` falsos en `sys.modules` ANTES de cargarlos (es la via que
indica `tests/README.md` para modulos que dependen de Calibre). Lo que se
prueba es todo lo que no necesita red:

- `worker.py`: si una sinopsis es real o de relleno, el parseo de la lista de
  ediciones de una obra, la alternancia de URL `.xml` <-> sin extension y la
  decision de reintentar ante un 503.
- `__init__.py`: que un reclamo de genero ("A Reverse Harem Dragon Shifter
  Romance") no sirva como prueba de coincidencia, ni al construir los nucleos
  de busqueda ni al comparar los del candidato; y que los separadores de
  segmento (":", " - ", "_", "|") partan el titulo donde deben -- ni de mas
  (una palabra suelta por cada "_" de un titulo todo-con-guiones-bajos) ni de
  menos (un titulo real con un guion pegado a una palabra, "Self-Published",
  no se parte).

`get_title_tokens`/`get_author_tokens` son de Calibre; aqui hay una imitacion
suficientemente fiel para estos casos (parte por puntuacion, quita los
"joiners" a/and/the). Si algun dia un test de estos falla dentro de Calibre
pero pasa aqui, sospechar primero de esa imitacion.
"""
from __future__ import unicode_literals

import os
import sys
import types
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    import lxml.html  # noqa: F401
    HAS_LXML = True
except ImportError:
    HAS_LXML = False


def _install_calibre_stubs():
    """Modulos `calibre.*` minimos, solo lo que worker.py importa."""
    def mod(name, **attrs):
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[name] = m
        return m

    class Metadata(object):
        def __init__(self, title, authors):
            self.title, self.authors = title, authors
            self.comments = self.series = self.publisher = None
            self.language = 'und'
            self.identifiers = {}
            self.has_cover = False

        def set_identifier(self, k, v):
            self.identifiers[k] = v

    for pkg in ('calibre', 'calibre.ebooks', 'calibre.ebooks.metadata',
                'calibre.ebooks.metadata.book', 'calibre.library', 'calibre.utils'):
        mod(pkg)
    mod('calibre.ebooks.metadata.book.base', Metadata=Metadata)
    mod('calibre.library.comments', sanitize_comments_html=lambda h: h)
    mod('calibre.utils.localization',
        canonicalize_lang=lambda n: {'English': 'eng', 'German': 'deu'}.get(n))
    mod('calibre.utils.cleantext', clean_ascii_chars=lambda x: x)
    mod('calibre.utils.date', utcfromtimestamp=lambda ts: None)


def _install_source_stub():
    """`Source` de Calibre reducido a los helpers que usa el plugin."""
    import re as _re

    class Source(object):
        def get_title_tokens(self, title, strip_joiners=True, strip_subtitle=False):
            if not title:
                return
            if strip_subtitle:
                m = _re.match(r'^(.+?)([,:;] .+)$', title)
                if m:
                    title = m.group(1)
            for tok in _re.sub(r'[:,;!@$%^&*(){}.`~"\s\[\]/]', ' ', title).split():
                tok = tok.strip('.').strip('"').strip("'")
                if not tok:
                    continue
                if strip_joiners and tok.lower() in ('a', 'and', 'the', '&'):
                    continue
                yield tok

        def get_author_tokens(self, authors, only_first_author=True):
            if only_first_author:
                authors = authors[:1]
            for a in authors:
                for tok in _re.split(r'[^0-9A-Za-z]+', a or ''):
                    if tok:
                        yield tok

    m = types.ModuleType('calibre.ebooks.metadata.sources.base')
    m.Source = Source
    m.fixcase = lambda x: x
    m.fixauthors = lambda x: x
    sys.modules['calibre.ebooks.metadata.sources'] = types.ModuleType(
        'calibre.ebooks.metadata.sources')
    sys.modules['calibre.ebooks.metadata.sources.base'] = m

    sys.modules['calibre'].as_unicode = lambda x: x
    ebooks = sys.modules['calibre.ebooks']
    ebooks.normalize = lambda x: x
    md = sys.modules['calibre.ebooks.metadata']
    md.check_isbn = lambda x: x
    icu = types.ModuleType('calibre.utils.icu')
    icu.lower = lambda x: (x or '').lower()
    sys.modules['calibre.utils.icu'] = icu


def _load(path, name):
    if sys.version_info[0] >= 3:
        import importlib.util
        spec = importlib.util.spec_from_file_location(name, path)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    import imp
    return imp.load_source(name, path)


def _load_modules():
    _install_calibre_stubs()
    _install_source_stub()
    return (_load(os.path.join(REPO, 'goodreads_fast', 'worker.py'), 'gf_worker'),
            _load(os.path.join(REPO, 'goodreads_fast', '__init__.py'), 'gf_plugin'))


worker, plugin_mod = _load_modules() if HAS_LXML else (None, None)


def _make_plugin():
    """Instancia sin __init__ (Source pide rutas de plugin que aqui sobran)."""
    return plugin_mod.GoodreadsFast.__new__(plugin_mod.GoodreadsFast)


def _cand(book_id, title, author, ratings=100, work=None):
    return {'bookId': book_id, 'bookTitleBare': title, 'ratingsCount': ratings,
            'workId': work, 'author': {'name': author}}


class _Log(object):
    def __init__(self):
        self.lines = []

    def _add(self, *a):
        self.lines.append(' '.join(str(x) for x in a))

    info = warn = error = debug = exception = _add

    def __call__(self, *a):
        self._add(*a)


class _HttpError(Exception):
    """Se parece a lo que levanta mechanize: trae getcode() y .code."""
    def __init__(self, code):
        Exception.__init__(self, 'HTTP Error %d' % code)
        self.code = code

    def getcode(self):
        return self.code


def _make_worker(url='https://www.goodreads.com/book/show/85746064.xml'):
    """Worker sin __init__ (no arranca hilo ni clona navegador)."""
    w = worker.Worker.__new__(worker.Worker)
    w.url, w.log, w.timeout = url, _Log(), 30
    w.lang_map = {'English': 'eng', 'German': 'deu'}
    return w


EDITIONS_HTML = """<html><body>
<div class="elementList clearFix">
  <a class="bookTitle" href="/book/show/85746064-blade">Blade (The Blood Brotherhood, #3)</a>
  <div class="editionData">Kindle Edition, 385 pages Edition language: English</div>
</div>
<div class="elementList clearFix">
  <a class="bookTitle" href="/book/show/138295429-blade">Blade: A Bear Shifter Biker Romance</a>
  <div class="editionData">Paperback, 348 pages Edition language: English</div>
</div>
<div class="elementList clearFix">
  <a class="bookTitle" href="/book/show/249408031-blade">Blade: Ein Baer Shifter Biker Romance Buch</a>
  <div class="editionData">Paperback, 358 pages Edition language: German</div>
</div>
</body></html>"""


@unittest.skipUnless(HAS_LXML, 'lxml no instalado')
class TestIsRealDescription(unittest.TestCase):
    """Goodreads pone "Coming soon..." en muchas fichas: eso NO es sinopsis."""

    def setUp(self):
        self.w = _make_worker()

    def test_coming_soon_no_es_sinopsis(self):
        self.assertFalse(self.w._is_real_description('<div>Coming soon...</div>'))

    def test_vacia_no_es_sinopsis(self):
        self.assertFalse(self.w._is_real_description(None))
        self.assertFalse(self.w._is_real_description('<div>  </div>'))

    def test_to_be_announced_no_es_sinopsis(self):
        self.assertFalse(self.w._is_real_description('To be announced'))

    def test_demasiado_corta_no_es_sinopsis(self):
        self.assertFalse(self.w._is_real_description('<p>Un libro.</p>'))

    def test_sinopsis_de_verdad(self):
        self.assertTrue(self.w._is_real_description(
            '<div><b>The only woman I want is the only one who does not want me '
            'in return.</b><br/>The Brotherhood is my life.</div>'))


@unittest.skipUnless(HAS_LXML, 'lxml no instalado')
class TestSiblingEditionIds(unittest.TestCase):
    """La sinopsis se toma prestada de otra edicion de la MISMA obra."""

    def setUp(self):
        self.w = _make_worker()
        self.w.browser = types.SimpleNamespace(
            open_novisit=lambda url, timeout=None: types.SimpleNamespace(
                read=lambda: EDITIONS_HTML.encode('utf-8')))

    def test_excluye_la_propia_y_los_otros_idiomas(self):
        self.assertEqual(self.w.sibling_edition_ids('u', '85746064', 'eng'),
                         ['138295429'])

    def test_sin_idioma_conocido_no_filtra(self):
        self.assertEqual(self.w.sibling_edition_ids('u', '85746064', None),
                         ['138295429', '249408031'])

    def test_la_propia_puede_ser_cualquiera(self):
        self.assertEqual(self.w.sibling_edition_ids('u', '138295429', 'eng'),
                         ['85746064'])

    def test_lista_ilegible_no_rompe(self):
        self.w.browser = types.SimpleNamespace(
            open_novisit=lambda url, timeout=None: (_ for _ in ()).throw(IOError('boom')))
        self.assertEqual(self.w.sibling_edition_ids('u', '1', 'eng'), [])


@unittest.skipUnless(HAS_LXML, 'lxml no instalado')
class TestEditionsUrl(unittest.TestCase):
    def setUp(self):
        self.w = _make_worker()

    def test_desde_el_json_de_la_obra(self):
        self.assertEqual(
            self.w.editions_url({'editions': {'webUrl': 'https://x/work/editions/110186032'},
                                 'legacyId': 110186032}),
            'https://x/work/editions/110186032')

    def test_desde_el_legacy_id(self):
        self.assertEqual(self.w.editions_url({'legacyId': 110186032}),
                         'https://www.goodreads.com/work/editions/110186032')

    def test_sin_datos(self):
        self.assertIsNone(self.w.editions_url({}))
        self.assertIsNone(self.w.editions_url(None))


@unittest.skipUnless(HAS_LXML, 'lxml no instalado')
class TestOtherUrlFlavour(unittest.TestCase):
    """El WAF de Goodreads acepta o rechaza cada variante por separado."""

    def setUp(self):
        self.w = _make_worker()

    def test_ida_y_vuelta(self):
        xml = 'https://www.goodreads.com/book/show/51279741.xml'
        bare = 'https://www.goodreads.com/book/show/51279741'
        self.assertEqual(self.w._other_url_flavour(xml), bare)
        self.assertEqual(self.w._other_url_flavour(bare), xml)

    def test_url_con_slug(self):
        self.assertEqual(
            self.w._other_url_flavour('https://www.goodreads.com/book/show/51279741-exposed'),
            'https://www.goodreads.com/book/show/51279741.xml')


@unittest.skipUnless(HAS_LXML, 'lxml no instalado')
class TestGetDetailsRetry(unittest.TestCase):
    """Un 503 es un rechazo del WAF, no un libro inexistente: hay que reintentar."""

    def _worker_that_raises(self, exc):
        w = _make_worker()
        def boom(url, timeout=None):
            raise exc
        w.browser = types.SimpleNamespace(open_novisit=boom)
        return w

    def test_503_pide_reintento_y_cambia_de_url(self):
        w = self._worker_that_raises(_HttpError(503))
        self.assertTrue(w.get_details())
        self.assertEqual(w.url, 'https://www.goodreads.com/book/show/85746064')

    def test_429_pide_reintento(self):
        self.assertTrue(self._worker_that_raises(_HttpError(429)).get_details())

    def test_404_no_reintenta(self):
        w = self._worker_that_raises(_HttpError(404))
        self.assertFalse(w.get_details())
        self.assertEqual(w.url, 'https://www.goodreads.com/book/show/85746064.xml')

    def test_error_desconocido_no_reintenta(self):
        self.assertFalse(self._worker_that_raises(ValueError('raro')).get_details())

    def test_http_code_desde_atributo_code(self):
        w = _make_worker()
        e = Exception('sin getcode')
        e.code = 503
        self.assertEqual(w._http_code(e), 503)
        self.assertIsNone(w._http_code(ValueError('nada')))


@unittest.skipUnless(HAS_LXML, 'lxml no instalado')
class TestIsBoilerplateSegment(unittest.TestCase):
    """"A Reverse Harem Dragon Shifter Romance" lo comparten cientos de libros."""

    def setUp(self):
        self.p = _make_plugin()

    def test_con_articulo_y_sustantivo_de_genero(self):
        for seg in ('A Reverse Harem Dragon Shifter Romance',
                    'A Bear Shifter Biker Romance',
                    'An Alien Warrior Romance',
                    'The Complete Collection',
                    'A Novel'):
            self.assertTrue(self.p._is_boilerplate_segment(seg), seg)

    def test_sin_articulo_pero_con_tropo(self):
        self.assertTrue(self.p._is_boilerplate_segment(
            'Reverse Harem Dragon Shifter Romance'))

    def test_titulo_de_verdad_no_es_reclamo(self):
        for seg in ('An Heir Fit for a King',
                    'Rise of a Wizard Queen',
                    'The Girl on the Train',
                    'The Pregnant Princess',
                    'Blade',
                    'Singed'):
            self.assertFalse(self.p._is_boilerplate_segment(seg), seg)

    def test_sin_articulo_y_sin_tropo_no_es_reclamo(self):
        # Termina en "Story" pero no hay ninguna etiqueta comercial: podria ser
        # un titulo real, asi que no se descarta.
        self.assertFalse(self.p._is_boilerplate_segment('Toy Story'))

    def test_vacio(self):
        self.assertFalse(self.p._is_boilerplate_segment(''))
        self.assertFalse(self.p._is_boilerplate_segment(None))


@unittest.skipUnless(HAS_LXML, 'lxml no instalado')
class TestTitleCores(unittest.TestCase):
    """La cola solo se busca por separado si dice algo del libro."""

    def setUp(self):
        self.p = _make_plugin()

    def test_no_busca_el_reclamo_de_genero_solo(self):
        cores = self.p._title_cores(
            'Bonded to her Royal Mates: A Reverse Harem Dragon Shifter Romance')
        self.assertIn('Bonded to her Royal Mates', cores)
        self.assertNotIn('A Reverse Harem Dragon Shifter Romance', cores)

    def test_la_cola_util_se_conserva(self):
        # El caso que justifica que exista la cola: el titulo real va DESPUES
        # del prefijo de saga.
        cores = self.p._title_cores(
            'Fate of Wizardoms - Wizardoms: Rise of a Wizard Queen')
        self.assertIn('Rise of a Wizard Queen', cores)

    def test_el_titulo_entero_sigue_estando(self):
        cores = self.p._title_cores('Blade: A Bear Shifter Biker Romance')
        self.assertEqual(cores[0], 'Blade')
        self.assertTrue(any('Bear Shifter Biker Romance' in c for c in cores))


@unittest.skipUnless(HAS_LXML, 'lxml no instalado')
class TestCandTitleVariants(unittest.TestCase):
    def setUp(self):
        self.p = _make_plugin()

    def _sets(self, title):
        return self.p._cand_title_variants(title)

    def test_la_cola_de_genero_no_es_variante(self):
        genre = frozenset(('reverse', 'harem', 'dragon', 'shifter', 'romance'))
        self.assertNotIn(genre, self._sets('Singed: A Reverse Harem Dragon Shifter Romance'))

    def test_la_cabeza_sigue_siendo_variante(self):
        self.assertIn(frozenset(('Singed'.lower(),)),
                      self._sets('Singed: A Reverse Harem Dragon Shifter Romance'))
        self.assertIn(frozenset(('blade',)),
                      self._sets('Blade: A Bear Shifter Biker Romance'))


@unittest.skipUnless(HAS_LXML, 'lxml no instalado')
class TestRankCandidates(unittest.TestCase):
    """De punta a punta: el caso real que devolvia un libro inventado."""

    def setUp(self):
        self.p = _make_plugin()

    def test_rechaza_los_libros_del_mismo_genero_y_otro_autor(self):
        # "Bonded to her Royal Mates" de Claire Heat NO esta en Goodreads:
        # lo correcto es no devolver nada.
        cands = [_cand('51254043', 'Singed: A Reverse Harem Dragon Shifter Romance',
                       'Misty Malloy', 173),
                 _cand('71049378', 'Ignited: A Reverse Harem Dragon Shifter Romance',
                       'Misty Malloy', 138),
                 _cand('70743258', 'Scorched: A Reverse Harem Dragon Shifter Romance',
                       'Misty Malloy', 309)]
        scored = self.p._rank_candidates(
            _Log(), cands,
            'Bonded to her Royal Mates: A Reverse Harem Dragon Shifter Romance',
            ['Claire Heat'])
        self.assertEqual(scored, [])

    def test_el_libro_correcto_sigue_ganando(self):
        cands = [_cand('85746064', 'Blade', 'Eva Kent', 268),
                 _cand('138295429', 'Blade: A Bear Shifter Biker Romance',
                       'Eva Kent', 268)]
        scored = self.p._rank_candidates(_Log(), cands, 'Blade', ['Eva Kent'])
        self.assertEqual(sorted(c['bookId'] for _s, c in scored),
                         ['138295429', '85746064'])

    def test_mismo_titulo_y_mismo_autor_se_acepta(self):
        # El autor sigue sin ser un veto: un titulo que casa de verdad entra
        # aunque Goodreads lo acredite a otro nombre (seudonimos, coautorias).
        scored = self.p._rank_candidates(
            _Log(), [_cand('1', 'Bonded to her Royal Mates', 'Otra Persona', 50)],
            'Bonded to her Royal Mates', ['Claire Heat'])
        self.assertEqual(len(scored), 1)


@unittest.skipUnless(HAS_LXML, 'lxml no instalado')
class TestSegmentSeparators(unittest.TestCase):
    """':' y ' - ' no son los unicos separadores: los titulos sacados de un
    nombre de fichero (donde ':' y el espacio no son validos) suelen usar
    guion bajo. Un '_' SUELTO es casi siempre un sustituto de un espacio --
    tratarlo como separador de segmento partiria "Blade_A_Bear_Shifter_Biker_
    Romance" en seis palabras sueltas. Una RACHA de 2+ ('__', '_-_', '|') si
    es una senal deliberada de separador."""

    def setUp(self):
        self.p = _make_plugin()

    def test_un_solo_guion_bajo_no_es_separador(self):
        # No debe partirse en palabras sueltas: un solo nucleo con todo junto
        # (los "_" se convierten en espacios en la limpieza final).
        cores = self.p._title_cores('Blade_A_Bear_Shifter_Biker_Romance')
        self.assertEqual(cores, ['Blade A Bear Shifter Biker Romance'])

    def test_doble_guion_bajo_si_es_separador(self):
        cores = self.p._title_cores('Blade__A_Bear_Shifter_Biker_Romance')
        self.assertIn('Blade', cores)
        self.assertNotIn('A Bear Shifter Biker Romance', cores)

    def test_guion_bajo_guion_guion_bajo(self):
        cores = self.p._title_cores('Blade_-_A_Bear_Shifter_Biker_Romance')
        self.assertIn('Blade', cores)
        self.assertNotIn('A Bear Shifter Biker Romance', cores)

    def test_barra_vertical_es_separador(self):
        cores = self.p._title_cores('Blade | A Bear Shifter Biker Romance')
        self.assertIn('Blade', cores)
        self.assertNotIn('A Bear Shifter Biker Romance', cores)

    def test_dos_puntos_con_guiones_bajos_alrededor(self):
        cores = self.p._title_cores('Blade_:_A Bear Shifter Biker Romance')
        self.assertIn('Blade', cores)

    def test_guion_pegado_a_una_palabra_no_es_separador(self):
        # "Self-Published" es una palabra real; no debe partirse por el "-".
        self.assertEqual(self.p._title_cores('Self-Published Diary'),
                         ['Self Published Diary'])

    def test_caso_ya_existente_sigue_igual(self):
        # ' - ' y ':' normales (con espacios de verdad) no cambian de
        # comportamiento tras compartir el regex.
        cores = self.p._title_cores(
            'Fate of Wizardoms - Wizardoms: Rise of a Wizard Queen')
        self.assertIn('Fate of Wizardoms', cores)
        self.assertIn('Rise of a Wizard Queen', cores)

    def test_cand_title_variants_reconoce_los_mismos_separadores(self):
        # La cola de genero AISLADA (sin "singed") no debe aparecer como
        # variante propia -- solo puede colarse dentro del "titulo completo"
        # de reserva, que siempre incluye todas las palabras.
        genre_alone = frozenset(('dragon', 'shifter', 'harem', 'romance', 'reverse'))
        variants = self.p._cand_title_variants(
            'Singed__A_Reverse_Harem_Dragon_Shifter_Romance')
        self.assertIn(frozenset(('singed',)), variants)
        self.assertNotIn(genre_alone, variants)


@unittest.skipUnless(HAS_LXML, 'lxml no instalado')
class TestRankCandidatesUnderscored(unittest.TestCase):
    """El caso real de Claire Heat, pero con el titulo mal exportado (todo
    con guiones bajos en vez de espacios/2 puntos) -- debe seguir sin match."""

    def setUp(self):
        self.p = _make_plugin()
        self.cands = [
            _cand('51254043', 'Singed: A Reverse Harem Dragon Shifter Romance',
                  'Misty Malloy', 173),
            _cand('71049378', 'Ignited: A Reverse Harem Dragon Shifter Romance',
                  'Misty Malloy', 138),
            _cand('70743258', 'Scorched: A Reverse Harem Dragon Shifter Romance',
                  'Misty Malloy', 309),
        ]

    def test_con_doble_guion_bajo_como_separador(self):
        scored = self.p._rank_candidates(
            _Log(), self.cands,
            'Bonded_to_her_Royal_Mates__A_Reverse_Harem_Dragon_Shifter_Romance',
            ['Claire Heat'])
        self.assertEqual(scored, [])

    def test_con_un_solo_guion_bajo_en_todas_partes(self):
        scored = self.p._rank_candidates(
            _Log(), self.cands,
            'Bonded_to_her_Royal_Mates_A_Reverse_Harem_Dragon_Shifter_Romance',
            ['Claire Heat'])
        self.assertEqual(scored, [])

    def test_blade_con_doble_guion_bajo_sigue_encontrando_la_edicion(self):
        blade_cands = [_cand('85746064', 'Blade', 'Eva Kent', 268),
                       _cand('138295429', 'Blade: A Bear Shifter Biker Romance',
                             'Eva Kent', 268)]
        scored = self.p._rank_candidates(
            _Log(), blade_cands, 'Blade__A_Bear_Shifter_Biker_Romance',
            ['Eva Kent'])
        self.assertEqual(sorted(c['bookId'] for _s, c in scored),
                         ['138295429', '85746064'])


if __name__ == '__main__':
    unittest.main()
