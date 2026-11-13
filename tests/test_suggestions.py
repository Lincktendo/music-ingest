from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import Catalog, UserError, suggestion_client


class Suggestions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.client = Mock()
        self.client.get_search_suggestions.return_value = ['daft punk']
        self.factory = Mock(return_value=self.client)
        self.catalog = Catalog(Path(self.temp.name), suggest_factory=self.factory)

    def tearDown(self):
        self.temp.cleanup()

    def test_skips_short_queries_urls_and_rejects_oversize(self):
        for query in ('', ' ', 'a', 'https://youtube.com/watch?v=example', 'HTTP://private/', 'www.youtube.com'):
            self.assertEqual(self.catalog.suggestions(query), {'items': []})
        with self.assertRaises(UserError):
            self.catalog.suggestions('x' * 201)
        self.factory.assert_not_called()

    def test_provider_normalization_bound_and_cache_not_mutable(self):
        self.client.get_search_suggestions.return_value = [None, {}, '', 'daft punk', 'DAFT PUNK', '  daft  live ', 'x'*201] + [f'item {i}' for i in range(20)]
        result = self.catalog.suggestions('  daft  ')
        self.assertEqual(len(result['items']), 8)
        self.assertEqual(result['items'][:2], ['daft punk', 'daft live'])
        self.client.get_search_suggestions.assert_called_once_with('daft')
        result['items'].clear()
        self.assertEqual(len(self.catalog.suggestions('DAFT')['items']), 8)
        self.assertEqual(self.factory.call_count, 1)
        self.client._session.close.assert_called_once()

    def test_provider_failure_releases_slot_and_is_not_cached(self):
        self.client.get_search_suggestions.side_effect = TimeoutError('provider')
        with self.assertRaises(TimeoutError):
            self.catalog.suggestions('daft')
        self.client.get_search_suggestions.side_effect = None
        self.assertEqual(self.catalog.suggestions('daft'), {'items': ['daft punk']})
        self.assertEqual(self.factory.call_count, 2)
        self.assertEqual(self.client._session.close.call_count, 2)

    def test_concurrent_queries_do_not_block_worker(self):
        slots = self.catalog.suggestion_slots
        slots.acquire(); slots.acquire()
        try:
            self.assertEqual(self.catalog.suggestions('daft'), {'items': []})
            self.factory.assert_not_called()
        finally:
            slots.release(); slots.release()

    def test_cache_expiry_and_capacity(self):
        self.catalog.suggestions('daft')
        with patch('core.time.monotonic', return_value=10**12):
            self.catalog.suggestions('daft')
            self.assertEqual(self.factory.call_count, 2)
            for i in range(140):
                self.catalog.suggestions(f'query {i}')
        self.assertLessEqual(len(self.catalog.suggestion_cache), 128)

    def test_session_has_short_timeout_and_no_account_auth(self):
        session = Mock()
        with patch('core.requests.Session', return_value=session), patch('core.YTMusic') as constructor:
            suggestion_client()
        session.request('GET', 'https://music.youtube.com')
        session.request.func.assert_called_once_with('GET', 'https://music.youtube.com', timeout=(2, 4))
        constructor.assert_called_once_with(language='es', requests_session=session)


if __name__ == '__main__':
    unittest.main()
