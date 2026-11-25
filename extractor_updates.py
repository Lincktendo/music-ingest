"""Daily updates of the official signed yt-dlp zipapp, outside the application filesystem."""
from contextlib import contextmanager
from datetime import date
import hashlib
from importlib.metadata import version as package_version
import json
import logging
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urljoin, urlsplit

import requests

DAY = 24 * 3600
LEASE = 300
LATEST = 'https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest'
ASSETS = 'https://github.com/yt-dlp/yt-dlp/releases/download/'
HOSTS = {'api.github.com', 'github.com', 'release-assets.githubusercontent.com',
         'objects.githubusercontent.com', 'github-releases.githubusercontent.com'}
KEYRING = '/usr/local/share/music-ingest/yt-dlp-release-public.gpg'
VERSION = re.compile(r'(\d{4})\.(\d{1,2})\.(\d{1,2})(?:\.(\d{1,5}))?', re.ASCII)
log = logging.getLogger('music_ingest')


class UpdateError(Exception):
    pass


def version_key(tag):
    match = VERSION.fullmatch(tag) if isinstance(tag, str) else None
    if not match:
        raise UpdateError()
    year, month, day, revision = (int(n or 0) for n in match.groups())
    try:
        return date(year, month, day), revision
    except ValueError:
        raise UpdateError() from None


def fetch(url, limit, target=None, stop=None):
    """Only official release endpoints, no credentials and a bound on time and bytes."""
    deadline = time.monotonic() + 50
    size = 0
    result = bytearray()
    with requests.Session() as session:
        session.trust_env = False
        session.headers['User-Agent'] = 'Music-Ingest updater'
        for _ in range(5):
            parsed = urlsplit(url)
            if parsed.scheme != 'https' or parsed.hostname not in HOSTS or parsed.username or parsed.password or parsed.port not in (443, None):
                raise UpdateError()
            with session.get(url, stream=True, allow_redirects=False, timeout=(4, 8)) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers['Location'])
                    continue
                if response.status_code != 200:
                    raise UpdateError()
                for chunk in response.iter_content(65536):
                    if stop is not None and stop.is_set():
                        raise InterruptedError()
                    size += len(chunk)
                    if size > limit or time.monotonic() > deadline:
                        raise UpdateError()
                    if target is None:
                        result.extend(chunk)
                    else:
                        target.write(chunk)
                return bytes(result)
    raise UpdateError()


def signed_digest(directory):
    checksum = directory / 'SHA2-256SUMS'
    signature = directory / 'SHA2-256SUMS.sig'
    if any(p.is_symlink() or not p.is_file() for p in (checksum, signature)):
        raise UpdateError()
    if checksum.stat().st_size > 256_000 or signature.stat().st_size > 32_000:
        raise UpdateError()
    verified = subprocess.run(['gpgv', '--keyring', KEYRING, '--', str(signature), str(checksum)],
                              capture_output=True, timeout=8, check=False)
    if verified.returncode:
        raise UpdateError()
    matches = re.findall(r'^([0-9a-f]{64})[ \t]+[*]?yt-dlp$', checksum.read_text('ascii'), re.M)
    if len(matches) != 1:
        raise UpdateError()
    return matches[0]


def validate(directory, tag):
    archive = directory / 'yt-dlp'
    if directory.is_symlink() or archive.is_symlink() or not archive.is_file() or archive.stat().st_size > 30_000_000:
        raise UpdateError()
    expected = signed_digest(directory)
    with archive.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
            raise UpdateError()
    args = [sys.executable, '-I', str(archive), '--ignore-config', '--version']
    run = subprocess.run(args, capture_output=True, timeout=12, check=False)
    if run.returncode or version_key(run.stdout.decode('ascii').strip()) != version_key(tag):
        raise UpdateError()


class ExtractorUpdates:
    def __init__(self, data, bundled=None):
        self.root = Path(data) / 'extractor-updates'
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.bundled = bundled or package_version('yt-dlp')
        self.stop_event = threading.Event()
        self.thread = None
        self.validated = {}
        self.validation_lock = threading.Lock()
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS engine (id INTEGER PRIMARY KEY, active TEXT, previous TEXT, checked REAL, lease REAL, result TEXT)')
            db.execute("INSERT OR IGNORE INTO engine VALUES(1,'','',0,0,'pending')")

    @contextmanager
    def db(self):
        conn = sqlite3.connect(self.root/'state.sqlite', timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def row(self):
        with self.db() as db:
            return db.execute('SELECT * FROM engine WHERE id=1').fetchone()

    def usable(self, tag):
        if not tag:
            return False
        try:
            if version_key(tag) <= version_key(self.bundled):
                return False
            folder = self.root / tag
            with self.validation_lock:
                stamp = tuple((s.st_ino, s.st_size, s.st_ctime_ns, s.st_mtime_ns) for s in
                              ((folder / n).lstat() for n in ('yt-dlp', 'SHA2-256SUMS', 'SHA2-256SUMS.sig')))
                if self.validated.get(tag) != stamp:
                    validate(folder, tag)
                    self.validated[tag] = stamp
            return True
        except (OSError, ValueError, subprocess.SubprocessError, UpdateError):
            return False

    def effective(self, row):
        return next((tag for tag in (row['active'], row['previous']) if self.usable(tag)), self.bundled)

    def command(self):
        tag = self.effective(self.row())
        if tag == self.bundled:
            return [sys.executable, '-I', '-m', 'yt_dlp']
        return [sys.executable, '-I', str(self.root / tag / 'yt-dlp')]

    def status(self):
        row = self.row()
        tag = self.effective(row)
        result = row['result']
        if row['lease'] > time.time():
            result = 'checking'
        elif row['active'] and tag != row['active']:
            try:
                if version_key(self.bundled) < version_key(row['active']):
                    result = 'fallback'
            except UpdateError:
                result = 'fallback'
        return {'version': tag, 'result': result, 'last_check': row['checked'] or None, 'interval_hours': 24}

    def install(self, tag):
        if self.usable(tag):
            return
        base = ASSETS + tag + '/'
        with tempfile.TemporaryDirectory(dir=self.root, prefix='.stage-') as tmp:
            candidate = Path(tmp) / 'payload'
            candidate.mkdir(mode=0o700)
            for name, maximum in [('SHA2-256SUMS', 256_000), ('SHA2-256SUMS.sig', 32_000), ('yt-dlp', 30_000_000)]:
                with (candidate/name).open('xb') as out:
                    fetch(base+name, maximum, target=out, stop=self.stop_event)
            validate(candidate, tag)
            if self.stop_event.is_set():
                raise InterruptedError()
            final = self.root / tag
            if final.exists() or final.is_symlink():
                # An incomplete or damaged older copy can be replaced, after verification.
                os.replace(final, Path(tmp)/'previous-copy')
            os.replace(candidate, final)

    def check(self):
        now = time.time()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM engine WHERE id=1').fetchone()
            if row['lease'] > now or 0 <= now - row['checked'] < DAY:
                return
            lease = now + LEASE
            db.execute('UPDATE engine SET lease=? WHERE id=1', (lease,))
        active, previous, result = row['active'], row['previous'], 'current'
        try:
            release = json.loads(fetch(LATEST, 512_000, stop=self.stop_event))
            if release.get('draft') or release.get('prerelease'):
                raise UpdateError()
            tag = release['tag_name']
            current = self.effective(row)
            if version_key(tag) > version_key(current):
                self.install(tag)
                active, previous, result = tag, current, 'updated'
        except InterruptedError:
            with self.db() as db:
                db.execute('UPDATE engine SET lease=0 WHERE id=1 AND lease=?', (lease,))
            return
        except (UpdateError, KeyError, TypeError, AttributeError, ValueError, OSError,
                requests.RequestException, subprocess.SubprocessError):
            result = 'unavailable'
        with self.db() as db:
            changed = db.execute('UPDATE engine SET active=?,previous=?,checked=?,lease=0,result=? WHERE id=1 AND lease=?',
                                 (active, previous, time.time(), result, lease)).rowcount
        if changed and result == 'updated':
            self.clean_old({active, previous})

    def clean_old(self, keep):
        # In-flight downloads have a ten-minute limit. Retain old releases for two days.
        for path in self.root.iterdir():
            if path.name in keep or path.is_symlink() or not VERSION.fullmatch(path.name) or not path.is_dir():
                continue
            if time.time() - path.stat().st_mtime > 2*DAY:
                shutil.rmtree(path)
                with self.validation_lock:
                    self.validated.pop(path.name, None)

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        def loop():
            while not self.stop_event.is_set():
                try:
                    self.check()
                except (OSError, sqlite3.Error):
                    log.warning('No se pudo guardar el estado de actualización de yt-dlp.')
                self.stop_event.wait(300)
        self.thread = threading.Thread(target=loop, name='yt-dlp-updater', daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=9)
