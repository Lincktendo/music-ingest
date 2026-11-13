import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx


class API(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        runtime = Path(__file__).resolve().parent / '.runtime'
        runtime.mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=runtime)
        root = Path(self.tmp.name)
        with patch.dict(os.environ, {'DATA_DIR': str(root / 'data'), 'MUSIC_DIR': str(root / 'music'), 'ALLOWED_HOSTS': 'localhost,127.0.0.1'}):
            spec = importlib.util.spec_from_file_location('test_api_instance', Path(__file__).resolve().parents[1] / 'app.py')
            self.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.module)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.module.app), base_url='http://localhost:8511')

    async def asyncSetUp(self):
        response = await self.client.post('/api/auth/register', json={'username': 'tester', 'password': 'correct-horse-battery'})
        self.assertEqual(response.status_code, 201, response.text)

    async def asyncTearDown(self):
        await self.client.aclose()
        self.tmp.cleanup()

    async def test_host_origin_and_json_guard(self):
        self.assertEqual((await self.client.get('/api/health')).status_code, 200)
        self.assertEqual((await self.client.get('/api/health', headers={'host': 'evil.com'})).status_code, 400)
        self.assertEqual((await self.client.post('/api/jobs', json={}, headers={'origin': 'https://evil.com'})).status_code, 403)
        self.assertEqual((await self.client.post('/api/jobs', json={}, headers={'origin': 'http://localhost:9999'})).status_code, 403)
        self.assertEqual((await self.client.post('/api/jobs', content='{}', headers={'content-type': 'text/plain'})).status_code, 415)
        self.assertEqual((await self.client.post('/api/jobs', content='x' * 70000, headers={'content-type': 'application/json'})).status_code, 413)

    async def test_json_replayed_and_untrusted_metadata_ignored(self):
        ident = 'BaW_jenozKc'
        track = {'id': ident, 'title': 'Verified title', 'artist': 'Verified artist', 'cover': '', 'album': '', 'track': 1}
        self.module.catalog.remember([track])
        result = await self.client.post('/api/jobs', json={'tracks': [{'id': ident, 'title': '../../Bad', 'cover': 'http://127.0.0.1:22'}], 'format': 'mp3'}, headers={'origin': 'http://localhost:8511'})
        self.assertEqual(result.status_code, 201, result.text)
        job = (await self.client.get('/api/jobs')).json()['items'][0]
        self.assertEqual(job['title'], 'Verified title')
        self.assertEqual(job['status'], 'queued')

    async def test_unpreviewed_and_invalid_urls_rejected(self):
        response = await self.client.post('/api/jobs', json={'tracks': [{'id': 'BaW_jenozKc'}]})
        self.assertEqual(response.status_code, 400)
        for url in ('http://127.0.0.1:22', 'https://youtube.com.evil/watch?v=BaW_jenozKc'):
            self.assertEqual((await self.client.post('/api/preview', json={'url': url})).status_code, 400)
        self.assertEqual((await self.client.get('/api/files/job/secret.txt')).status_code, 404)

    async def test_suggestions_api_bounds_and_provider_errors(self):
        with patch.object(self.module.catalog, 'suggestions', return_value={'items': ['daft punk']}) as call:
            response = await self.client.get('/api/suggestions', params={'q': 'daft'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {'items': ['daft punk']})
            call.assert_called_once_with('daft')
            self.assertEqual((await self.client.get('/api/suggestions', params={'q': 'x' * 201})).status_code, 422)
            self.assertEqual(call.call_count, 1)
        with patch.object(self.module.catalog, 'suggestions', side_effect=RuntimeError('PRIVATE_PROVIDER_DETAIL')):
            response = await self.client.get('/api/suggestions', params={'q': 'test'})
            self.assertEqual(response.status_code, 502)
            self.assertNotIn('PRIVATE_PROVIDER_DETAIL', response.text)


if __name__ == '__main__':
    unittest.main()
