"""Regression checks for library-private sources and the format actually written to disk."""
from contextlib import contextmanager
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from requests import Response
from mutagen.flac import FLAC
from core import Catalog, Store, UserError
from music_home import import_home, live_home
from source_sessions import cookie_rows
from qobuz_store import offers

SONG = {'id': 'fixture_A01', 'title': 'Horizonte', 'artist': 'Artista de prueba', 'album': 'Amanecer',
        'type': 'song', 'track': 1, 'cover': '', 'duration': '0:01'}
QID = 'qb:171'
ART = 'https://lh3.googleusercontent.com/example=w544-h544'
MANIFEST = [{'metadata': {'albums': [{'id': 8, 'title': 'Amanecer', 'image': {'large':'https://static.qobuz.com/images/example.jpg'}, 'artists': [{'name': SONG['artist']}]}],
                          'tracks': [{'id': 171, 'title': SONG['title'], 'album': {'id': 8}, 'duration': 1}]},
             'audios': [{'track_id': 171, 'mime_type': 'audio/flac', 'url': 'https://download.qobuz.com/fixture',
                         'bit_depth': 24, 'sampling_rate': 48}]}]
SAMPLE = 'example-only-ephemeral'
COOKIES = '.youtube.com\tTRUE\t/\tTRUE\t0\t__Secure-3PAPISID\t'+SAMPLE


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = Store(root/'data', root/'music', Catalog(root/'cache'))
        self.s = self.store.sources
        self.store.catalog.remember([SONG])

    def index(self):
        with patch('qobuz_store.small_response', return_value=(json.dumps(MANIFEST).encode(), 'https://qobuz.com/')):
            self.assertEqual(self.s.refresh('qbzdl://example-test')['indexed'], 1)

    def test_detects_highest_native_flac_and_freezes_plan(self):
        self.assertTrue(self.s.settings()['best'])
        self.assertEqual(self.s.describe([SONG])[0]['output_format'], 'mp3')
        self.index()
        self.assertEqual(self.s.describe([SONG])[0]['output_format'], 'flac')
        extra = {**SONG, 'id': 'fixture_B02', 'title': 'Otra canción'}
        self.store.enqueue([SONG, extra], 'auto')
        self.s.set_option('best_quality', False)
        self.assertEqual(self.store.jobs()['items'][0]['formats'], ['flac', 'mp3'])
        self.assertEqual(self.s.plan([SONG], 'auto')[0]['output_format'], 'mp3')
        self.assertEqual(self.s.plan(self.s.selected([QID]), 'original')[0]['output_format'], 'flac')
        self.assertFalse(self.s.describe([{**SONG, 'album':'En vivo'}])[0]['has_flac'])
        with self.assertRaises(UserError):
            self.s.plan([extra], 'flac')

    def test_mp3_only_qobuz_edition_and_album(self):
        manifest = json.loads(json.dumps(MANIFEST))
        manifest[0]['audios'][0]['mime_type'] = 'audio/mpeg'
        with patch('qobuz_store.small_response', return_value=(json.dumps(manifest).encode(), '')):
            self.s.refresh('qbzdl://example-mp3')
        track = self.s.purchases.get(QID)
        self.assertEqual(track['native_format'], 'MP3')
        annotated = self.s.describe([track])[0]
        self.assertFalse(annotated['has_flac'])
        self.assertIsNone(annotated['flac_id'])
        self.assertEqual(self.s.plan([track], 'auto')[0]['output_format'], 'mp3')
        with self.assertRaises(UserError):
            self.s.plan([track], 'flac')
        self.assertEqual(self.s.purchases.album_preview(catalog_id='8')['tracks'][0]['id'], QID)

    def test_each_source_imports_its_own_page(self):
        self.s.index.import_html('youtube', '<a href="/watch?v=fixture_A01">Una canción</a>')
        html = '<a href="/us-en/album/revista/a04?campaign=test">Otro álbum</a>'
        html += '<a href="https://example.org/track/123">Otra fuente</a>'
        self.assertEqual(self.s.index.import_html('qobuz', html), {'imported': 1})
        tiles=self.s.index.rows()
        # Albums stay accessible via search. The Home listening shelf contains tracks.
        self.assertEqual(self.s.option('home_html')[0]['id'],SONG['id'])
        album = next(t for t in tiles if t['source']=='qobuz')
        self.assertEqual(album['type'], 'album')
        self.assertTrue(album['reference'])
        self.assertNotIn('campaign', album['url'])
        self.assertNotIn('output_format', album)
        self.assertNotIn('Otra fuente', str(tiles))

    def test_download_history_suggests_new_tracks_and_albums(self):
        with self.store.db() as db:
            db.execute('INSERT INTO files VALUES(?,?,?,?,?)', (SONG['id'], 'mp3', 'prueba.mp3', json.dumps(SONG), 'example'))
        artist = [{'name':SONG['artist']}]
        def artist_results(name, filter, limit):
            self.assertEqual(name, SONG['artist'])
            if filter == 'songs':
                return [{'videoId': SONG['id'], 'title': SONG['title'], 'artists': artist},
                        {'videoId':'fixture_B02','title':'Otra rola','artists':artist}]
            return [{'browseId':'MPREb123456','resultType':'album','title':'Otro disco','artists':artist}]
        with patch.object(self.store.catalog,'suggest_factory') as factory:
            factory.return_value.search.side_effect = artist_results
            tiles = self.s.related(False)
            self.assertEqual({t['title'] for t in tiles}, {'Otra rola','Otro disco'})
            self.assertEqual({t['type'] for t in tiles}, {'song','album'})
            self.assertEqual(self.s.related(False), tiles)
            self.assertEqual(factory.return_value.search.call_count, 2)

    def test_format_filter_applies_to_home_preview_and_queue(self):
        self.index()
        mp3 = json.loads(json.dumps(MANIFEST))
        mp3[0]['metadata']['tracks'][0].update(id=172,title='Solo MP3')
        mp3[0]['audios'][0].update(track_id=172,mime_type='audio/mpeg')
        with patch('qobuz_store.small_response',return_value=(json.dumps(mp3).encode(),'')):
            self.s.refresh('qbzdl://mp3-example')
        self.s.configure('qobuz','format',False,'mp3')
        home=[t for shelf in self.s.home()['sections'] for t in shelf['items']]
        self.assertEqual([(t['id'],t['output_format']) for t in home],[(QID,'flac')])
        tracks=self.s.purchases.album_preview(catalog_id='8')['tracks']
        self.assertEqual([t['id'] for t in self.s.describe(tracks)],[QID])
        with self.assertRaises(UserError):
            self.s.plan(self.s.selected(['qb:172']),'auto')
        self.s.configure('qobuz','home',False)
        self.assertEqual(self.s.home()['sections'],[])
        self.assertEqual(self.s.plan(self.s.selected([QID]),'auto')[0]['output_format'],'flac')

    def test_removal_and_readding_have_clean_default_preferences(self):
        self.index()
        self.s.configure('qobuz','favorite',True)
        self.s.remove('qobuz')
        self.assertNotIn('qobuz',self.s.index.active())
        self.assertIn('qobuz',[x['id'] for x in self.s.settings()['available']])
        self.assertEqual(self.s.purchases.search('Horizonte'),[])
        self.s.index.add('qobuz')
        new=next(s for s in self.s.settings()['sources'] if s['id']=='qobuz')
        self.assertTrue(new['home'])
        self.assertFalse(new['favorite'])
        self.assertEqual(set(new['enabled_formats']),{'mp3','flac'})
        with self.assertRaises(UserError):
            self.s.configure('youtube','format',False,'mp3')

    def test_custom_source_learns_only_after_a_verified_download(self):
        key=self.s.index.add('audio.example.org')
        current=lambda:next(s for s in self.s.settings()['sources'] if s['id']==key)
        self.assertEqual(current()['formats'],[])
        with self.store.db() as db:
            self.s.index.learn(db,key,'mp3')
        self.assertEqual(current()['formats'],['mp3'])
        with self.store.db() as db:
            self.s.index.learn(db,key,'wav')
        self.assertEqual(set(current()['formats']),{'mp3','flac','wav'})
        self.s.configure(key,'format',False,'mp3')
        self.s.configure(key,'format',False,'flac')
        track={**SONG,'source':key,'id':'ex:'+'1'*32,'native_format':'WAV'}
        self.assertEqual(self.s.plan([track],'auto')[0]['output_format'],'wav')
        self.assertEqual(self.s.describe([{**track,'native_format':'mp3'}]),[])

    def test_later_lower_quality_purchase_keeps_available_master(self):
        self.index()
        lower = [{**MANIFEST[0], 'audios': [{**MANIFEST[0]['audios'][0], 'bit_depth':16, 'sampling_rate':44.1}]}]
        with patch('qobuz_store.small_response', return_value=(json.dumps(lower).encode(), '')):
            self.s.refresh('qbzdl://different-test')
        self.assertEqual(self.s.purchases.get(QID)['bit_depth'], 24)
        self.assertEqual(self.s.purchases.get(QID)['sample_rate'], 48000)

    def test_html_import_extracts_music_links_only(self):
        html='<a href="/watch?v=fixture_A01">La primera</a><a href="/watch?v=fixture_A01">Duplicada</a>'
        html+='<a href="https://example.org/watch?v=fixture_B02">Ajena</a><script>un valor privado</script>'
        self.assertEqual(self.s.html(html), {'imported': 1})
        self.assertEqual(self.s.option('home_html')[0]['title'],'La primera')
        with patch('home_recordings.threading.Thread.start'):
            home=self.s.home()
        self.assertTrue(home['checking'])
        self.assertEqual(home['sections'],[])
        self.assertNotIn('privado', json.dumps(home))
        self.assertNotIn('Ajena', json.dumps(home))
        with self.assertRaises(UserError):
            import_home('<html>sin música</html>')

    def test_import_rendered_tile_keeps_artist_and_proxies_public_art(self):
        html = ('<ytmusic-two-row-item-renderer><img src="https://i.ytimg.com/vi/fixture_A01/hqdefault.jpg?discard=1">'
                '<a href="/watch?v=fixture_A01">La pista</a><a href="/channel/UCRr1xG_2WIDs18a6cIiCxeA">Artista invitado</a>'
                '</ytmusic-two-row-item-renderer>')
        self.s.html(html)
        self.store.catalog.cover_sources.clear()
        self.assertEqual(self.s.option('home_html')[0]['artist'],'Artista invitado')
        with patch('home_recordings.threading.Thread.start'):
            self.assertEqual(self.s.home()['sections'], [])
        # When the provider confirms the official recording, only its album image is used.
        from time import time
        self.s.set_option('official_home_cache',{SONG['id']:{'until':time()+1000,
            'item':{**SONG,'video_type':'MUSIC_VIDEO_TYPE_ATV','thumbnail':ART,'artist':'Artista invitado'}}})
        tracks = self.s.home()['sections'][0]['items']
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]['artist'], 'Artista invitado')
        self.assertTrue(tracks[0]['cover'].startswith('/api/covers/'))
        self.assertNotIn('thumbnail', tracks[0])
        self.assertNotIn('discard', str(self.store.catalog.cover_sources))

    def test_session_is_scoped_and_revocable(self):
        self.s.change_session('youtube', COOKIES)
        with self.store.db() as db:
            blob = db.execute("SELECT value FROM source_secrets WHERE name='youtube'").fetchone()[0]
            self.assertNotIn(SAMPLE.encode(), blob)
        with self.s.vault.youtube_file() as name:
            self.assertIn(SAMPLE, Path(name).read_text())
        self.assertFalse(Path(name).exists())
        with self.assertRaises(UserError):
            cookie_rows('youtube', COOKIES + '\n.example.org\tTRUE\t/\tTRUE\t0\ttest\texample')
        self.s.change_session('youtube')
        self.assertFalse(self.s.settings()['youtube'])
        self.assertIsNone(self.s.vault.read('youtube'))

    def test_live_home_authenticated_library_client_and_snapshot(self):
        # Use the installed provider client for authentication setup; stub only its network-facing calls.
        self.s.change_session('youtube', COOKIES)
        def account_response(session, method, url, **kwargs):
            self.assertTrue(url == 'https://music.youtube.com' or url.startswith('https://music.youtube.com/'))
            response = Response()
            response.status_code = 200
            if method.upper() == 'GET':
                response._content = b'<html></html>'
            else:
                self.assertIn('/account/account_menu', url)
                headers = {key.lower(): value for key, value in kwargs['headers'].items()}
                self.assertTrue(headers.get('authorization', '').startswith('SAPISIDHASH '))
                account = {'accountName': {'runs': [{'text':'QA'}]}, 'accountPhoto': {'thumbnails':[{'url':'https://example.org/fixture'}]}}
                response._content = json.dumps({'actions':[{'openPopupAction':{'popup':{'multiPageMenuRenderer':{'header':{'activeAccountHeaderRenderer':account}}}}}]}).encode()
            return response
        with patch('music_home.MusicSession.request', new=account_response), \
             patch('music_home.YTMusic.get_home', return_value=[{'contents':[{'title':'Ejemplo','videoId':SONG['id'],'videoType':'MUSIC_VIDEO_TYPE_ATV','thumbnails':[{'url':ART,'width':544,'height':544}]}]}]) as fetch:
            self.assertEqual(self.s.home()['sections'][0]['items'][0]['id'], SONG['id'])
            self.assertEqual(self.s.home()['sections'][0]['items'][0]['title'], 'Ejemplo')
            self.assertEqual(fetch.call_count, 1)
        self.s.change_session('youtube')
        self.assertEqual(self.s.home()['sections'], [])

    def test_autodiscovery_uses_purchase_links_and_strips_media_urls(self):
        self.s.change_session('qobuz', '.qobuz.com\tTRUE\t/\tTRUE\t0\tfixture\texample')
        def page(url, cookies):
            if '/v4/' in url:
                return json.dumps(MANIFEST).encode(), url
            return b'<a href="qbzdl://example-test">Download</a>', url
        with patch('qobuz_store.small_response', side_effect=page):
            self.assertEqual(self.s.refresh()['indexed'], 1)
        public = json.dumps(self.s.purchases.search('horizonte'))
        self.assertNotIn('https://', public)
        self.assertNotIn('example-test', public)
        root = Path(self.tmp.name)
        other = Store(root/'other', root/'other-music', self.store.catalog)
        self.assertEqual(other.sources.purchases.search('Horizonte'), [])
        self.s.change_session('qobuz')
        self.assertEqual(self.s.settings()['purchases'], 0)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg required')
    def test_download_files_and_tags(self):
        self.index()
        path = Path(self.tmp.name)/'fixture.flac'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=duration=1:sample_rate=48000',
                        '-c:a','flac','-sample_fmt','s32',str(path)],check=True)
        class Media:
            headers = {'Content-Length': str(path.stat().st_size)}
            def iter_content(self, size):
                yield path.read_bytes()
        @contextmanager
        def media(*_args, **_kwargs):
            yield Media()
        with patch('qobuz_store.small_response', return_value=(json.dumps(MANIFEST).encode(),'')), \
             patch('qobuz_store.response_for', side_effect=media):
            for mode in ('flac', 'mp3'):
                plan = self.s.plan(self.s.selected([QID]), mode)[0]
                self.store.download('fixturejob',plan,mode,lambda _x: None)
        files = self.store.library()['items']
        self.assertEqual({f['format'] for f in files}, {'mp3','flac'})
        flac = next(f for f in files if f['format']=='flac')
        self.assertEqual(flac['sample_rate'],48000)
        self.assertEqual(flac['bit_depth'],24)
        song=FLAC(self.store.file_path('fixturejob',flac['name']))
        self.assertEqual(song['title'], [SONG['title']])
        self.assertNotIn(':',flac['name'])
        self.assertTrue(self.store.delete_file(QID,'flac')['deleted'])

    def test_wrong_mime_and_invalid_flac_never_publish(self):
        wrong=[{**MANIFEST[0], 'audios':[{**MANIFEST[0]['audios'][0], 'mime_type':'video/mp4'}]}]
        with patch('qobuz_store.small_response',return_value=(json.dumps(wrong).encode(),'')):
            self.assertEqual(offers('fixture', []), {})
        self.index()
        def wrong_file(ident, path, progress):
            path.write_bytes(b'not FLAC'*900)
        with patch.object(self.s.purchases,'download',side_effect=wrong_file), self.assertRaises(UserError):
            self.store.download('fixturejob', self.s.plan([SONG],'flac')[0], 'flac',lambda _x:None)
        self.assertEqual(self.store.library()['total'], 0)
