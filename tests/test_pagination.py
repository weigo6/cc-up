import unittest
from urllib.parse import parse_qs, urlsplit
from cc_up.pagination import Pages


class PaginationTest(unittest.TestCase):
    def test_history_can_move_forward_back_and_forward_with_encoded_cursors(self):
        pages = Pages()
        pages.accept(0, {'next_cursor': 'a+/='})
        path = pages.path('/v1/history', 1)
        self.assertEqual(parse_qs(urlsplit(path).query)['cursor'], ['a+/='])
        # A failed request does not change the displayed page or cursor.
        self.assertEqual(pages.index, 0)
        pages.accept(1, {'next_cursor': 'b'})
        self.assertEqual(pages.path('/v1/history', 0), '/v1/history')
        pages.accept(0, {'next_cursor':'a+/='})
        self.assertEqual(pages.path('/v1/history', 1), path)
        pages.accept(1, {'next_cursor':None})
        self.assertEqual(pages.index, 1)
        with self.assertRaisesRegex(ValueError, '最后一页'):
            pages.path('/v1/history', 2)

    def test_first_page_with_less_than_fifty_rows_has_no_next_page(self):
        pages = Pages()
        pages.accept(0, {'records':[{}]*30,'next_cursor':None})
        self.assertIsNone(pages.next_cursor)
        with self.assertRaises(ValueError):
            pages.path('/v1/history', 1)
