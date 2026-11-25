"""Regression checks for browsers that seek audio with byte-range requests."""
import shutil
import subprocess
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
import httpx

from core import Catalog, Store, UserError, classify_error
from listening import install_listening, listen


TRACK = {'id': 'fixture_001', 'type': 'song', 'title': 'Prueba', 'artist': 'Artista', 'duration_seconds': 6}


class TransportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.store = Store(root/'data', root/'music', Catalog(root/'global'))
        self.store.catalog.remember([TRACK])
        app = FastAPI()

        def access(request, library):
            if library != 'mine':
                raise HTTPException(403, 'Biblioteca privada')
            return None, {'id': 'mine'}

        install_listening(app, access, {'mine': self.store})
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://localhost:8511',follow_redirects=True)
        self.addAsyncCleanup(self.client.aclose)
        self.base = '/api/listen/'+TRACK['id']
        self.params = {'library': 'mine'}

    @staticmethod
    def audio(folder, *_):
        subprocess.run(['ffmpeg','-nostdin','-loglevel','error','-f','lavfi','-i',
                        'sine=frequency=440:duration=6',str(folder/'audio.mp3')], check=True)

    @unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg needed')
    async def test_duration_ranges_stable_validator_and_library_scope(self):
        with patch.object(self.store,'download_youtube',side_effect=self.audio) as build:
            details = await self.client.post(self.base+'/prepare', params=self.params)
            self.assertEqual(details.status_code, 200, details.text)
            body = details.json()
            self.assertAlmostEqual(body['duration'],6,delta=.2)
            first = await self.client.get(self.base, params=self.params, headers={'range': 'bytes=0-99'})
            later = await self.client.get(body['url'], headers={'range': 'bytes=1400-1499'})
            self.assertEqual((first.status_code, later.status_code), (206,206))
            self.assertEqual(len(later.content),100)
            length = await self.client.head(body['url'])
            total = int(length.headers['content-length'])
            self.assertEqual(later.headers['content-range'],f'bytes 1400-1499/{total}')
            self.assertEqual(first.headers['etag'],length.headers['etag'])
            invalid = await self.client.get(body['url'], headers={'range': f'bytes={total+1}-'})
            self.assertEqual(invalid.status_code,416)
            with self.store.db() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM files').fetchone()[0],0)
            foreign = await self.client.get(body['url'].replace('library=mine','library=other'))
            self.assertEqual(foreign.status_code,403)
            self.assertEqual(build.call_count,1)

    @unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg needed')
    def test_two_requests_share_one_complete_preparation(self):
        started = threading.Event()
        resume = threading.Event()

        def wait_and_build(folder, *_):
            started.set()
            self.assertTrue(resume.wait(5))
            self.audio(folder)

        with patch.object(self.store,'download_youtube',side_effect=wait_and_build) as build, ThreadPoolExecutor(2) as pool:
            first = pool.submit(listen, self.store, TRACK['id'])
            self.assertTrue(started.wait(5))
            second = pool.submit(listen, self.store, TRACK['id'])
            resume.set()
            self.assertEqual(first.result(timeout=8),second.result(timeout=8))
            self.assertEqual(build.call_count,1)

    async def test_google_quota_instead_of_login_hint_and_retry_clears_error(self):
        error = UserError(classify_error('ERROR: HTTP Error 429: Too Many Requests; sign in'))
        with patch.object(self.store,'download_youtube',side_effect=error):
            response = await self.client.get(self.base,params=self.params)
            self.assertEqual(response.status_code,429)
            status = (await self.client.get(self.base+'/status',params=self.params)).json()
            self.assertIn('Esperá',status['error'])
            self.assertNotIn('cookies',status['error'])
        if shutil.which('ffmpeg'):
            with patch.object(self.store,'download_youtube',side_effect=self.audio):
                recovered = await self.client.head(self.base,params=self.params)
                self.assertEqual(recovered.status_code,200)
                self.assertEqual((await self.client.get(self.base+'/status',params=self.params)).json()['error'],'')
