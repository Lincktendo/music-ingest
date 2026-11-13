import json
import io
import shutil
import subprocess
from pathlib import Path
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import Catalog, Store, UserError, parse_link, safe_name, tag_file


ID = 'BaW_jenozKc'
TRACK = {'id': ID, 'title': '../Example', 'artist': 'Artist', 'album': 'Album', 'track': 1, 'cover': ''}


class Safety(unittest.TestCase):
    def setUp(self):
        runtime = Path(__file__).resolve().parent / '.runtime'
        runtime.mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=runtime)
        self.root = Path(self.tmp.name)
        self.catalog = Catalog(self.root / 'data')
        self.store = Store(self.root / 'data', self.root / 'music', self.catalog)

    def tearDown(self):
        self.tmp.cleanup()

    def test_allowlist_link(self):
        self.assertEqual(parse_link('https://youtu.be/' + ID), ID)
        self.assertEqual(parse_link('https://music.youtube.com/watch?v=' + ID), ID)
        for link in ['http://youtube.com/watch?v=' + ID, 'https://youtube.com.evil/watch?v=' + ID, 'https://evil@youtube.com/watch?v=' + ID, 'https://youtube.com:8443/watch?v=' + ID, 'file:///etc/passwd', 'https://127.0.0.1/watch?v=' + ID, 'https://youtu.be/../../../x', 'https://youtube.com/playlist?list=123']:
            with self.subTest(link=link), self.assertRaises((UserError, ValueError)):
                parse_link(link)

    def test_filename_and_cover_validation(self):
        self.assertNotIn('/', safe_name('../../test'))
        self.assertNotIn('\\', safe_name('..\\test'))
        self.assertEqual(safe_name('CON'), '_CON')
        for url in ['https://lh3.googleusercontent.com.evil/x', 'https://user@i.ytimg.com/x', 'http://i.ytimg.com/x', 'https://i.ytimg.com:444/x', 'http://127.0.0.1/x']:
            self.assertFalse(self.catalog.valid_cover(url))
        self.assertTrue(self.catalog.valid_cover('https://i.ytimg.com/vi/' + ID + '/default.jpg'))

    @unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg not installed')
    def test_tagless_audio_is_valid_and_can_be_tagged(self):
        from mutagen import File
        for extension, codec in [('m4a', 'aac'), ('opus', 'libopus')]:
            with self.subTest(extension=extension):
                file = self.root / ('tone.' + extension)
                subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1', '-c:a', codec, str(file)], check=True)
                audio = File(file)
                if audio.tags:
                    audio.delete()
                self.assertIsNotNone(File(file))
                tag_file(file, TRACK, None)
                checked = File(file)
                self.assertIsNotNone(checked.info)
                self.assertTrue(checked.tags)

    def test_server_verified_selection(self):
        with self.assertRaises(UserError):
            self.catalog.selected([ID])
        self.catalog.remember([TRACK])
        selected = self.catalog.selected([ID])
        selected[0]['title'] = 'client changed'
        self.assertEqual(self.catalog.selected([ID])[0]['title'], TRACK['title'])
        with self.assertRaises(UserError):
            self.catalog.selected([ID, ID])
        self.catalog.cache[ID] = (time.time() - 7300, TRACK)
        with self.assertRaises(UserError):
            self.catalog.selected([ID])

    def test_queue_bound_and_restart(self):
        for _ in range(10):
            self.store.enqueue([TRACK], 'mp3')
        with self.assertRaises(UserError):
            self.store.enqueue([TRACK], 'mp3')
        second = Store(self.root / 'data', self.root / 'music', self.catalog)
        self.assertEqual({r['status'] for r in second.jobs()['items']}, {'interrupted'})
        self.assertEqual(len(second.jobs()['items']), 10)

    def test_retry_no_duplicate_completed_track(self):
        ident = self.store.enqueue([TRACK], 'mp3')['id']
        filename = 'test.mp3'
        (self.root / 'music' / filename).write_bytes(b'valid test placeholder')
        with self.store.db() as db:
            db.execute('INSERT INTO files VALUES(?,?,?,?,?)', (ID, 'mp3', filename, json.dumps(TRACK), ident))
        self.store.update(ident, status='failed')
        self.store.retry(ident)
        with self.store.db() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (ident,)).fetchone()
        self.store.download = lambda *args: self.fail('Completed track was downloaded again')
        self.store.execute(row)
        self.assertEqual(self.store.jobs()['items'][0]['status'], 'completed')
        with self.assertRaises(UserError):
            self.store.retry(ident)

    def test_unregistered_and_traversal_file_denied(self):
        (self.root / 'music' / 'secret.txt').write_text('not app output')
        for name in ['secret.txt', '../outside', '..\\outside', '/etc/passwd']:
            with self.assertRaises(UserError):
                self.store.file_path('x', name)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg not installed')
    def test_publish_preserves_existing_user_file(self):
        from storage import Folders
        Folders(self.store).create('', 'Mis canciones')
        Folders(self.store).select('Mis canciones')
        original = self.root / 'fixture.mp3'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1', '-c:a', 'libmp3lame', str(original)], check=True)
        content = original.read_bytes()
        name = safe_name(TRACK['artist']) + ' - ' + safe_name(TRACK['title']) + ' [' + ID + '].mp3'
        collision = self.root / 'music' / 'Mis canciones' / name
        collision.write_bytes(b'USER ORIGINAL MUST SURVIVE')
        class FakeProcess:
            def __init__(self, args, **kwargs):
                destination = args[args.index('-o') + 1].replace('%(ext)s', 'mp3')
                Path(destination).write_bytes(content)
                self.stdout = io.StringIO('[download] 100.0%\n')
            def wait(self, timeout=None): return 0
            def poll(self): return 0
        self.store.enricher = lambda track: {'synced_lyrics': '[00:00.00]Test lyric', 'lyrics': 'Test lyric', 'genres': ['Test genre'], 'metadata_status': {'lyrics': 'found'}}
        with patch('core.subprocess.Popen', FakeProcess):
            self.store.download('job', TRACK.copy(), 'mp3', lambda p: None)
        self.assertEqual(collision.read_bytes(), b'USER ORIGINAL MUST SURVIVE')
        output = self.store.library()['items'][0]
        self.assertTrue(output['name'].startswith('Mis canciones/'))
        self.assertNotEqual(output['name'], name)
        self.assertTrue(self.store.file_path('job', output['name']).is_file())
        self.assertTrue(output['lyrics_url'].endswith('.lrc'))
        self.assertIn('Test lyric', self.store.file_path('job', output['lyrics_file']).read_text(encoding='utf8'))
        with self.store.db() as db:
            persisted = json.loads(db.execute('SELECT metadata FROM files').fetchone()[0])
        self.assertNotIn('lyrics', persisted)
        self.assertNotIn('synced_lyrics', persisted)
        self.assertEqual(persisted['metadata_status'], {'lyrics': 'found'})
        from mutagen.id3 import ID3
        self.assertEqual(ID3(self.store.file_path('job', output['name'])).getall('USLT')[0].text, 'Test lyric')
        self.assertEqual(list((self.root / 'data' / 'temp').iterdir()), [])

    def test_job_summaries_bound_lyrics_and_fetch_only_referenced_files(self):
        for _ in range(10):
            self.store.enqueue([TRACK], 'mp3')
        (self.store.music / 'fixture.mp3').write_bytes(b'audiofixture')
        huge_metadata = TRACK | {'lyrics': 'a' * 100000, 'synced_lyrics': 'b' * 100000, 'genres': ['Rock'], 'metadata_status': {'lyrics': 'found'}}
        with self.store.db() as db:
            db.execute('INSERT INTO files VALUES(?,?,?,?,?)', (ID, 'mp3', 'fixture.mp3', json.dumps(huge_metadata), 'fixturejob'))
            db.execute('INSERT INTO files VALUES(?,?,?,?,?)', ('unused00000', 'mp3', 'unrelated.mp3', '{}', 'unrelated'))
        calls, statements = [], []
        original_db, public_file = self.store.db, self.store.public_file
        @contextmanager
        def traced_db():
            with original_db() as db:
                db.set_trace_callback(statements.append)
                yield db
        def observed(row):
            calls.append(row['source_id'])
            return public_file(row)
        with patch.object(self.store, 'db', traced_db), patch.object(self.store, 'public_file', observed):
            result = self.store.jobs()
        self.assertEqual(calls, [ID])
        self.assertTrue(all(' WHERE ' in query.upper() for query in statements if query.upper().startswith('SELECT * FROM FILES')))
        self.assertLess(len(json.dumps(result)), 20000)
        for job in result['items']:
            item = job['files'][0]
            self.assertNotIn('lyrics', item)
            self.assertNotIn('synced_lyrics', item)
            self.assertEqual(item['genres'], ['Rock'])
        self.assertNotIn('synced_lyrics', self.store.library()['items'][0])

    def test_lyrics_reuse_identical_across_formats_and_preserve_different_content(self):
        mp3 = self.store.music / 'same-track.mp3'
        m4a = self.store.music / 'same-track.m4a'
        first = self.store.publish_lyrics(mp3, '[00:00] First lyric')
        second = self.store.publish_lyrics(m4a, '[00:00] First lyric')
        self.assertEqual(first, second)
        different = self.store.publish_lyrics(m4a, '[00:00] Different edition')
        self.assertEqual(different, 'same-track.m4a.lrc')
        self.assertEqual((self.store.music / first).read_text(encoding='utf8'), '[00:00] First lyric\n')
        self.assertEqual((self.store.music / different).read_text(encoding='utf8'), '[00:00] Different edition\n')
        third = self.store.publish_lyrics(m4a, '[00:00] Third edition')
        self.assertNotIn(third, (first, different))
        self.assertEqual((self.store.music / different).read_text(encoding='utf8'), '[00:00] Different edition\n')
        self.assertEqual(list(self.store.music.glob('.lyrics-*.tmp')), [])

    def test_lyrics_never_reuse_nonregular_target(self):
        target = self.store.music / 'song.lrc'
        target.mkdir()
        actual = self.store.publish_lyrics(self.store.music / 'song.opus', '[00:01] Lyrics')
        self.assertEqual(actual, 'song.opus.lrc')
        self.assertTrue(target.is_dir())

    def test_lyrics_never_reuse_symlink_even_with_identical_content(self):
        target = self.root / 'outside.lrc'
        target.write_text('[00:01] Lyrics\n', encoding='utf8')
        link = self.store.music / 'song.lrc'
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest('Symlinks need platform permission')
        actual = self.store.publish_lyrics(self.store.music / 'song.mp3', '[00:01] Lyrics')
        self.assertEqual(actual, 'song.mp3.lrc')
        self.assertEqual(target.read_text(encoding='utf8'), '[00:01] Lyrics\n')

    def test_symlink_file_denied(self):
        target = self.root / 'outside.txt'; target.write_text('secret')
        link = self.root / 'music' / 'linked.mp3'
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest('Symlinks need platform permission')
        with self.store.db() as db:
            db.execute('INSERT INTO files VALUES(?,?,?,?,?)', (ID, 'mp3', link.name, json.dumps(TRACK), 'job'))
        with self.assertRaises(UserError):
            self.store.file_path('job', link.name)


if __name__ == '__main__':
    unittest.main()
