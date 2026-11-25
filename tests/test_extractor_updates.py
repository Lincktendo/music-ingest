import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from extractor_updates import DAY, ExtractorUpdates, UpdateError, validate, version_key


class EngineUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.engine = ExtractorUpdates(self.tmp.name, bundled='2026.10.26')

    def release(self, tag):
        return patch('extractor_updates.fetch', return_value=json.dumps({'tag_name': tag}).encode())

    def sample(self, tag):
        folder = self.engine.root / tag
        folder.mkdir()
        archive = folder / 'yt-dlp'
        archive.write_bytes(b'fixture')
        (folder / 'SHA2-256SUMS').write_text(hashlib.sha256(archive.read_bytes()).hexdigest() + '  yt-dlp\n')
        (folder / 'SHA2-256SUMS.sig').write_bytes(b'fixture')
        return folder

    def test_version_parsing(self):
        self.assertEqual(version_key('2026.01.02'), version_key('2026.1.2'))
        self.assertGreater(version_key('2026.11.23.1'), version_key('2026.11.23'))
        for value in ('2026.13.33', '../release', 'nightly', ''):
            with self.assertRaises(UpdateError):
                version_key(value)

    def test_daily_check_and_restart(self):
        with self.release(self.engine.bundled) as fetch:
            self.engine.check()
            self.assertEqual(self.engine.status()['result'], 'current')
            other = ExtractorUpdates(self.tmp.name, self.engine.bundled)
            other.check()
            self.assertEqual(fetch.call_count, 1)
            with other.db() as db:
                db.execute('UPDATE engine SET checked=?', (time.time() - DAY - 1,))
            other.check()
            self.assertEqual(fetch.call_count, 2)

    def test_unsigned_release_never_executed(self):
        folder = self.sample('2026.11.23')
        with patch('extractor_updates.subprocess.run', return_value=Mock(returncode=1)) as run:
            with self.assertRaises(UpdateError):
                validate(folder, '2026.11.23')
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[0][0], 'gpgv')

    def test_corrupt_payload_never_executed(self):
        folder = self.sample('2026.11.23')
        (folder/'yt-dlp').write_bytes(b'changed')
        with patch('extractor_updates.subprocess.run', return_value=Mock(returncode=0)) as run:
            with self.assertRaises(UpdateError):
                validate(folder, '2026.11.23')
            self.assertEqual(run.call_count, 1)

    def test_activate_verified_release_and_recover_previous_after_restart(self):
        old, new = '2026.11.01', '2026.11.23'
        self.sample(old)
        self.sample(new)
        with self.engine.db() as db:
            db.execute('UPDATE engine SET active=?', (old,))
        with patch('extractor_updates.validate'), self.release(new):
            self.engine.check()
            self.assertEqual(self.engine.status()['version'], new)
            self.assertEqual(self.engine.row()['previous'], old)
            self.assertEqual(self.engine.command(), [sys.executable, '-I', str(self.engine.root/new/'yt-dlp')])
        other = ExtractorUpdates(self.tmp.name, self.engine.bundled)
        def verified(folder, tag):
            if tag == new:
                raise UpdateError()
        with patch('extractor_updates.validate', side_effect=verified):
            self.assertEqual(other.status()['result'], 'fallback')
            self.assertEqual(other.status()['version'], old)

    def test_unavailable_release_preserves_bundled_engine(self):
        with self.release('2026.11.23'), patch.object(self.engine, 'install', side_effect=UpdateError()):
            self.engine.check()
        self.assertEqual(self.engine.command(), [sys.executable, '-I', '-m', 'yt_dlp'])
        self.assertEqual(self.engine.status()['result'], 'unavailable')

    def test_overlapping_checks_skip_fetch(self):
        with self.engine.db() as db:
            db.execute('UPDATE engine SET lease=?', (time.time()+120,))
        with self.release('2026.11.23') as fetch:
            self.engine.check()
            fetch.assert_not_called()
            self.assertEqual(self.engine.status()['result'], 'checking')

    def test_download_process_uses_selected_engine_and_session(self):
        from contextlib import nullcontext
        from core import Store
        store = Mock()
        store.extractor.command.return_value = ['python', '-I', '/data/extractor-updates/release/yt-dlp']
        store.sources.vault.youtube_file.return_value = nullcontext('/tmp/fixture-cookies.txt')
        store.stop_event.is_set.return_value = False
        process = Mock()
        process.stdout = io.StringIO('')
        process.wait.return_value = 0
        process.poll.return_value = 0
        folder = Path(self.tmp.name)
        with patch('core.subprocess.Popen', return_value=process) as popen:
            Store.download_youtube(store, folder, {'id':'fixture_A01'}, 'mp3', lambda value: None)
        args = popen.call_args.args[0]
        self.assertEqual(args[:6], [*store.extractor.command(), '--cookies', '/tmp/fixture-cookies.txt', '--ignore-config'])
        self.assertEqual(args[-1], 'https://www.youtube.com/watch?v=fixture_A01')
