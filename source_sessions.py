"""Library-local credentials for explicitly connected providers."""
from contextlib import contextmanager
import json
import os
import re
import tempfile
import time
from urllib.parse import urlsplit

from Cryptodome.Cipher import AES
from core import UserError

COOKIE_HOSTS = {'youtube': {'youtube.com', 'www.youtube.com', 'music.youtube.com'},
                'qobuz': {'qobuz.com', 'www.qobuz.com'}}
COOKIE_NAME = re.compile(r"[!#$%&'*+.^_\x60|~0-9A-Za-z-]{1,128}\Z")
COOKIE_VALUE = re.compile(r"[\x21-\x3a\x3c-\x7e]{1,8192}\Z")


def cookie_rows(provider, text, allowed_hosts=None):
    hosts = allowed_hosts or COOKIE_HOSTS.get(provider,set())
    if not hosts or not isinstance(text, str) or len(text) > 60000:
        raise UserError('Elegí un archivo de cookies de este sitio (hasta 60 KB).')
    rows = {}
    for line in text.lstrip('\ufeff').splitlines():
        if line.startswith('#HttpOnly_'):
            line = line[len('#HttpOnly_'):]
        elif not line.strip() or line.startswith('#'):
            continue
        fields = line.split('\t')
        if len(fields) != 7:
            raise UserError('Usá el formato Netscape cookies.txt. Abrí la ayuda ⓘ para ver los pasos.')
        domain, subdomains, path, secure, expiry, name, value = fields
        bare = domain.lstrip('.').lower()
        if bare not in hosts:
            raise UserError('Este archivo incluye otros sitios. Exportá únicamente las cookies del sitio que querés conectar.')
        if (not COOKIE_NAME.fullmatch(name) or not COOKIE_VALUE.fullmatch(value)
                or not re.fullmatch(r'/[^\s\x00-\x1f;]{0,500}', path)
                or subdomains not in ('TRUE', 'FALSE') or secure not in ('TRUE', 'FALSE')
                or not re.fullmatch(r'\d{1,12}', expiry)):
            continue
        if int(expiry) and int(expiry) < time.time():
            continue
        rows[(bare, path, name)] = [bare, subdomains == 'TRUE', path, int(expiry), name, value]
    if not rows:
        raise UserError('El archivo no contiene cookies vigentes del sitio elegido. Exportá solo ese dominio.')
    if len(rows) > 200:
        raise UserError('Demasiadas cookies. Exportá únicamente las del sitio elegido.')
    return list(rows.values())


def header_for(rows, url):
    parsed = urlsplit(url)
    host, path = parsed.hostname or '', parsed.path or '/'
    if parsed.scheme != 'https':
        return ''
    pairs = []
    for domain, subs, prefix, expiry, name, value in sorted(rows, key=lambda r: -len(r[2])):
        if expiry and expiry <= time.time():
            continue
        if host != domain and not (subs and host.endswith('.' + domain)):
            continue
        if path == prefix or path.startswith(prefix.rstrip('/') + '/'):
            pairs.append(name + '=' + value)
    return '; '.join(pairs)


class PrivateSources:
    """The key and encrypted records stay in the library's data volume, never in /music."""
    def __init__(self, store):
        self.store = store
        self.dir = store.data / 'private-sources'
        self.dir.mkdir(mode=0o700, exist_ok=True)
        self.keyfile = self.dir / 'key'
        with store.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS source_secrets(name TEXT PRIMARY KEY, value BLOB NOT NULL)')

    def key(self):
        # Calls are serialized by the per-library store lock. Publish a complete key atomically.
        if not self.keyfile.exists():
            with tempfile.NamedTemporaryFile(dir=self.dir, delete=False) as temp:
                temp.write(os.urandom(32))
                temp.flush()
                os.fsync(temp.fileno())
            try:
                try:
                    os.link(temp.name, self.keyfile)
                except FileExistsError:
                    pass
            finally:
                os.unlink(temp.name)
        return self.keyfile.read_bytes()

    def seal(self, label, value):
        cipher = AES.new(self.key(), AES.MODE_GCM)
        cipher.update(label.encode())
        encrypted, tag = cipher.encrypt_and_digest(json.dumps(value, ensure_ascii=False).encode())
        return cipher.nonce + tag + encrypted

    def read(self, label):
        with self.store.lock, self.store.db() as db:
            row = db.execute('SELECT value FROM source_secrets WHERE name=?', (label,)).fetchone()
            if not row:
                return None
            data = row[0]
            try:
                cipher = AES.new(self.key(), AES.MODE_GCM, nonce=data[:16])
                cipher.update(label.encode())
                return json.loads(cipher.decrypt_and_verify(data[32:], data[16:32]))
            except (ValueError, OSError):
                raise UserError('No se pudo abrir la sesión guardada. Volvé a conectar tu cuenta.') from None

    def save(self, label, value):
        with self.store.lock, self.store.db() as db:
            db.execute('INSERT OR REPLACE INTO source_secrets VALUES(?,?)', (label, self.seal(label, value)))

    def youtube_file(self):
        return self.session_file('youtube')

    @contextmanager
    def session_file(self, provider):
        rows = self.read(provider)
        if not rows:
            yield None
            return
        # yt-dlp can rewrite its jar. Each job gets an ephemeral, domain-scoped copy.
        temp = tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix='.txt', delete=False)
        try:
            with temp:
                temp.write('# Netscape HTTP Cookie File\n')
                for domain, subs, path, expires, name, value in rows:
                    temp.write('\t'.join([('.' if subs else '') + domain, 'TRUE' if subs else 'FALSE',
                                         path, 'TRUE', str(expires), name, value]) + '\n')
            yield temp.name
        finally:
            os.unlink(temp.name)
