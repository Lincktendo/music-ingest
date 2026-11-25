"""Resolve the Qobuz Store's purchase links. The streaming catalog is not a download source."""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
from html.parser import HTMLParser
import json
import re
import time
import unicodedata
from urllib.parse import quote, urljoin, urlsplit

import requests
from core import UserError, bounded_text
from source_sessions import header_for

PURCHASES = 'https://www.qobuz.com/profile/downloads'
STORE_HOSTS = {'www.qobuz.com', 'qobuz.com'}
QID = re.compile(r'qb:\d{1,16}\Z')
TOKEN = re.compile(r'qbzdl://([a-zA-Z0-9_+=.%~/-]{4,2048})\Z')
FLAC_TYPES = {'audio/flac', 'audio/x-flac'}
MP3_TYPES = {'audio/mpeg','audio/mp3'}
FILE_LIMIT = 300_000_000
CDNS = {'streaming-qobuz-std.akamaized.net', 'streaming-qobuz-sec.akamaized.net',
        'streaming-qobuz-hires.akamaized.net', 'download-qobuz.akamaized.net'}


def key_text(text):
    return ' '.join(unicodedata.normalize('NFKC', str(text or '')).casefold().split())


def allowed(url, media=False):
    try:
        u = urlsplit(url)
        host = u.hostname or ''
        return (u.scheme == 'https' and not u.username and not u.password and u.port in (443, None)
                and (host in STORE_HOSTS or media and (host.endswith('.qobuz.com') or host in CDNS)))
    except (TypeError, ValueError):
        return False


@contextmanager
def response_for(url, cookies, media=False):
    """Validate every redirect. Never forward a store cookie to a media CDN."""
    try:
        with requests.Session() as session:
            for _ in range(5):
                if not allowed(url, media):
                    raise UserError('La tienda devolvió un destino de descarga no reconocido.')
                cookie = header_for(cookies, url) if urlsplit(url).hostname in STORE_HOSTS else ''
                headers = {'Cookie': cookie} if cookie else {}
                session.cookies.clear()
                with session.get(url, headers=headers, stream=True, timeout=(4, 12), allow_redirects=False) as response:
                    if response.is_redirect:
                        url = urljoin(url, response.headers['Location'])
                        continue
                    if response.status_code in (401, 403):
                        raise UserError('Qobuz rechazó el acceso. Renová la sesión o el enlace de Mis compras.')
                    if response.status_code != 200:
                        raise UserError('La compra no está disponible ahora. Probá con un enlace nuevo de Qobuz.')
                    yield response
                    return
            raise UserError('Qobuz redirigió la descarga demasiadas veces.')
    except requests.RequestException:
        raise UserError('No se pudo conectar con la tienda de Qobuz. Intentá de nuevo.') from None


def small_response(url, cookies):
    data = bytearray()
    deadline = time.monotonic() + 20
    with response_for(url, cookies) as response:
        for chunk in response.iter_content(65536):
            if len(data) + len(chunk) > 4_000_000 or time.monotonic() > deadline:
                raise UserError('La tienda tardó demasiado o devolvió una página demasiado grande.')
            data.extend(chunk)
        return bytes(data), response.url


class PurchaseLinks(HTMLParser):
    def __init__(self, base):
        super().__init__()
        self.base, self.pages, self.tokens = base, [], []

    def handle_starttag(self, tag, attrs):
        if tag not in ('a', 'button'):
            return
        for name, value in attrs:
            if name not in ('href', 'data-url', 'data-href', 'data-link') or not value:
                continue
            token = TOKEN.fullmatch(value)
            if token:
                self.tokens.append(token[1])
                continue
            full = urljoin(self.base, value)
            if not allowed(full):
                continue
            path = urlsplit(full).path.lower()
            if re.search(r'/(?:profile/downloads?|account/downloads?|downloads?|telechargement|downloader)(?:/|$)', path):
                self.pages.append(full)


@dataclass
class Offer:
    track: dict
    url: str
    rank: tuple


def number(value, default=0):
    try:
        return int(float(value or default))
    except (TypeError, ValueError, OverflowError):
        return default


def offers(token, cookies):
    url = 'https://qobuz.com/v4/downloader/info?token%5B%5D=' + quote(token, safe='')
    raw, _ = small_response(url, cookies)
    try:
        manifests = json.loads(raw)
        if not isinstance(manifests, list):
            raise ValueError()
        result = {}
        for manifest in manifests:
            meta = manifest['metadata']
            albums = {str(a['id']): a for a in meta.get('albums', [])}
            tracks = {str(t['id']): t for t in meta['tracks']}
            for audio in manifest['audios']:
                ident = str(audio['track_id'])
                row = tracks.get(ident)
                if not row or not QID.fullmatch('qb:' + ident) or audio.get('mime_type') not in FLAC_TYPES | MP3_TYPES:
                    continue
                if not allowed(audio.get('url'), media=True):
                    continue
                album = albums.get(str((row.get('album') or {}).get('id')), {}) or row.get('album') or {}
                who = (row.get('performer') or {}).get('name') or '; '.join(a['name'] for a in album.get('artists', []) if a.get('name'))
                title = bounded_text(row.get('title'))
                if row.get('version'):
                    title += ' (' + bounded_text(row['version'], 90) + ')'
                if not title.strip() or not who:
                    continue
                ident = 'qb:' + ident
                bits, rate = number(audio.get('bit_depth')), number(audio.get('sampling_rate'))
                if 0 < rate < 1000:
                    # Qobuz sometimes reports sample rate in kHz (44.1 etc).
                    rate = round(float(audio['sampling_rate']) * 1000)
                track = {'id': ident, 'type': 'song', 'title': title, 'artist': bounded_text(who),
                         'album': bounded_text(album.get('title')), 'track': max(1, number(row.get('track_position'), 1)),
                         'duration': str(number(row.get('duration')) or ''), 'cover': '',
                         'cover_source': (album.get('image') or {}).get('large') or '',
                         'bit_depth': bits, 'sample_rate': rate}
                track['native_format']='FLAC' if audio.get('mime_type') in FLAC_TYPES else 'MP3'
                track['album_id']=str(album.get('id') or '')
                candidate = Offer(track, audio['url'], (track['native_format']=='FLAC',bits,rate))
                if ident not in result or candidate.rank > result[ident].rank:
                    result[ident] = candidate
        return result
    except (ValueError, KeyError, TypeError, AttributeError):
        raise UserError('Este enlace no entregó una lista de archivos FLAC. Volvé a Mis compras en Qobuz.') from None


class PurchaseCatalog:
    def __init__(self, store, vault):
        self.store, self.vault = store, vault
        with store.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS qobuz_purchases(id TEXT PRIMARY KEY, purchase TEXT, title TEXT, artist TEXT, album TEXT, metadata TEXT)')
            db.execute('CREATE INDEX IF NOT EXISTS qobuz_match ON qobuz_purchases(title,artist)')

    def add(self, token, cookies, generation):
        items = offers(token, cookies)
        if not items:
            raise UserError('Qobuz no ofreció pistas descargables para este enlace.')
        label = 'purchase:' + hashlib.sha256(token.encode()).hexdigest()
        with self.store.lock, self.store.db() as db:
            current = db.execute("SELECT value FROM library_options WHERE key='qobuz_revision'").fetchone()
            if (current[0] if current else '') != generation:
                raise UserError('La conexión Qobuz cambió. Volvé a actualizar tus compras.')
            db.execute('INSERT OR REPLACE INTO source_secrets VALUES(?,?)', (label, self.vault.seal(label, token)))
            for item in items.values():
                t = item.track.copy()
                art = t.pop('cover_source')
                if isinstance(art, str) and self.store.catalog.valid_cover(art):
                    t['artwork'] = urlsplit(art)._replace(query='', fragment='').geturl()
                prior = db.execute('SELECT purchase,metadata FROM qobuz_purchases WHERE id=?', (t['id'],)).fetchone()
                if prior and prior['purchase'] != label:
                    previous = json.loads(prior['metadata'])
                    if (previous.get('native_format','FLAC')=='FLAC',number(previous.get('bit_depth')), number(previous.get('sample_rate'))) > item.rank:
                        continue
                db.execute('INSERT OR REPLACE INTO qobuz_purchases VALUES(?,?,?,?,?,?)',
                           (t['id'], label, key_text(t['title']), key_text(t['artist']), key_text(t['album']), json.dumps(t)))
        return len(items)

    def refresh(self, link=''):
        with self.store.lock, self.store.db() as db:
            current = db.execute("SELECT value FROM library_options WHERE key='qobuz_revision'").fetchone()
            generation = current[0] if current else ''
            cookies = self.vault.read('qobuz') or []
        link = link.strip()
        manual = TOKEN.fullmatch(link)
        if manual:
            return {'indexed': self.add(manual[1], cookies, generation)}
        if link and (not allowed(link) or not re.search(r'/(?:profile/downloads?|account/downloads?|downloads?|telechargement|downloader)(?:/|$)', urlsplit(link).path, re.I)):
            raise UserError('Pegá el enlace qbzdl:// de tu compra o su página de descarga en qobuz.com.')
        if not cookies and not link:
            raise UserError('Conectá tu cuenta o pegá el enlace de una compra.')
        queue, visited, tokens = [link or PURCHASES], set(), set()
        started = time.monotonic()
        count, skipped = 0, 0
        while queue and len(visited) < 24 and time.monotonic() - started < 36:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            raw, final = small_response(url, cookies)
            if '/signin' in urlsplit(final).path or '/login' in urlsplit(final).path:
                raise UserError('Qobuz pidió iniciar sesión. Actualizá las cookies desde Mis compras.')
            page = raw.decode('utf-8', 'replace')
            links = PurchaseLinks(final)
            links.feed(page)
            # Some versions render the launch link from an inline JSON string.
            links.tokens += re.findall(r'qbzdl://([A-Za-z0-9_.~%+=/-]{4,2048})', page.replace(r'\/', '/'))
            for token in dict.fromkeys(links.tokens):
                if token in tokens:
                    continue
                if len(tokens) >= 50 or time.monotonic() - started > 36:
                    skipped += 1
                    break
                tokens.add(token)
                try:
                    count += self.add(token, cookies, generation)
                except UserError:
                    skipped += 1
            queue.extend(p for p in dict.fromkeys(links.pages) if p not in visited and p not in queue)
        if not count:
            raise UserError('No se encontraron archivos de audio en Mis compras. Abrí una compra y pegá su enlace de Qobuz Downloader aquí.')
        return {'indexed': count, 'partial': bool(skipped or queue)}

    def public_track(self, metadata):
        track = json.loads(metadata)
        artwork = track.pop('artwork', '')
        if artwork:
            track['cover'] = self.store.catalog.cover([{'url': artwork, 'width': 600}])
        if track.get('album_id'):
            track['album_browse_id']='qa:'+hashlib.sha256(str(track['album_id']).encode()).hexdigest()[:32]
        return track

    def get(self, ident):
        with self.store.db() as db:
            row = db.execute('SELECT metadata FROM qobuz_purchases WHERE id=?', (ident,)).fetchone()
        if not row:
            raise UserError('Esta compra ya no está conectada a tu biblioteca.')
        return self.public_track(row[0])

    def search(self, query):
        words = key_text(query).split()[:12]
        if not words:
            return []
        where = ' AND '.join(["instr(title || ' ' || artist || ' ' || album, ?) > 0"] * len(words))
        with self.store.db() as db:
            rows = db.execute('SELECT metadata FROM qobuz_purchases WHERE ' + where + ' ORDER BY title LIMIT 30', words)
            return [self.public_track(row[0]) for row in rows]

    def albums(self,query):
        # Limit the text search, then identify the complete album on opening.
        rows=self.search(query)
        albums={}
        for t in rows:
            if t.get('album') and t.get('album_id'):
                aid='qa:'+hashlib.sha256(t['album_id'].encode()).hexdigest()[:32]
                albums.setdefault(aid,{'id':aid,'type':'album','source':'qobuz','title':t['album'],'artist':t['artist'],'cover':t['cover']})
        return list(albums.values())

    def album_preview(self,ident=None,catalog_id=None):
        with self.store.db() as db:
            rows=db.execute("SELECT metadata FROM qobuz_purchases WHERE json_extract(metadata,'$.album_id')=?",
                            (catalog_id,)).fetchall() if catalog_id else db.execute("SELECT metadata FROM qobuz_purchases WHERE json_extract(metadata,'$.album_id') IS NOT NULL").fetchall()
        tracks=[]
        for row in rows:
            t=json.loads(row[0])
            aid='qa:'+hashlib.sha256(str(t['album_id']).encode()).hexdigest()[:32]
            if ident and ident!=aid:
                continue
            tracks.append(self.public_track(row[0]))
        if not tracks:
            raise UserError('Este álbum todavía no tiene pistas de Qobuz conectadas a tu biblioteca.')
        tracks.sort(key=lambda t:t.get('track') or 0)
        warnings=['Mostrando las primeras 50 pistas.'] if len(tracks)>50 else []
        return {'id':'qa:'+hashlib.sha256(str(tracks[0]['album_id']).encode()).hexdigest()[:32],'type':'album',
                'title':tracks[0]['album'],'artist':tracks[0]['artist'],'cover':tracks[0]['cover'],'tracks':tracks[:50],'warnings':warnings}

    def match(self, track):
        if QID.fullmatch(track['id']):
            return self.get(track['id'])
        with self.store.db() as db:
            found = db.execute('SELECT album,metadata FROM qobuz_purchases WHERE title=? AND artist=?',
                               (key_text(track.get('title')), key_text(track.get('artist')))).fetchall()
        if track.get('album'):
            found = [row for row in found if row['album'] == key_text(track['album'])]
        if len(found) == 1:
            item = self.public_track(found[0]['metadata'])
            def seconds(val):
                parts = str(val or '').split(':')
                return sum(number(x) * 60**i for i, x in enumerate(reversed(parts)))
            a, b = seconds(track.get('duration')), seconds(item.get('duration'))
            if not a or not b or abs(a - b) <= 3:
                return item
        return None

    def download(self, ident, path, progress):
        with self.store.lock, self.store.db() as db:
            row = db.execute('SELECT purchase FROM qobuz_purchases WHERE id=?', (ident,)).fetchone()
            if not row:
                raise UserError('Volvé a conectar la compra FLAC en Inicio.')
            token = self.vault.read(row[0])
            cookies = self.vault.read('qobuz') or []
        choice = offers(token, cookies).get(ident)
        if not choice:
            raise UserError('Qobuz ya no ofrece el FLAC seleccionado. Actualizá el enlace de la compra.')
        with response_for(choice.url, cookies, media=True) as response, path.open('xb') as out:
            length = number(response.headers.get('Content-Length'))
            if length > FILE_LIMIT:
                raise UserError('Esta pista FLAC supera el límite de 300 MB.')
            received = 0
            start = time.monotonic()
            for chunk in response.iter_content(256 * 1024):
                if not chunk:
                    continue
                received += len(chunk)
                if received > FILE_LIMIT or time.monotonic() - start > 600 or self.store.stop_event.is_set():
                    raise UserError('La descarga FLAC se interrumpió o superó el límite.')
                out.write(chunk)
                if length:
                    progress(min(95, 95 * received / length))
            if length and received != length:
                raise UserError('La descarga FLAC quedó incompleta. Podés reintentarla.')
