import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from integrations import Enrichment, IntegrationError, ProviderUnavailable, MAX_JSON

TRACK = {'title': 'A Song', 'artist': 'The Artist', 'album': 'Album', 'duration_seconds': 180.0}
UUID = '12345678-1234-1234-1234-123456789abc'


class Response:
    def __init__(self, data=None, status=200, headers=None, raw=None):
        self.status_code = status; self.headers = headers or {}
        self.raw = raw if raw is not None else json.dumps(data).encode()
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def iter_content(self, size):
        for start in range(0, len(self.raw), size): yield self.raw[start:start + size]


class FakeSession:
    def __init__(self, response): self.response = response; self.calls = []; self.trust_env = True
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def get(self, url, **kwargs): self.calls.append((url, kwargs)); return self.response


class Integrations(unittest.TestCase):
    def setUp(self):
        runtime = Path(__file__).resolve().parent / '.runtime'
        runtime.mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=runtime)
        self.service = Enrichment(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()

    def test_defaults_private_persistence_and_isolation(self):
        public = self.service.get_settings('liba')
        states = {p['id']: p for p in public['providers']}
        self.assertTrue(states['lrclib']['enabled']); self.assertTrue(states['musicbrainz']['enabled'])
        self.assertFalse(states['lastfm']['enabled']); self.assertFalse(states['duckduckgo']['enabled'])
        secret = 'a' * 32
        public = self.service.save_settings('liba', {'providers': {'lastfm': {'enabled': True, 'api_key': secret}}})
        self.assertNotIn(secret, json.dumps(public))
        lastfm = next(p for p in public['providers'] if p['id'] == 'lastfm')
        self.assertTrue(lastfm['configured'])
        self.assertFalse(next(p for p in self.service.get_settings('libb')['providers'] if p['id'] == 'lastfm')['configured'])
        self.service.save_settings('liba', {'providers': {'lastfm': {'enabled': False}}})
        self.assertEqual(self.service._load('liba')['lastfm']['api_key'], secret)
        fresh = Enrichment(self.tmp.name)
        self.assertEqual(fresh._load('liba')['lastfm']['api_key'], secret)
        if os.name == 'posix': self.assertEqual(stat.S_IMODE((Path(self.tmp.name) / 'integration-settings/liba.json').stat().st_mode), 0o600)
        fresh.save_settings('liba', {'providers': {'lastfm': {'api_key': ''}}})
        self.assertFalse(fresh._load('liba')['lastfm']['api_key'])

    def test_settings_validation_is_atomic_and_no_url_fields(self):
        for library in ('../escape', '/etc/passwd', 'x/y', 'x\\y', '.', 'CON'):
            with self.assertRaises(IntegrationError): self.service.get_settings(library)
        for payload in ({'providers': {'evil': {'enabled': True}}}, {'providers': {'lrclib': {'url': 'http://127.0.0.1'}}}, {'providers': {'lastfm': {'enabled': 'yes'}}}, {'providers': {'lastfm': {'api_key': 'SECRET BAD'}}}):
            with self.assertRaises(IntegrationError): self.service.save_settings('liba', payload)
        self.assertFalse((Path(self.tmp.name) / 'integration-settings/liba.json').exists())
        with self.assertRaises(IntegrationError): self.service.save_settings('liba', {'providers': {'lrclib': {'enabled': False}, 'lastfm': {'api_key': 'bad'}}})
        self.assertTrue(self.service._load('liba')['lrclib']['enabled'])

    def test_symlink_settings_denied(self):
        outside = Path(self.tmp.name) / 'outside.json'; outside.write_text('{}')
        link = Path(self.tmp.name) / 'integration-settings/liba.json'
        try: link.symlink_to(outside)
        except OSError: self.skipTest('Platform does not permit symlinks')
        with self.assertRaises(IntegrationError): self.service.get_settings('liba')

    def lyric_row(self, **changes):
        return {'trackName': 'A Song', 'artistName': 'The Artist', 'duration': 180, 'plainLyrics': 'sample text', 'syncedLyrics': '[00:01.00]sample text', **changes}

    def test_lyrics_identity_and_duration_must_match(self):
        with patch.object(self.service, '_request', return_value=self.lyric_row()):
            self.assertEqual(self.service._lyrics(TRACK, {})[2], 'synced')
        for changes in ({'trackName': 'Different'}, {'artistName': 'Someone Else'}, {'duration': 190}, {'duration': None}):
            with patch.object(self.service, '_request', return_value=self.lyric_row(**changes)):
                self.assertEqual(self.service._lyrics(TRACK, {}), ('', '', 'unverified'))
        with patch.object(self.service, '_request') as call:
            self.assertEqual(self.service._lyrics({**TRACK, 'duration_seconds': None}, {}), ('', '', 'unverified'))
            call.assert_not_called()

    def test_lyrics_missing_instrumental_bounds(self):
        for row, expected in ((None, 'missing'), (self.lyric_row(instrumental=True), 'instrumental'), (self.lyric_row(plainLyrics='x' * 160001, syncedLyrics='not LRC'), 'missing')):
            with patch.object(self.service, '_request', return_value=row):
                self.assertEqual(self.service._lyrics(TRACK, {})[2], expected)

    def test_musicbrainz_verified_recording_genres(self):
        recording = {'id': UUID, 'title': 'A Song', 'length': 180100, 'artist-credit': [{'artist': {'name': 'The Artist'}}]}
        with patch.object(self.service, '_request', side_effect=[{'recordings': [recording]}, {'genres': [{'name': 'rock'}]}]) as call:
            self.assertEqual(self.service._musicbrainz(TRACK), (['rock'], 'recording'))
            self.assertEqual(call.call_args.args[:2], ('musicbrainz', '/ws/2/recording/' + UUID))
        # A different artist's recording must not be used, even if the title matches.
        recording['artist-credit'][0]['artist']['name'] = 'Someone Else'
        with patch.object(self.service, '_request', side_effect=[{'recordings': [recording]}, {'artists': []}]):
            self.assertEqual(self.service._musicbrainz(TRACK), ([], 'missing'))

    def test_musicbrainz_ambiguous_artist_not_guessed(self):
        rows = [{'id': UUID, 'name': 'The Artist'}, {'id': 'aaaaaaaa-1234-1234-1234-123456789abc', 'name': 'The Artist'}]
        with patch.object(self.service, '_request', side_effect=[{'recordings': []}, {'artists': rows}]) as call:
            self.assertEqual(self.service._musicbrainz(TRACK), ([], 'missing'))
            self.assertEqual(call.call_count, 2)

    def test_lastfm_identity_and_noise_filter(self):
        result = {'toptags': {'@attr': {'artist': 'The Artist', 'track': 'A Song'}, 'tag': [{'name': 'rock'}, {'name': 'seen live'}, {'name': '1980s'}, {'name': 'The Artist'}]}}
        with patch.object(self.service, '_request', return_value=result):
            self.assertEqual(self.service._lastfm(TRACK, {'api_key': 'b'*32}), ['rock'])
            result['toptags']['@attr']['artist'] = 'Other'
            self.assertEqual(self.service._lastfm(TRACK, {'api_key': 'b'*32}), [])

    def test_duckduckgo_exact_structured_and_attributed(self):
        row = {'Heading': 'The Artist', 'AbstractURL': 'https://en.wikipedia.org/wiki/The_Artist', 'AbstractSource': 'Wikipedia', 'Infobox': {'content': [{'label': 'Genres', 'value': 'rock, pop'}]}}
        with patch.object(self.service, '_request', return_value=row):
            values, credits = self.service._duckduckgo(TRACK)
            self.assertEqual(values, ['rock', 'pop']); self.assertEqual(len(credits), 2)
            row['AbstractURL'] = 'http://127.0.0.1/private'
            self.assertEqual(self.service._duckduckgo(TRACK), ([], []))

    def test_provider_failures_never_fail_audio_or_leak_secret(self):
        self.service.save_settings('liba', {'providers': {'lastfm': {'enabled': True, 'api_key': 'c'*32}}})
        with patch.object(self.service, '_request', side_effect=RuntimeError('SECRET_TOKEN_IN_PROVIDER_URL')):
            result = self.service.enrich('liba', TRACK)
        self.assertTrue(result['warnings']); self.assertEqual(result['lyrics'], ''); self.assertEqual(result['genres'], [])
        self.assertNotIn('SECRET', json.dumps(result)); self.assertNotIn('c'*32, json.dumps(result))
        self.assertEqual(self.service.enrich('liba', {'artist': None})['metadata_status']['lyrics'], 'unverified')

    def test_http_fixed_hosts_no_redirect_bounds_and_cache(self):
        session = FakeSession(Response({'test': 'ok'}))
        with patch('integrations.requests.Session', return_value=session):
            self.assertEqual(self.service._request('lrclib', '/api/get', {'track_name': 'x'}), {'test': 'ok'})
            self.service._request('lrclib', '/api/get', {'track_name': 'x'})
        self.assertEqual(len(session.calls), 1); self.assertFalse(session.trust_env)
        url, kwargs = session.calls[0]
        self.assertEqual(url, 'https://lrclib.net/api/get'); self.assertFalse(kwargs['allow_redirects']); self.assertEqual(kwargs['timeout'], (3, 7))
        with self.assertRaises(ProviderUnavailable): self.service._request('lrclib', 'https://127.0.0.1', {})
        for response in (Response(status=302, headers={'Location': 'http://127.0.0.1'}), Response(raw=b'x' * (MAX_JSON + 1))):
            with patch('integrations.requests.Session', return_value=FakeSession(response)), patch('integrations.time.sleep'):
                with self.assertRaises(ProviderUnavailable): self.service._request('lrclib', '/api/get', {})

    def test_rate_limit_and_retry_after_cooldown(self):
        session = FakeSession(Response(status=429, headers={'Retry-After': '120'}))
        with patch('integrations.requests.Session', return_value=session):
            with self.assertRaises(ProviderUnavailable): self.service._request('lrclib', '/api/get', {})
            with self.assertRaises(ProviderUnavailable): self.service._request('lrclib', '/api/get', {})
        self.assertEqual(len(session.calls), 1)
        self.service.last_call['musicbrainz'] = 100
        with patch('integrations.time.monotonic', return_value=100), patch('integrations.time.sleep') as pause, patch('integrations.requests.Session', return_value=FakeSession(Response({}))):
            self.service._request('musicbrainz', '/ws/2/artist/', {})
        self.assertAlmostEqual(pause.call_args.args[0], 1.1)


if __name__ == '__main__': unittest.main()
