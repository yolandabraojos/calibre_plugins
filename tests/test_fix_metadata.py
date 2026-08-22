# -*- coding: utf-8 -*-
"""
Suite de tests para los módulos PUROS del plugin fix_metadata.

Cubre fix_author, fix_identifiers, fix_title y fix_world, que solo dependen de
`re`/`json` y por tanto se ejecutan sin Calibre (red de seguridad antes de cada
reempaquetado del ZIP).

Uso:
    python3 -m unittest discover -s tests -v
"""
from __future__ import unicode_literals
import os
import sys
import unittest

_PLUGIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'fix_metadata')
sys.path.insert(0, _PLUGIN_DIR)

import fix_author as fa          # noqa: E402
import fix_identifiers as fi     # noqa: E402
import fix_title as ft           # noqa: E402
import fix_world as fw           # noqa: E402
import fix_comments as fc        # noqa: E402


class TestFixAuthor(unittest.TestCase):

    def test_reverse_last_first(self):
        self.assertEqual(fa.fix_author('García, Gabriel'), 'Gabriel García')

    def test_reverse_with_initials(self):
        self.assertEqual(fa.fix_author('Tolkien, J.R.R.'), 'J. R. R. Tolkien')

    def test_dotted_initials_no_space(self):
        self.assertEqual(fa.fix_author('J.K. Rowling'), 'J. K. Rowling')

    def test_bare_initials_two(self):
        self.assertEqual(fa.fix_author('JK Rowling'), 'J. K. Rowling')

    def test_bare_initials_three(self):
        self.assertEqual(fa.fix_author('JRR Tolkien'), 'J. R. R. Tolkien')

    def test_dotted_no_spaces_at_all(self):
        self.assertEqual(fa.fix_author('J.K.Rowling'), 'J. K. Rowling')

    def test_spaced_initials_missing_dots(self):
        self.assertEqual(fa.fix_author('J K Rowling'), 'J. K. Rowling')

    def test_two_letter_initials(self):
        self.assertEqual(fa.fix_author('HP Lovecraft'), 'H. P. Lovecraft')

    def test_normal_name_unchanged(self):
        self.assertEqual(fa.fix_author('Brandon Sanderson'), 'Brandon Sanderson')

    def test_three_word_name_unchanged(self):
        self.assertEqual(fa.fix_author('Gabriel García Márquez'), 'Gabriel García Márquez')

    def test_particle_name_unchanged(self):
        self.assertEqual(fa.fix_author('Vincent van Gogh'), 'Vincent van Gogh')

    def test_empty_string(self):
        self.assertEqual(fa.fix_author(''), '')

    def test_none(self):
        self.assertIsNone(fa.fix_author(None))

    def test_would_fix_author(self):
        self.assertTrue(fa.would_fix_author('JK Rowling'))
        self.assertFalse(fa.would_fix_author('Brandon Sanderson'))


class TestFixIdentifiers(unittest.TestCase):

    def test_asin_to_amazon(self):
        new, _ = fi.fix_identifiers({'asin': 'B00ABC1234'})
        self.assertEqual(new, {'amazon': 'B00ABC1234'})

    def test_mobi_asin_to_amazon(self):
        new, _ = fi.fix_identifiers({'mobi-asin': 'B00ABC1234'})
        self.assertEqual(new, {'amazon': 'B00ABC1234'})

    def test_isbn13_variant(self):
        new, _ = fi.fix_identifiers({'isbn-13': '9780007370740'})
        self.assertEqual(new, {'isbn': '9780007370740'})

    def test_key_equals_value_to_isbn(self):
        new, _ = fi.fix_identifiers({'9780007351619': '9780007351619'})
        self.assertEqual(new, {'isbn': '9780007351619'})

    def test_regional_amazon_merged(self):
        new, _ = fi.fix_identifiers({'amazon_es': 'B00XYZ0001'})
        self.assertEqual(new, {'amazon': 'B00XYZ0001'})

    def test_isbn_digits_in_key(self):
        new, _ = fi.fix_identifiers({'isbn0310861691': 'ISBN0310861691'})
        self.assertEqual(new, {'isbn': '0310861691'})

    def test_uuid_removed(self):
        new, _ = fi.fix_identifiers({'246ad44a-1234-5678-9abc-def012345678': 'x'})
        self.assertEqual(new, {})

    def test_invalid_amazon_removed(self):
        new, _ = fi.fix_identifiers({'amazon': 'tooShort'})
        self.assertEqual(new, {})

    def test_valid_amazon_kept(self):
        new, _ = fi.fix_identifiers({'amazon': 'B00ABC1234'})
        self.assertEqual(new, {'amazon': 'B00ABC1234'})

    def test_real_isbn_kept(self):
        new, _ = fi.fix_identifiers({'isbn': '9780007370740'})
        self.assertEqual(new, {'isbn': '9780007370740'})

    def test_does_not_mutate_input(self):
        original = {'asin': 'B00ABC1234'}
        fi.fix_identifiers(original)
        self.assertEqual(original, {'asin': 'B00ABC1234'})


class TestFindSeries(unittest.TestCase):

    def test_A_dash_hash(self):
        self.assertEqual(ft.find_series_in_title('Blackout - John Milton #10'),
                         ('John Milton', 10.0, None))

    def test_B_paren_hash(self):
        self.assertEqual(
            ft.find_series_in_title('The Name of the Wind (The Kingkiller Chronicle, #1)'),
            ('The Kingkiller Chronicle', 1.0, None))

    def test_K_paren_book_num(self):
        self.assertEqual(
            ft.find_series_in_title("Laundry Lady's Love (Ladies of Sanctuary House Book 1)"),
            ('Ladies of Sanctuary House', 1.0, None))

    def test_I_bracket_index(self):
        self.assertEqual(ft.find_series_in_title('Mistborn [2] - The Well of Ascension'),
                         ('Mistborn', 2.0, None))

    def test_J_inline_num(self):
        self.assertEqual(ft.find_series_in_title('City Of Fire Trilogy 1 - Dreamland'),
                         ('City Of Fire Trilogy', 1.0, None))

    def test_H_series_num_title(self):
        self.assertEqual(
            ft.find_series_in_title('Star Trek: The Original Series - 020 - The Tears of the Singers'),
            ('Star Trek: The Original Series', 20.0, None))

    def test_year_in_parens_not_series(self):
        self.assertEqual(ft.find_series_in_title('The Hobbit (2010)'), (None, None, None))

    def test_generic_book_word_not_series(self):
        self.assertEqual(ft.find_series_in_title('Some Book (Book 2)'), (None, None, None))

    def test_numeric_title_not_series(self):
        self.assertEqual(ft.find_series_in_title('1984'), (None, None, None))

    def test_empty(self):
        self.assertEqual(ft.find_series_in_title(''), (None, None, None))

    def test_author_anchored_index_only(self):
        self.assertEqual(
            ft.find_series_in_title('Linsey Hall - 05 Rise of the Fae', author='Linsey Hall'),
            (None, 5.0, None))


class TestMakeCleanTitle(unittest.TestCase):

    def test_strip_dash_hash(self):
        self.assertEqual(
            ft.make_clean_title('Blackout - John Milton #10', series='John Milton', index=10.0),
            'Blackout')

    def test_strip_paren_hash(self):
        self.assertEqual(
            ft.make_clean_title('The Name of the Wind (The Kingkiller Chronicle, #1)',
                                series='The Kingkiller Chronicle', index=1.0),
            'The Name of the Wind')

    def test_strip_bracket_prefix(self):
        self.assertEqual(
            ft.make_clean_title('Mistborn [2] - The Well of Ascension',
                                series='Mistborn', index=2.0),
            'The Well of Ascension')

    def test_strip_inline_num_prefix(self):
        self.assertEqual(
            ft.make_clean_title('City Of Fire Trilogy 1 - Dreamland',
                                series='City Of Fire Trilogy', index=1.0),
            'Dreamland')

    def test_strip_language_prefix(self):
        self.assertEqual(ft.make_clean_title('(eng) The Hobbit', language='eng'), 'The Hobbit')

    def test_empty_fallback_keeps_original(self):
        self.assertEqual(ft.make_clean_title('John Milton #10', series='John Milton', index=10.0),
                         'John Milton #10')


class TestLanguageAndSubtitle(unittest.TestCase):

    def test_lang_suffix(self):
        self.assertEqual(ft.find_language_in_title('Title (eng)'), 'eng')

    def test_lang_prefix(self):
        self.assertEqual(ft.find_language_in_title('(spa) Título'), 'spa')

    def test_lang_none(self):
        self.assertIsNone(ft.find_language_in_title('Plain Title'))

    def test_subtitle_colon(self):
        self.assertEqual(ft.find_subtitle_in_title('Dune: The Graphic Novel'),
                         'The Graphic Novel')

    def test_subtitle_rejects_series_structure(self):
        self.assertIsNone(
            ft.find_subtitle_in_title('Star Trek: The Original Series - 020 - X'))

    def test_subtitle_none_without_colon(self):
        self.assertIsNone(ft.find_subtitle_in_title('Plain Title'))


class KnownBugs(unittest.TestCase):

    @unittest.expectedFailure
    def test_author_suffix_jr(self):
        self.assertEqual(fa.fix_author('King, Stephen Jr.'), 'Stephen King Jr.')

    @unittest.expectedFailure
    def test_urn_isbn_value_not_normalised(self):
        new, _ = fi.fix_identifiers({'urnisbn': 'urn:isbn:9780007351619'})
        self.assertEqual(new, {'isbn': '9780007351619'})


class TestNewSeriesPatterns(unittest.TestCase):

    def _series(self, title, **kw):
        s, i, _ = ft.find_series_in_title(title, **kw)
        return s, i

    def test_N_colon_novel_book(self):
        self.assertEqual(self._series('Starlight Web: A Moonshadow Bay Novel, Book 1'),
                         ('Moonshadow Bay', 1.0))

    def test_K_paren_series_book(self):
        self.assertEqual(
            self._series("Weaver's Web: A Paranormal Women's Fiction Novel "
                         "(Moonshadow Bay Series Book 6)"),
            ('Moonshadow Bay', 6.0))

    def test_O_series_num_colon(self):
        self.assertEqual(self._series('Harley Merlin 11: Finch Merlin and the Lost Map'),
                         ('Harley Merlin', 11.0))

    def test_M_bracket_name_num_dash(self):
        self.assertEqual(self._series("[Darkblade 01] - The Daemon's Curse"),
                         ('Darkblade', 1.0))

    def test_M_bracket_name_num_bullet(self):
        self.assertEqual(self._series('[Harley Merlin 13] • Finch Merlin and the Locked Gateway'),
                         ('Harley Merlin', 13.0))

    def test_P_series_hash_dash(self):
        self.assertEqual(self._series('Long Price Quartet #04 - The Price Of Spring'),
                         ('Long Price Quartet', 4.0))
        self.assertEqual(self._series('Blue Bloods #5 - Keys to the Repository'),
                         ('Blue Bloods', 5.0))

    def test_Q_series_book_prefix(self):
        self.assertEqual(
            self._series('Hammer of the Gods Book 1 – First Strike: A LitRPG '
                         'Post Apocalyptic Earth Adventure'),
            ('Hammer of the Gods', 1.0))

    def test_normalise_fade_series(self):
        self.assertEqual(self._series('FALLING (FADE Series #2)'), ('FADE', 2.0))

    def test_normalise_trilogy(self):
        self.assertEqual(
            self._series("Wolf's Bane: A Reverse Harem Shifter Romance "
                         "(Shifted Mates Trilogy Book 1)"),
            ('Shifted Mates', 1.0))

    def test_spanish_serie_prefix_and_edition(self):
        self.assertEqual(self._series('Furia (Serie Crave 2) (Spanish Edition)'),
                         ('Crave', 2.0))

    def test_keep_chronicle(self):
        self.assertEqual(self._series('The Name of the Wind (The Kingkiller Chronicle, #1)'),
                         ('The Kingkiller Chronicle', 1.0))

    def test_keep_original_series(self):
        s, _ = self._series('Star Trek: The Original Series - 020 - The Tears of the Singers')
        self.assertEqual(s, 'Star Trek: The Original Series')


class TestNewCleanTitle(unittest.TestCase):

    def test_clean_colon_novel_book(self):
        self.assertEqual(
            ft.make_clean_title('Starlight Web: A Moonshadow Bay Novel, Book 1',
                                series='Moonshadow Bay', index=1.0),
            'Starlight Web')

    def test_clean_bracket_name_num(self):
        self.assertEqual(
            ft.make_clean_title("[Darkblade 01] - The Daemon's Curse",
                                series='Darkblade', index=1.0),
            "The Daemon's Curse")

    def test_clean_series_hash_dash(self):
        self.assertEqual(
            ft.make_clean_title('Long Price Quartet #04 - The Price Of Spring',
                                series='Long Price Quartet', index=4.0),
            'The Price Of Spring')


class TestEditionAndLangStrip(unittest.TestCase):

    def test_spanish_edition(self):
        self.assertEqual(ft.make_clean_title('El Imperio Final (Spanish Edition)'),
                         'El Imperio Final')

    def test_english_edition(self):
        self.assertEqual(ft.make_clean_title('Some Book (English Edition)'), 'Some Book')

    def test_edition_with_series_paren(self):
        self.assertEqual(
            ft.make_clean_title('Furia (Serie Crave 2) (Spanish Edition)',
                                series='Crave', index=2.0),
            'Furia')

    def test_trailing_lang_code(self):
        self.assertEqual(ft.make_clean_title('The Hobbit (eng)'), 'The Hobbit')

    def test_leading_lang_code(self):
        self.assertEqual(ft.make_clean_title('(spa) El Hobbit'), 'El Hobbit')

    def test_roman_numeral_preserved(self):
        self.assertEqual(ft.make_clean_title('Vampiros sureños 06 (II) - Hortera'),
                         'Vampiros sureños 06 (II) - Hortera')


class TestFixWorld(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.rev = fw.load_world_map()

    def test_map_loaded(self):
        self.assertTrue(self.rev, "world_map.json no cargó ninguna entrada")

    def test_cosmere_members(self):
        for s in ('Elantris', 'The Mistborn Saga', 'The Stormlight Archive',
                  'Mistborn: Wax & Wayne'):
            self.assertEqual(fw.world_for_series(s, self.rev), 'The Cosmere')

    def test_hunter_legends(self):
        self.assertEqual(fw.world_for_series('Chronicles of Nick', self.rev),
                         'Hunter Legends')

    def test_case_insensitive(self):
        self.assertEqual(fw.world_for_series('the mistborn saga', self.rev),
                         'The Cosmere')
        self.assertEqual(fw.world_for_series('  ELANTRIS  ', self.rev),
                         'The Cosmere')

    def test_unknown_series(self):
        self.assertIsNone(fw.world_for_series('No Existe', self.rev))

    def test_empty_series(self):
        self.assertIsNone(fw.world_for_series('', self.rev))
        self.assertIsNone(fw.world_for_series(None, self.rev))

    def test_missing_file_safe(self):
        self.assertEqual(fw.load_world_map('/no/existe/world_map.json'), {})


class TestAuthorInTitle(unittest.TestCase):

    def test_suffix_dash_author(self):
        self.assertEqual(ft.make_clean_title('Solos - Adam Baker', author='Adam Baker'),
                         'Solos')

    def test_suffix_author_with_initials(self):
        self.assertEqual(ft.make_clean_title('Hexbreaker - Jordan L. Hawk',
                                             author='Jordan L. Hawk'),
                         'Hexbreaker')

    def test_by_author(self):
        self.assertEqual(ft.make_clean_title('Michael Strogoff by Jules Verne',
                                             author='Jules Verne'),
                         'Michael Strogoff')

    def test_paren_author(self):
        self.assertEqual(
            ft.make_clean_title('Las Doradas Manzanas Del Sol (Ray Bradbury)',
                                author='Ray Bradbury'),
            'Las Doradas Manzanas Del Sol')

    def test_author_sort_swapped(self):
        self.assertEqual(ft.make_clean_title('Solos - Adam Baker',
                                             author_sort='Baker, Adam'),
                         'Solos')

    def test_non_author_suffix_untouched(self):
        self.assertEqual(ft.make_clean_title('The Pirate - A Love Story',
                                             author='Jane Doe'),
                         'The Pirate - A Love Story')

    def test_by_not_author_untouched(self):
        self.assertEqual(ft.make_clean_title('Death by Chocolate',
                                             author='Sally Berneathy'),
                         'Death by Chocolate')


class TestAuthorSeriesNoDash(unittest.TestCase):
    """Patrón F2: 'Autor - Serie N Título' (sin guion antes del título)."""

    def test_karen_hawkins_maclean(self):
        self.assertEqual(
            ft.find_series_in_title(
                'Karen Hawkins - MacLean 1 How to Abduct a Highland Lord',
                author='Karen Hawkins'),
            ('MacLean', 1.0, None))

    def test_karen_hawkins_clean_title(self):
        ds, di, _ = ft.find_series_in_title(
            'Karen Hawkins - MacLean 1 How to Abduct a Highland Lord',
            author='Karen Hawkins')
        self.assertEqual(
            ft.make_clean_title(
                'Karen Hawkins - MacLean 1 How to Abduct a Highland Lord',
                series=ds, index=di, author='Karen Hawkins'),
            'How to Abduct a Highland Lord')

    def test_article_guard(self):
        # "The 39 Steps" no debe partirse en serie "The" #39
        self.assertEqual(
            ft.find_series_in_title('Karen Hawkins - The 39 Steps',
                                    author='Karen Hawkins'),
            (None, None, None))


class TestBookNInSeries(unittest.TestCase):
    """Patrón R: 'Título - Book N in/of [the] Serie [Series]'."""

    def _s(self, t):
        a, i, _ = ft.find_series_in_title(t)
        return a, i

    def test_dash_in_the_series(self):
        self.assertEqual(self._s('Coveted - Book 3 in the Gwen Sparks Series'),
                         ('Gwen Sparks', 3.0))

    def test_colon_in_the_series(self):
        self.assertEqual(
            self._s('Secret Santa Surprise: Book 29 in the Kindred Tales Series'),
            ('Kindred Tales', 29.0))

    def test_paren_of_the_saga(self):
        self.assertEqual(
            self._s('Laugh of Destruction (Book 3 of the Death Incarnate Saga)'),
            ('Death Incarnate Saga', 3.0))

    def test_no_separator_before_book(self):
        self.assertEqual(self._s('Behaving Badly Book 4 in the Action! Series'),
                         ('Action!', 4.0))

    def test_clean_title(self):
        ds, di, _ = ft.find_series_in_title('Coveted - Book 3 in the Gwen Sparks Series')
        self.assertEqual(
            ft.make_clean_title('Coveted - Book 3 in the Gwen Sparks Series',
                                series=ds, index=di),
            'Coveted')

    def test_genre_blurb_rejected(self):
        # "Book 3 of a LitRPG adventure": 'a ...' es descriptor, no serie
        self.assertEqual(
            self._s('Hide and Seek: Apocalypse Parenting, Book 3 of a LitRPG adventure'),
            (None, None))


class TestSeriesValidity(unittest.TestCase):
    """Filtros nuevos (a partir de las correcciones de QRevisar)."""

    def test_year_as_index_rejected(self):
        # "Serie - AÑO - Título": el año no es índice de serie
        self.assertEqual(ft.find_series_in_title('Harlequin Presents March - 2018 - His Mistress'),
                         (None, None, None))
        self.assertEqual(ft.find_series_in_title('NIMWAY HALL 1794 - Charlotte'),
                         (None, None, None))

    def test_looks_like_year_helper(self):
        self.assertTrue(ft._looks_like_year(2018))
        self.assertTrue(ft._looks_like_year(1794))
        self.assertFalse(ft._looks_like_year(8))

    def test_container_words_not_series(self):
        self.assertFalse(ft._is_valid_series('Linear Tactical Boxed Set'))
        self.assertFalse(ft._is_valid_series('Dating Season: Bundle'))
        self.assertFalse(ft._is_valid_series('The Hybrid Omnibus'))

    def test_junk_not_series(self):
        self.assertFalse(ft._is_valid_series('#'))
        self.assertFalse(ft._is_valid_series('c.'))
        self.assertFalse(ft._is_valid_series('mobi v.9/'))
        self.assertFalse(ft._is_valid_series('Pack Promocional Nº'))

    def test_genre_blurb_not_series(self):
        self.assertFalse(ft._is_valid_series('A sexy, funny mystery/romance, Cottonmouth'))
        self.assertFalse(ft._is_valid_series('a contemporary & realistic mfff adventure'))

    def test_real_series_still_valid(self):
        for ok in ('Mistborn', 'Bryant & May', 'Steel Brothers Saga',
                   'The Kingkiller Chronicle', "Jazz's Song"):
            self.assertTrue(ft._is_valid_series(ok), ok)

    def test_hash_inside_paren(self):
        self.assertEqual(ft.find_series_in_title('Enchanted Frost (Frost Series #8)'),
                         ('Frost', 8.0, None))


class TestBracketHashAndParenPrefixSeries(unittest.TestCase):
    """Patrones S y T: serie al PRINCIPIO del título."""

    def _series(self, title, **kw):
        s, i, _ = ft.find_series_in_title(title, **kw)
        return s, i

    def test_S_bracket_hash_prefix(self):
        self.assertEqual(self._series('[Jack Morgan #05] - Private Berlin'),
                         ('Jack Morgan', 5.0))

    def test_T_paren_prefix_no_hash(self):
        self.assertEqual(self._series('(For His Pleasure 11) His Every Word'),
                         ('For His Pleasure', 11.0))
        self.assertEqual(
            self._series('(Marco Didio Falco 10) A Los Leones(c.1)'),
            ('Marco Didio Falco', 10.0))

    def test_T_bare_year_not_series(self):
        # "(2012)" es un año de publicación, no una serie.
        self.assertEqual(self._series('(2012) Evie Undercover'), (None, None))

    def test_S_clean_title(self):
        ds, di, _ = ft.find_series_in_title('[Jack Morgan #05] - Private Berlin')
        self.assertEqual(
            ft.make_clean_title('[Jack Morgan #05] - Private Berlin',
                                series=ds, index=di),
            'Private Berlin')

    def test_T_clean_title(self):
        ds, di, _ = ft.find_series_in_title('(For His Pleasure 11) His Every Word')
        self.assertEqual(
            ft.make_clean_title('(For His Pleasure 11) His Every Word',
                                series=ds, index=di),
            'His Every Word')


class TestYearAndCopyMarkerStrip(unittest.TestCase):
    """Limpieza incondicional de "(YYYY)" y "(c.N)" en make_clean_title."""

    def test_bare_year_prefix_stripped(self):
        self.assertEqual(ft.make_clean_title('(2012) Evie Undercover'),
                         'Evie Undercover')

    def test_bare_year_suffix_stripped(self):
        self.assertEqual(ft.make_clean_title('Evie Undercover (2012)'),
                         'Evie Undercover')

    def test_copy_marker_stripped(self):
        self.assertEqual(
            ft.make_clean_title('(Marco Didio Falco 10) A Los Leones(c.1)',
                                series='Marco Didio Falco', index=10.0),
            'A Los Leones')

    def test_copy_marker_alone_stripped(self):
        self.assertEqual(ft.make_clean_title('A Los Leones(c.1)'), 'A Los Leones')

    def test_paren_book_num_year_rejected(self):
        # Bug corregido en el patrón K: "(Jul 2012)" no debe leerse como
        # serie "Jul" #2012.
        self.assertEqual(
            ft.find_series_in_title('No bajes al sotano (spa) (Jul 2012)'),
            (None, None, None))


class TestFixCommentsHtmlStrip(unittest.TestCase):
    """strip_html / normalize_text: HTML -> texto plano para el analisis."""

    def test_strip_basic_tags(self):
        self.assertEqual(fc.strip_html('<p>Hello <b>world</b></p>'), 'Hello world')

    def test_strip_script_and_style(self):
        self.assertEqual(
            fc.strip_html('<script>alert(1)</script>Texto<style>p{color:red}</style>'),
            'Texto')

    def test_br_becomes_newline(self):
        self.assertEqual(fc.strip_html('Linea uno<br>Linea dos'), 'Linea uno\nLinea dos')

    def test_block_close_becomes_newline(self):
        # La etiqueta de apertura del bloque siguiente se convierte en un
        # espacio (via _TAG_RE), por eso queda un espacio tras el salto.
        self.assertEqual(fc.strip_html('<p>A</p><p>B</p>'), 'A\n B')

    def test_html_entities_unescaped(self):
        self.assertEqual(fc.strip_html('Ni&ntilde;o &amp; perro'), 'Niño & perro')

    def test_empty_string(self):
        self.assertEqual(fc.strip_html(''), '')

    def test_none(self):
        self.assertEqual(fc.strip_html(None), '')

    def test_normalize_lowercases_and_collapses_whitespace(self):
        self.assertEqual(fc.normalize_text('  CAFÉ   con   leche  '), 'café con leche')

    def test_normalize_empty(self):
        self.assertEqual(fc.normalize_text(''), '')


class TestAnalyzeComment(unittest.TestCase):
    """analyze_comment: codigos de issue sobre el texto ya limpio."""

    VALID = ('<p>Este es un relato apasionante sobre un joven mago que descubre un '
             'mundo oculto lleno de magia y peligros inesperados.</p>'
             '<p>A lo largo de su viaje debe enfrentar enemigos poderosos, forjar '
             'alianzas inquebrantables y desentranar secretos que cambiaran su '
             'destino para siempre, mientras aprende el significado del coraje.</p>')

    def test_valid_synopsis_no_issues(self):
        self.assertEqual(fc.analyze_comment(self.VALID), [])

    def test_empty_html_is_vacio_only(self):
        self.assertEqual(fc.analyze_comment(''), [fc.ISSUE_EMPTY])

    def test_tags_only_is_vacio(self):
        # Sin texto util tras quitar las etiquetas -> vacio, no basura ni corto.
        self.assertEqual(fc.analyze_comment('<p>&nbsp;</p>'), [fc.ISSUE_EMPTY])

    def test_short_comment_flagged_corto(self):
        self.assertIn(fc.ISSUE_SHORT, fc.analyze_comment('<p>Un libro corto.</p>'))

    def test_long_comment_flagged_largo(self):
        sentences = [
            'Frase numero {} que aporta contenido distinto para evitar '
            'repeticiones internas y alargar el texto.'.format(i)
            for i in range(60)
        ]
        longtext = '<p>' + ' '.join(sentences) + '</p>'
        self.assertEqual(fc.analyze_comment(longtext), [fc.ISSUE_LONG])

    def test_internal_repeat_flagged(self):
        seg = ('Esta frase se repite exactamente dos veces dentro del mismo '
               'comentario para la prueba')
        rep_text = (
            '<p>{seg}. Texto de relleno para superar el minimo de caracteres y '
            'palabras requerido en el analisis del comentario, anadiendo contexto '
            'adicional sobre la trama y los personajes principales de la '
            'historia.</p><p>{seg}.</p>'
        ).format(seg=seg)
        self.assertEqual(fc.analyze_comment(rep_text), [fc.ISSUE_REPEAT])

    def test_junk_boilerplate_phrase(self):
        self.assertIn(fc.ISSUE_JUNK, fc.analyze_comment('<p>Sinopsis no disponible.</p>'))

    def test_junk_site_watermark(self):
        self.assertIn(fc.ISSUE_JUNK,
                      fc.analyze_comment('<p>Descargado de epublibre.org</p>'))

    def test_junk_url(self):
        self.assertIn(fc.ISSUE_JUNK, fc.analyze_comment(
            '<p>Visita http://example.com para mas info sobre este libro y '
            'muchos otros titulos disponibles para descargar gratis ahora '
            'mismo.</p>'))

    def test_junk_mojibake(self):
        self.assertIn(fc.ISSUE_JUNK, fc.analyze_comment(
            '<p>Texto con caracteres mal codificados como Ã© y Ã± que aparecen '
            'por errores de codificacion en el origen del archivo original.</p>'))


class TestDuplicateFingerprint(unittest.TestCase):
    """duplicate_fingerprint: deteccion de sinopsis compartida entre libros."""

    def test_short_text_returns_none(self):
        self.assertIsNone(fc.duplicate_fingerprint('<p>Corto.</p>'))

    def test_long_text_returns_fingerprint(self):
        self.assertIsNotNone(fc.duplicate_fingerprint(TestAnalyzeComment.VALID))

    def test_fingerprint_ignores_case_and_html(self):
        a = fc.duplicate_fingerprint('<p>HOLA MUNDO ' + 'x' * 60 + '</p>')
        b = fc.duplicate_fingerprint('<p>hola mundo ' + 'X' * 60 + '</p>')
        self.assertEqual(a, b)



class TestDetectExtraSections(unittest.TestCase):
    """detect_extra_sections: About the Author / Praise / Reviews / Excerpt."""

    def test_no_sections_in_plain_synopsis(self):
        text = fc.strip_html(TestAnalyzeComment.VALID)
        self.assertEqual(fc.detect_extra_sections(text), ((), None))

    def test_about_author_heading_detected(self):
        text = fc.strip_html(
            '<p>Sinopsis del libro.</p><p><b>About the Author</b></p>'
            '<p>Biografia de la autora.</p>')
        labels, cutoff = fc.detect_extra_sections(text)
        self.assertEqual(labels, ('about_author',))
        self.assertIsNotNone(cutoff)

    def test_praise_for_heading_detected(self):
        text = fc.strip_html('<p>Sinopsis.</p><p><b>Praise for The Book</b></p>')
        labels, _ = fc.detect_extra_sections(text)
        self.assertEqual(labels, ('praise',))

    def test_editorial_reviews_heading_detected(self):
        text = fc.strip_html('<p>Sinopsis.</p><p><b>Editorial Reviews</b></p>')
        labels, _ = fc.detect_extra_sections(text)
        self.assertEqual(labels, ('reviews',))

    def test_excerpt_heading_detected(self):
        text = fc.strip_html('<p>Sinopsis.</p><p><b>Excerpt</b></p>')
        labels, _ = fc.detect_extra_sections(text)
        self.assertEqual(labels, ('excerpt',))

    def test_praise_mid_sentence_not_a_heading(self):
        # "Praise" dentro de una frase larga de prosa no debe contarse como
        # cabecera de seccion (no es una linea corta independiente).
        text = ('Praise for her earlier novels poured in from critics across the '
                'country, cementing her reputation as one of the most exciting '
                'voices in contemporary fiction today according to major outlets.')
        labels, cutoff = fc.detect_extra_sections(text)
        self.assertEqual(labels, ())
        self.assertIsNone(cutoff)


class TestAnalyzeCommentExtraSections(unittest.TestCase):
    """analyze_comment: las secciones extra cuentan como basura, no HTML per se."""

    SYNOPSIS = ('Un joven detective debe resolver el misterio de una mansion '
                'abandonada antes de que el culpable escape para siempre, '
                'enfrentando pistas falsas y peligros inesperados en cada rincon '
                'de la casa mientras la tormenta arrecia fuera, y descubriendo '
                'secretos familiares que llevaban decadas ocultos.')

    def test_about_author_flagged_as_junk(self):
        html = ('<p>{}</p><p><b>About the Author</b></p>'
                '<p>Biografia de la autora con mas de veinte novelas publicadas '
                'y traducidas a quince idiomas alrededor del mundo.</p>'
               ).format(self.SYNOPSIS)
        self.assertIn(fc.ISSUE_JUNK, fc.analyze_comment(html))

    def test_plain_html_formatting_is_not_junk(self):
        # El marcado HTML en si (negrita, parrafos, listas) no es basura por
        # defecto; solo lo son las secciones especificas (About the Author,
        # Praise, Reviews, Excerpt) u otras senales de basura ya conocidas.
        html = '<p><b>{}</b></p><ul><li>Detalle uno</li></ul>'.format(self.SYNOPSIS)
        self.assertNotIn(fc.ISSUE_JUNK, fc.analyze_comment(html))

    def test_long_appendix_does_not_flag_largo(self):
        # Sinopsis normal + una seccion "Praise for" muy larga: antes se
        # marcaba "largo" solo por el apendice; ahora no, porque la
        # longitud se mide sobre la sinopsis real (antes de la cabecera).
        # Si se marca como basura (correcto), pero no como largo.
        praise = ' '.join(
            'Cita de elogio numero {} de un critico distinto sobre esta novela.'.format(i)
            for i in range(80))
        html = '<p>{}</p><p><b>Praise for The Book</b></p><p>{}</p>'.format(
            self.SYNOPSIS, praise)
        self.assertGreater(len(fc.strip_html(html)), fc.MAX_CHARS)
        issues = fc.analyze_comment(html)
        self.assertNotIn(fc.ISSUE_LONG, issues)
        self.assertIn(fc.ISSUE_JUNK, issues)

    def test_thin_synopsis_with_bio_flagged_corto(self):
        # Sinopsis real muy corta + biografia larga: el total "parece"
        # suficiente, pero la sinopsis de verdad es corta y debe marcarse,
        # ademas de basura por la seccion adicional.
        short_syn = 'Una historia de amor y traicion en tiempos de guerra.'
        bio = ' '.join(
            'Dato biografico numero {} sobre la autora y su carrera literaria.'.format(i)
            for i in range(15))
        html = '<p>{}</p><p><b>About the Author</b></p><p>{}</p>'.format(
            short_syn, bio)
        issues = fc.analyze_comment(html)
        self.assertIn(fc.ISSUE_SHORT, issues)
        self.assertIn(fc.ISSUE_JUNK, issues)

    def test_heading_at_very_start_falls_back_to_full_text(self):
        # Si la cabecera aparece casi al principio (sin sinopsis previa
        # real), no hay "nucleo" fiable que medir: se usa el texto completo.
        html = '<p>Excerpt</p><p>{}</p>'.format(self.SYNOPSIS)
        issues = fc.analyze_comment(html)
        self.assertIn(fc.ISSUE_JUNK, issues)
        self.assertNotIn(fc.ISSUE_SHORT, issues)



class TestQRevisar2CorrectionRound(unittest.TestCase):
    """Correcciones de la 2a ronda de revision del Excel (QRevisar,
    2026-07-19): ver notas de Yolanda en propuestas_serie_subtitulo.xlsx."""

    def _series(self, title, **kw):
        s, i, sub = ft.find_series_in_title(title, **kw)
        return s, i, sub

    def test_complete_series_stays_in_title(self):
        # "Cuando es Complete Series / Boxed Set debe mantenerse como titulo"
        title = ('Whatever He Wants: The Complete Series '
                  '(An Alpha Billionaire Romance)')
        self.assertIsNone(ft.find_subtitle_in_title(
            ft.make_clean_title(title)))
        self.assertEqual(ft.make_clean_title(title), title)

    def test_boxed_set_stays_in_title(self):
        title = 'The Essential Elements: Boxed Set'
        self.assertIsNone(ft.find_subtitle_in_title(title))
        self.assertEqual(ft.make_clean_title(title), title)

    def test_subtitle_splits_on_last_colon_not_first(self):
        # Con 2+ ":", el titulo se queda con todo salvo el ultimo tramo.
        self.assertEqual(
            ft.find_subtitle_in_title('Istoria Online: Square One: A LitRPG Adventure'),
            'A LitRPG Adventure')

    def test_subtitle_last_colon_main_title(self):
        clean = 'Istoria Online: Square One: A LitRPG Adventure'
        sub = ft.find_subtitle_in_title(clean)
        main = clean.rpartition(': ')[0].strip()
        self.assertEqual(main, 'Istoria Online: Square One')
        self.assertEqual(sub, 'A LitRPG Adventure')

    def test_book_n_in_series_word_number(self):
        # "Se debe considerar el numero de la serie escrito tambien en palabras"
        self.assertEqual(
            self._series('Broken Mirrors: Book One of the Broken Mirrors Duology'),
            ('Broken Mirrors Duology', 1.0, None))
        self.assertEqual(
            self._series('Broken Lords: Book Two of the Broken Mirrors Duology'),
            ('Broken Mirrors Duology', 2.0, None))

    def test_book_n_in_series_word_number_clean_title(self):
        s, i, _ = self._series(
            'Broken Mirrors: Book One of the Broken Mirrors Duology')
        self.assertEqual(
            ft.make_clean_title(
                'Broken Mirrors: Book One of the Broken Mirrors Duology',
                series=s, index=i),
            'Broken Mirrors')

    def test_series_colon_volume_colon_title(self):
        # "Volume 9 significa el libro 9 de la serie"
        self.assertEqual(
            self._series('The Atomic Sea: Volume Nine: War of the Abyss'),
            ('The Atomic Sea', 9.0, None))

    def test_series_colon_volume_colon_title_clean(self):
        s, i, _ = self._series('The Atomic Sea: Volume Nine: War of the Abyss')
        self.assertEqual(
            ft.make_clean_title('The Atomic Sea: Volume Nine: War of the Abyss',
                                series=s, index=i),
            'War of the Abyss')

    def test_title_colon_series_bare_word_number(self):
        self.assertEqual(
            self._series('Swordfall: Fall Trilogy Two'),
            ('Fall Trilogy', 2.0, None))

    def test_title_colon_series_bare_word_number_clean(self):
        s, i, _ = self._series('Swordfall: Fall Trilogy Two')
        self.assertEqual(
            ft.make_clean_title('Swordfall: Fall Trilogy Two', series=s, index=i),
            'Swordfall')

    def test_title_colon_series_bare_word_number_with_comma(self):
        # "Titulo: Serie, N" -- la coma antes del numero NO debe quedar
        # pegada al nombre de la serie (bug encontrado en un libro real:
        # "Claimings," en vez de "Claimings").
        self.assertEqual(
            self._series('Swordfall: Fall Trilogy, Two'),
            ('Fall Trilogy', 2.0, None))

    def test_title_colon_series_hash_with_comma(self):
        # "Titulo: Serie, #N" -- mismo bug que el anterior pero con "#N".
        # Caso real: "Assimilation, Love, and Other Human Oddities:
        # Claimings, #2".
        self.assertEqual(
            self._series(
                'Assimilation, Love, and Other Human Oddities: '
                'Claimings, #2'),
            ('Claimings', 2.0, None))

    def test_title_colon_series_hash_with_comma_clean(self):
        s, i, _ = self._series(
            'Assimilation, Love, and Other Human Oddities: Claimings, #2')
        self.assertEqual(
            ft.make_clean_title(
                'Assimilation, Love, and Other Human Oddities: '
                'Claimings, #2',
                series=s, index=i),
            'Assimilation, Love, and Other Human Oddities')

    def test_colon_series_book_n_with_trailing_subtitle(self):
        # "Titulo: Serie Book N: Subtitulo" -- el N ya no exige fin de cadena.
        self.assertEqual(
            self._series('Fighting Midnight: Ankarrah Chronicles Book Two: '
                         'A Paranormal Urban Fantasy'),
            ('Ankarrah Chronicles', 2.0, 'A Paranormal Urban Fantasy'))

    def test_colon_series_book_n_with_trailing_subtitle_clean(self):
        s, i, sub = self._series(
            'Fighting Midnight: Ankarrah Chronicles Book Two: '
            'A Paranormal Urban Fantasy')
        self.assertEqual(
            ft.make_clean_title(
                'Fighting Midnight: Ankarrah Chronicles Book Two: '
                'A Paranormal Urban Fantasy',
                series=s, index=i, subtitle=sub),
            'Fighting Midnight')

    def test_series_no_trailing_dash(self):
        # "La serie no debe terminar con - o :"
        self.assertEqual(
            self._series('The Faceless Ones (Skulduggery Pleasant - Book 3)'),
            ('Skulduggery Pleasant', 3.0, None))

    def test_series_no_trailing_dash_clean_title(self):
        s, i, _ = self._series('The Faceless Ones (Skulduggery Pleasant - Book 3)')
        self.assertEqual(
            ft.make_clean_title('The Faceless Ones (Skulduggery Pleasant - Book 3)',
                                series=s, index=i),
            'The Faceless Ones')

    def test_normalize_series_name_strips_trailing_dash_and_colon(self):
        self.assertEqual(ft._normalize_series_name('Skulduggery Pleasant -'),
                         'Skulduggery Pleasant')
        self.assertEqual(ft._normalize_series_name('Fall Trilogy:'),
                         'Fall')  # "Trilogy" is itself a stripped descriptor
        self.assertEqual(ft._normalize_series_name('Mistborn:'),
                         'Mistborn')

    def test_doctor_who_ambiguous_case_untouched(self):
        # "Dificil de diferenciar, quizas solo se pueda manualmente" -- no
        # existe patron de serie para esto, asi que solo entra por el
        # subtitulo generico de un colon; se documenta el comportamiento
        # actual (no se intenta “arreglar”, queda para revision manual).
        self.assertEqual(ft.find_subtitle_in_title('Doctor Who: Wetworld'),
                         'Wetworld')


class TestSerieGen(unittest.TestCase):
    """Campo nuevo Serie_Gen: universo/imprint SIN numero, distinto de
    `series` (que siempre lleva indice). Pedido explicito de Yolanda tras la
    2a ronda de revision, sobre las filas marcadas "?quizas world? ?otro
    campo?" (nunca implementadas como `series` porque no tienen numero)."""

    def test_paren_after_subtitle_colon(self):
        self.assertEqual(
            ft.find_generic_series_in_title(
                'The Library: Where Life Checks Out (American Haunts)'),
            'American Haunts')

    def test_paren_after_subtitle_colon_2(self):
        self.assertEqual(
            ft.find_generic_series_in_title(
                'Tormented Part 2: A Dark High School Bully Romance '
                '(Elginvale High)'),
            'Elginvale High')

    def test_paren_with_internal_colon_no_subtitle(self):
        # El ":" esta DENTRO del parentesis, no hay subtitulo por fuera.
        self.assertEqual(
            ft.find_generic_series_in_title('Voodoo (Royal Bastards MC: Ankeny IA)'),
            'Royal Bastards MC: Ankeny IA')

    def test_strip_from_title(self):
        sg = ft.find_generic_series_in_title('Voodoo (Royal Bastards MC: Ankeny IA)')
        self.assertEqual(
            ft.strip_generic_series_paren('Voodoo (Royal Bastards MC: Ankeny IA)', sg),
            'Voodoo')

    def test_make_clean_title_strips_serie_gen(self):
        title = 'The Library: Where Life Checks Out (American Haunts)'
        sg = ft.find_generic_series_in_title(title)
        self.assertEqual(
            ft.make_clean_title(title, serie_gen=sg),
            'The Library: Where Life Checks Out')

    def test_numbered_paren_not_claimed(self):
        # Cualquier numero en el parentesis -> es una serie normal (con
        # indice), no Serie_Gen; lo gestiona find_series_in_title.
        self.assertIsNone(
            ft.find_generic_series_in_title(
                'The Faceless Ones (Skulduggery Pleasant - Book 3)'))

    def test_language_code_not_claimed(self):
        self.assertIsNone(ft.find_generic_series_in_title('The Hobbit (eng)'))

    def test_edition_note_not_claimed(self):
        self.assertIsNone(
            ft.find_generic_series_in_title('El Imperio Final (Spanish Edition)'))

    def test_bare_year_not_claimed(self):
        self.assertIsNone(ft.find_generic_series_in_title('Evie Undercover (2012)'))

    def test_copy_marker_not_claimed(self):
        self.assertIsNone(ft.find_generic_series_in_title('A Los Leones(c.1)'))

    def test_genre_blurb_not_claimed(self):
        self.assertIsNone(
            ft.find_generic_series_in_title(
                'Whatever He Wants: The Complete Series '
                '(An Alpha Billionaire Romance)'))

    def test_translated_by_byline_not_claimed(self):
        # "(Translated by X)" no es una etiqueta de universo/imprint, es un
        # credito de traduccion -- bug real reportado por Yolanda: se estaba
        # borrando cualquier parentesis final sin numero, incluidos estos.
        self.assertIsNone(
            ft.find_generic_series_in_title(
                'War and Peace (Translated by Louise and Aylmer Maude)'))

    def test_read_by_byline_not_claimed(self):
        self.assertIsNone(
            ft.find_generic_series_in_title(
                'A Christmas Carol (Read by Tim Curry)'))

    def test_unabridged_not_claimed(self):
        self.assertIsNone(
            ft.find_generic_series_in_title('Moby Dick (Unabridged)'))

    def test_annotated_not_claimed(self):
        self.assertIsNone(
            ft.find_generic_series_in_title('Pride and Prejudice (Annotated)'))

    def test_large_print_not_claimed(self):
        self.assertIsNone(
            ft.find_generic_series_in_title('The Hobbit (Large Print)'))

    def test_with_new_introduction_not_claimed(self):
        self.assertIsNone(
            ft.find_generic_series_in_title(
                'Some Book (With a New Introduction)'))
        self.assertIsNone(
            ft.find_generic_series_in_title(
                'Some Book (With a New Introduction by John Smith)'))

    def test_real_universe_tag_still_claimed(self):
        # Los casos reales de Serie_Gen (Ronda 2) siguen funcionando tras
        # anadir las exclusiones de byline/formato de arriba.
        self.assertEqual(
            ft.find_generic_series_in_title(
                'The Library: Where Life Checks Out (American Haunts)'),
            'American Haunts')

    def test_complete_series_paren_not_claimed(self):
        self.assertIsNone(
            ft.find_generic_series_in_title('Something (The Complete Series)'))

    def test_no_trailing_paren_returns_none(self):
        self.assertIsNone(ft.find_generic_series_in_title('Plain Title'))

    def test_empty_title(self):
        self.assertIsNone(ft.find_generic_series_in_title(''))
        self.assertIsNone(ft.find_generic_series_in_title(None))

    def test_strip_generic_series_paren_noop_without_match(self):
        self.assertEqual(
            ft.strip_generic_series_paren('Plain Title', None), 'Plain Title')
        self.assertEqual(
            ft.strip_generic_series_paren('Plain Title', 'Nope'), 'Plain Title')


def _round3_pipeline(title, author=None):
    """Mini-replica of action.py's detection cascade (serie_gen -> series ->
    subtitle cascade -> series+index fallback), used to test the pieces
    together the same way action.py wires them. Despite the name this now
    matches the CURRENT (round-4) action.py logic, including the "not
    subtitle" fallback guard and the serie_gen step -- kept as one shared
    helper rather than forking a near-duplicate for round 4."""
    title_for_detection = ft.strip_known_author_suffix(title, author=author)
    sg = ft.find_generic_series_in_title(title_for_detection)
    if sg:
        title_for_detection = ft.strip_generic_series_paren(title_for_detection, sg)
    found_series, found_index, sub_g = ft.find_series_in_title(
        title_for_detection, author=author)
    clean = ft.make_clean_title(title, series=found_series, index=found_index,
                                 author=author, subtitle=sub_g, serie_gen=sg)
    sub_colon = None
    if not sub_g:
        sub_colon = ft.find_subtitle_in_title(clean)
        if sub_colon:
            main = clean.rpartition(': ')[0].strip()
            if main and main != clean:
                clean = main
        else:
            sub_colon = ft.find_dash_genre_subtitle_in_title(clean)
            if sub_colon:
                main = clean.rpartition(' - ')[0].strip()
                if main and main != clean:
                    clean = main
            else:
                sub_colon = ft.find_paren_genre_subtitle_in_title(clean)
                if sub_colon:
                    import re as _re
                    main = _re.sub(r'\s*\(' + _re.escape(sub_colon) + r'\)\s*$',
                                    '', clean, flags=_re.IGNORECASE).strip()
                    if main and main != clean:
                        clean = main
    subtitle = sub_g or sub_colon
    # "not subtitle" guard (v1.7.8 fix): the blurb-shape fallback must only
    # look at `clean` when NO subtitle was already carved out of it above --
    # otherwise a perfectly good title that just happens to start with "A"
    # and contain a blurb word ("A Novel Way to Die") gets wrongly replaced
    # by the fallback after its real subtitle was already split off cleanly.
    if found_series and clean and not subtitle and ft.whole_title_is_genre_blurb(clean):
        subtitle = clean
        idx_txt = ('%g' % found_index) if found_index is not None else ''
        clean = (found_series + (' ' + idx_txt if idx_txt else '')).strip()
    elif found_series and not clean:
        idx_txt = ('%g' % found_index) if found_index is not None else ''
        clean = (found_series + (' ' + idx_txt if idx_txt else '')).strip()
    return clean, found_series, found_index, subtitle, sg


class TestRound3SubtitleDecoupledFromSeries(unittest.TestCase):
    """Ronda 3: el subtitulo ya NO depende de "no se detecto serie" -- se
    detecta siempre que find_series_in_title no haya devuelto ya uno (sub_g).
    Casos reales de la 3a ronda de revision de Yolanda (filas 46-178 del
    Excel, el subconjunto fiable -- ver memoria del proyecto)."""

    def test_series_and_colon_subtitle_together(self):
        # Antes: al detectarse serie, el subtitulo NUNCA se buscaba.
        clean, series, index, subtitle, _sg = _round3_pipeline(
            'Tormented: A Dark High School Bully Romance '
            '(Elginvale High Book 1)', author='Esme Devlin')
        self.assertEqual(clean, 'Tormented')
        self.assertEqual(series, 'Elginvale High')
        self.assertEqual(index, 1.0)
        self.assertEqual(subtitle, 'A Dark High School Bully Romance')

    def test_series_and_colon_subtitle_together_2(self):
        clean, series, index, subtitle, _sg = _round3_pipeline(
            'The Correction of Folly: A Sense and Sensibility Variation '
            '(What Might Have Been Book 1)', author='Christine Combe')
        self.assertEqual(clean, 'The Correction of Folly')
        self.assertEqual(series, 'What Might Have Been')
        self.assertEqual(subtitle, 'A Sense and Sensibility Variation')


class TestRound3DashAndParenSubtitleDetectors(unittest.TestCase):

    def test_dash_genre_subtitle(self):
        self.assertEqual(
            ft.find_dash_genre_subtitle_in_title(
                'Wanted By The Billionaire Cowboy - A Second Chance Romance'),
            'A Second Chance Romance')

    def test_dash_genre_subtitle_end_to_end(self):
        clean, series, index, subtitle, _sg = _round3_pipeline(
            'Wanted By The Billionaire Cowboy - A Second Chance Romance '
            '(Billionaire Cowboys Book 6)', author='Holly Rayner')
        self.assertEqual(clean, 'Wanted By The Billionaire Cowboy')
        self.assertEqual(series, 'Billionaire Cowboys')
        self.assertEqual(subtitle, 'A Second Chance Romance')

    def test_paren_genre_subtitle(self):
        self.assertEqual(
            ft.find_paren_genre_subtitle_in_title(
                "Where there's a Will... (A Novel)"),
            'A Novel')

    def test_dash_no_genre_shape_returns_none(self):
        # Sin forma de blurb de genero (no empieza por "a"/"an" + palabra de
        # genero) -> no se reclama como subtitulo por este detector.
        self.assertIsNone(
            ft.find_dash_genre_subtitle_in_title('Some Title - Just A Place'))

    def test_paren_no_genre_shape_returns_none(self):
        self.assertIsNone(
            ft.find_paren_genre_subtitle_in_title('Some Title (Some Place)'))


class TestRound3NumInSeriesQuotedPattern(unittest.TestCase):
    """Patron NIS: "Titulo, No. N in the ['the ]Series 'Nombre'[ series]"."""

    def test_basic(self):
        series, index, sub = ft.find_series_in_title(
            "Girl on a Train, No. 1 in the 'Tempted by her Student' series "
            "(lesbian erotica)")
        self.assertEqual(series, 'Tempted by her Student')
        self.assertEqual(index, 1.0)

    def test_series_name_with_apostrophe(self):
        # El nombre de la serie contiene un apostrofo recto ("Amy's") que no
        # debe confundirse con la comilla de cierre.
        series, index, sub = ft.find_series_in_title(
            "Big City Massage (Lesbian Seduction): No. 1 in the Series "
            "'Amy's Adventures in New York'")
        self.assertEqual(series, "Amy's Adventures in New York")
        self.assertEqual(index, 1.0)

    def test_trailing_paren_left_for_downstream(self):
        # El parentesis final tras "series" NO se consume aqui -- queda para
        # que serie_gen/subtitulo lo procesen despues.
        clean = ft.make_clean_title(
            "Girl on a Train, No. 1 in the 'Tempted by her Student' series "
            "(lesbian erotica)",
            series='Tempted by her Student', index=1.0)
        self.assertEqual(clean, 'Girl on a Train (lesbian erotica)')

    def test_apostrophe_series_clean_title(self):
        clean = ft.make_clean_title(
            "Big City Massage (Lesbian Seduction): No. 1 in the Series "
            "'Amy's Adventures in New York'",
            series="Amy's Adventures in New York", index=1.0)
        self.assertEqual(clean, 'Big City Massage (Lesbian Seduction)')


class TestRound3TrailingDanglingSeparator(unittest.TestCase):

    def test_dangling_colon_after_paren_strip(self):
        self.assertEqual(
            ft.make_clean_title('Justice Unserved: (Nathan Doe Series Book 1)',
                                 series='Nathan Doe Series Book', index=1.0),
            'Justice Unserved')

    def test_no_dangling_separator_left_alone(self):
        # Un titulo normal, sin nada que limpiar, no debe verse afectado.
        self.assertEqual(
            ft.make_clean_title('A Perfectly Normal Title'),
            'A Perfectly Normal Title')


class TestRound3WordNumberBookPrefixCleanTitle(unittest.TestCase):
    """make_clean_title ahora usa el mismo _NUM (con soporte de numeros en
    palabra) que el patron Q de deteccion -- antes solo aceptaba digitos,
    dejando "Book Three:" pegado al titulo aunque la serie SI se detectara
    bien."""

    def test_word_number_book_prefix_stripped(self):
        clean, series, index, subtitle, _sg = _round3_pipeline(
            'NO ROAD HOME Book Three: Risen', author='John Prescott')
        self.assertEqual(clean, 'Risen')
        self.assertEqual(series, 'NO ROAD HOME')
        self.assertEqual(index, 3.0)
        self.assertIsNone(subtitle)

    def test_word_number_book_prefix_stripped_2(self):
        clean, series, index, subtitle, _sg = _round3_pipeline(
            'NO ROAD HOME Book Two: Hunter, Hunted', author='John Prescott')
        self.assertEqual(clean, 'Hunter, Hunted')
        self.assertEqual(series, 'NO ROAD HOME')
        self.assertEqual(index, 2.0)
        self.assertIsNone(subtitle)


class TestRound3SeriesPlusIndexFallback(unittest.TestCase):
    """Cuando lo que queda tras quitar la serie es solo un blurb generico
    repetido en todo el volumen (no un titulo real de este libro concreto),
    el titulo pasa a ser "Serie N" y el blurb se guarda como subtitulo."""

    def test_whole_remainder_is_genre_blurb(self):
        self.assertTrue(
            ft.whole_title_is_genre_blurb('An Erotic Short Story Bundle'))

    def test_fallback_title_becomes_series_plus_index(self):
        clean, series, index, subtitle, _sg = _round3_pipeline(
            'Futanarium 3: An Erotic Short Story Bundle', author='Maria N. Lang')
        self.assertEqual(clean, 'Futanarium 3')
        self.assertEqual(series, 'Futanarium')
        self.assertEqual(index, 3.0)
        self.assertEqual(subtitle, 'An Erotic Short Story Bundle')

    def test_fallback_title_becomes_series_plus_index_2(self):
        clean, series, index, subtitle, _sg = _round3_pipeline(
            'Futanarium 1: An Erotic Short Story Bundle', author='Maria N. Lang')
        self.assertEqual(clean, 'Futanarium 1')
        self.assertEqual(subtitle, 'An Erotic Short Story Bundle')

    def test_normal_remainder_not_treated_as_blurb(self):
        # Un titulo real (no un blurb generico) tras quitar la serie no debe
        # activar el fallback -- se queda como titulo normal.
        clean, series, index, subtitle, _sg = _round3_pipeline(
            'NO ROAD HOME Book Three: Risen', author='John Prescott')
        self.assertEqual(clean, 'Risen')
        self.assertNotEqual(clean, 'NO ROAD HOME 3')


class TestRound4CorrectionBatch(unittest.TestCase):
    """Ronda 4 (v1.7.8): 17 filas corregidas por Yolanda directamente en el
    Excel de propuestas (columnas titulo_correcto/serie_correcta/etc.), tras
    revisar el fichero de la ronda 3."""

    def test_dash_blurb_series_book(self):
        # Patron NB: "Titulo: Blurb - Serie - Book N" -- el blurb de genero
        # no debe fusionarse con la serie real.
        clean, series, index, subtitle, _sg = _round3_pipeline(
            'When Noonday Ends: A Southern Romantic-Suspense Novel - '
            'Nantahala - Book Two', author='Carmen DeSousa')
        self.assertEqual(clean, 'When Noonday Ends')
        self.assertEqual(series, 'Nantahala')
        self.assertEqual(index, 2.0)
        self.assertEqual(subtitle, 'A Southern Romantic-Suspense Novel')

    def test_colon_series_dash_book_stripped(self):
        # make_clean_title ahora tolera "-" (no solo ",") entre la serie y
        # "Book N" al limpiar el titulo (patron N).
        clean, series, index, subtitle, _sg = _round3_pipeline(
            'A New Paige: Stained Souls MC - Book 2', author='Zara Teleg')
        self.assertEqual(clean, 'A New Paige')
        self.assertEqual(series, 'Stained Souls MC')
        self.assertEqual(index, 2.0)
        self.assertIsNone(subtitle)

    def test_fallback_does_not_override_real_subtitle_split(self):
        # Fix critico: el fallback de "titulo=serie+indice" ya NO se dispara
        # si el cascade de subtitulo YA separo un subtitulo real -- antes
        # "A Novel Way to Die" (titulo real, ya separado de su subtitulo)
        # volvia a evaluarse y, por casualidad, tambien tiene forma de blurb
        # ("A" + "Novel"), asi que se sustituia por error.
        clean, series, index, subtitle, _sg = _round3_pipeline(
            'A Novel Way to Die: a reverse harem murder mystery '
            '(Nevermore Bookshop Mysteries Book 6)', author='Steffanie Holmes')
        self.assertEqual(clean, 'A Novel Way to Die')
        self.assertEqual(series, 'Nevermore Bookshop Mysteries')
        self.assertEqual(index, 6.0)
        self.assertEqual(subtitle, 'a reverse harem murder mystery')

    def test_hash_dash_no_spaces(self):
        # Patron P: el guion entre "#N" y el titulo puede no llevar espacios.
        clean, series, index, subtitle, _sg = _round3_pipeline(
            'Blaze of Glory #1-Death From on High: An action adventure '
            'adult western', author='A. M. Van Dorn')
        self.assertEqual(clean, 'Death From on High')
        self.assertEqual(series, 'Blaze of Glory')
        self.assertEqual(index, 1.0)
        self.assertEqual(subtitle, 'An action adventure adult western')

    def test_colon_series_hash_no_keyword(self):
        # Patron AB nuevo: "Titulo: Serie #N" sin palabra clave Book/Volume.
        clean, series, index, subtitle, sg = _round3_pipeline(
            'The Worst Reunion Ever: Kate & Kylie Mystery #3 '
            '(Kate & Kylie Mysteries)', author='Charlotte Moore')
        self.assertEqual(clean, 'The Worst Reunion Ever')
        self.assertEqual(series, 'Kate & Kylie Mystery')
        self.assertEqual(index, 3.0)
        self.assertEqual(sg, 'Kate & Kylie Mysteries')

    def test_mid_paren_series_with_colon_subtitle(self):
        # Patron K2 nuevo: parentesis serie+indice en medio del titulo,
        # seguido de ": Subtitulo" (no al final de cadena como el patron K).
        clean, series, index, subtitle, _sg = _round3_pipeline(
            'Alex (Heroes MC Fort Dix 1): MC Romance Suspense',
            author='AUTUMN SUMMERS')
        self.assertEqual(clean, 'Alex')
        self.assertEqual(series, 'Heroes MC Fort Dix')
        self.assertEqual(index, 1.0)
        self.assertEqual(subtitle, 'MC Romance Suspense')

    def test_mid_paren_series_with_colon_subtitle_2(self):
        clean, series, index, subtitle, _sg = _round3_pipeline(
            'Digger (Heroes MC Fort Dix 3): MC Romance Enemies To Lovers',
            author='AUTUMN SUMMERS')
        self.assertEqual(clean, 'Digger')
        self.assertEqual(series, 'Heroes MC Fort Dix')
        self.assertEqual(index, 3.0)
        self.assertEqual(subtitle, 'MC Romance Enemies To Lovers')

    def test_series_vol_title_left_untouched(self):
        # Patron W: cuando el titulo ENTERO es "Serie, Volume N", el titulo
        # ya NO se recorta a solo la serie -- se queda tal cual.
        clean, series, index, subtitle, _sg = _round3_pipeline(
            'Grantville Gazette, Volume 91', author='Bjorn Hasseler')
        self.assertEqual(clean, 'Grantville Gazette, Volume 91')
        self.assertEqual(series, 'Grantville Gazette')
        self.assertEqual(index, 91.0)

    def test_series_vol_title_left_untouched_no_comma(self):
        clean, series, index, subtitle, _sg = _round3_pipeline(
            'Grantville Gazette Volume 93', author='Bjorn Hasseler')
        self.assertEqual(clean, 'Grantville Gazette Volume 93')
        self.assertEqual(series, 'Grantville Gazette')
        self.assertEqual(index, 93.0)

    def test_colon_series_colon_book_no_subtitle(self):
        # "Titulo: Serie: Book N" -- el "Book N" final es el indice de la
        # serie, NO un subtitulo (nota explicita de Yolanda en el Excel).
        clean, series, index, subtitle, _sg = _round3_pipeline(
            'Alice Non-Biological: The Girls on the Hill: Book 2',
            author='Marilyn Foxworthy')
        self.assertEqual(clean, 'Alice Non-Biological')
        self.assertEqual(series, 'Girls on the Hill')
        self.assertEqual(index, 2.0)
        self.assertIsNone(subtitle)

    def test_colon_series_colon_book_no_subtitle_2(self):
        clean, series, index, subtitle, _sg = _round3_pipeline(
            'The Only Constant: Samair in Argos: Book 7',
            author='Michael Kotcher')
        self.assertEqual(clean, 'The Only Constant')
        self.assertEqual(series, 'Samair in Argos')
        self.assertEqual(index, 7.0)
        self.assertIsNone(subtitle)

    def test_genre_blurb_series_accepted_with_explicit_book_keyword(self):
        # Patron K: "(A Tom Wagner Adventure Book 4)" tiene forma de blurb
        # de genero (empieza por "A" + palabra "Adventure"), pero el "Book 4"
        # explicito es prueba suficiente de que es una serie real.
        clean, series, index, subtitle, _sg = _round3_pipeline(
            'The Golden Path (A Tom Wagner Adventure Book 4)',
            author='M. C. Roberts')
        self.assertEqual(clean, 'The Golden Path')
        self.assertEqual(series, 'A Tom Wagner Adventure')
        self.assertEqual(index, 4.0)
        self.assertIsNone(subtitle)

    def test_genre_blurb_without_book_keyword_still_rejected(self):
        # Sin "Book N" explicito, la forma de blurb SI debe seguir
        # rechazandose como nombre de serie (no se ha debilitado la regla
        # general, solo se ha anadido una excepcion puntual).
        self.assertFalse(ft._is_valid_series('A Tom Wagner Adventure'))
        self.assertTrue(
            ft._is_valid_series('A Tom Wagner Adventure', allow_genre_blurb=True))


if __name__ == '__main__':
    unittest.main(verbosity=2)
