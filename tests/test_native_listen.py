"""Native streaming sends the first audio block before the origin finishes and can seek."""
import asyncio
from contextlib import nullcontext
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException
from starlette.requests import Request
from core import UserError
from listening import native_info, native_response, native_ticket, NativeAudio, NoNativeAudio


class Origin:
    """A deterministic byte-range origin with no external music or credentials."""
    def __init__(self, content, delay=0):
        self.content = content
        self.delay = delay
        self.calls = []
        self.read = 0
        self.closed = False
        self.trust_env = True
        self.status_override = None

    def get(self, url, *, headers, stream, allow_redirects, timeout):
        self.calls.append((url, headers, allow_redirects))
        start, end = (int(n) for n in headers['Range'][6:].split('-'))
        content = self.content[start:end+1]

        def blocks(size):
            for offset in range(0, len(content), size):
                if self.delay:
                    time.sleep(self.delay)
                piece = content[offset:offset+size]
                self.read += len(piece)
                yield piece
        return SimpleNamespace(status_code=self.status_override or 206, close=lambda: None, iter_content=blocks,
                               headers={'Content-Length': str(len(content)),
                                        'Content-Range': f'bytes {start}-{end}/{len(self.content)}'})

    def close(self):
        self.closed = True


def request(method='GET', **headers):
    return Request({'type': 'http', 'method': method, 'asgi': {'version': '3.0', 'spec_version': '2.4'},
                    'headers': [(k.replace('_','-').lower().encode(), v.encode()) for k,v in headers.items()]})


async def receive_audio(response, req, first=None):
    parts = []
    async def send(message):
        if message['type'] == 'http.response.body' and message.get('body'):
            if not parts and first:
                first()
            parts.append(message['body'])
    async def receive():
        await asyncio.Event().wait()
    await response(req.scope, receive, send)
    return b''.join(parts)


def ticket(payload):
    return NativeAudio('https://r1.googlevideo.com/videoplayback?private-signed=test',
                       len(payload), 10, 'FixturePlayer', time.time()+180)


class NativeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.content = bytes(range(256)) * 2000
        self.ticket = ticket(self.content)

    async def test_first_block_is_delivered_while_origin_still_streams_and_client_can_seek(self):
        origin = Origin(self.content)
        with patch('listening.requests.Session', return_value=origin):
            req = request()
            response = native_response(self.ticket, 'fixture_001', req)
            first = []
            result = await receive_audio(response, req, lambda: first.append(origin.read))
            self.assertEqual(result, self.content)
            self.assertLess(first[0],len(result))
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.media_type,'audio/mp4')
            self.assertTrue(origin.closed)
            self.assertFalse(origin.trust_env)
            self.assertFalse(origin.calls[0][2])
            self.assertNotIn('Cookie',origin.calls[0][1])
            for rng, start, end in [('bytes=100-199',100,199),('bytes=-32',len(result)-32,len(result)-1)]:
                req=request(range=rng)
                selected=native_response(self.ticket,'fixture_001',req)
                self.assertEqual(selected.status_code,206)
                self.assertEqual(selected.headers['Content-Range'],f'bytes {start}-{end}/{len(result)}')
                self.assertEqual(await receive_audio(selected,req), self.content[start:end+1])
            calls=len(origin.calls)
            head=native_response(self.ticket,'fixture_001',request('HEAD'))
            self.assertEqual(int(head.headers['Content-Length']),len(result))
            self.assertEqual(len(origin.calls),calls)
            with self.assertRaises(HTTPException) as invalid:
                native_response(self.ticket,'fixture_001',request(range='bytes=99999999-'))
            self.assertEqual(invalid.exception.status_code,416)

    async def test_redirect_is_not_followed_and_resources_close_even_if_browser_disconnects(self):
        origin=Origin(self.content)
        origin.status_override=302
        with patch('listening.requests.Session',return_value=origin):
            with self.assertRaises(NoNativeAudio):
                native_response(self.ticket,'fixture_001',request())
            self.assertTrue(origin.closed)
            self.assertFalse(origin.calls[-1][2])
        disconnected=Origin(self.content)
        req=request()
        async def send(_):
            raise OSError('Browser closed')
        async def receive():
            await asyncio.Event().wait()
        with patch('listening.requests.Session',return_value=disconnected):
            response=native_response(self.ticket,'fixture_001',req)
            from starlette.requests import ClientDisconnect
            with self.assertRaises((ClientDisconnect,OSError)):
                await response(req.scope,receive,send)
        self.assertTrue(disconnected.closed)

    def test_signer_handles_only_fixed_google_media_origin_and_library_cache_is_scoped(self):
        revision=['original']
        def store():
            return SimpleNamespace(lock=threading.Lock(), extractor=None,
                        sources=SimpleNamespace(vault=SimpleNamespace(youtube_file=lambda:nullcontext(None)),
                                   option=lambda _:revision[0], index=SimpleNamespace(active=lambda:['youtube'])))
        first,second=store(),store()
        with patch('listening.prepare_track'),patch('listening.subprocess.run') as run:
            def output(url):
                run.return_value=SimpleNamespace(returncode=0,stdout=(url+'\n1234\n15.1\nFixture Agent\n').encode())
            for bad in ('https://r1.googlevideo.com.example.org/videoplayback','http://r1.googlevideo.com/videoplayback',
                        'https://name@r1.googlevideo.com/videoplayback','https://r1.googlevideo.com/redirect'):
                output(bad)
                with self.subTest(bad=bad),self.assertRaises(NoNativeAudio):
                    native_info(first,'fixture_001')
            output(self.ticket.url)
            initial=native_ticket(first,'fixture_001')
            count=run.call_count
            self.assertEqual(native_ticket(first,'fixture_001'),initial)
            self.assertEqual(run.call_count,count)
            native_ticket(second,'fixture_001')
            revision[0]='changed';native_ticket(first,'fixture_001')
            self.assertEqual(run.call_count,count+2)

    def test_timeout_waiting_for_another_listener_returns_a_retry_message(self):
        flight=Mock()
        flight.result.side_effect=TimeoutError()
        store=SimpleNamespace(lock=threading.Lock(),sources=SimpleNamespace(option=lambda _:None,
                            index=SimpleNamespace(active=lambda:['youtube'])),native_info_cache={},
                            native_info_pending={('fixture_001',None):flight})
        with patch('listening.native_info') as resolve, self.assertRaisesRegex(UserError,'tardando'):
            native_ticket(store,'fixture_001')
        resolve.assert_not_called()

    def test_rate_limit_at_the_media_origin_does_not_repeat_a_download(self):
        origin=Origin(self.content);origin.status_override=429
        with patch('listening.requests.Session',return_value=origin),self.assertRaisesRegex(UserError,'429'):
            native_response(self.ticket,'fixture_001',request())
        self.assertTrue(origin.closed)
        self.assertEqual(len(origin.calls),1)
