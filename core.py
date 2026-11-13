"""Small, isolated catalog and persistent download queue. No personal integrations."""
from __future__ import annotations

import base64
from contextlib import contextmanager
from functools import partial
import hashlib
import io
import json
import os
from pathlib import Path
import queue
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import unicodedata
from urllib.parse import parse_qs, quote, urlsplit
import uuid

import requests
from PIL import Image
from ytmusicapi import YTMusic
from storage import music_path

VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")
ALBUM_ID = re.compile(r"MPREb[A-Za-z0-9_-]{5,150}\Z")
ARTIST_ID = re.compile(r"UC[A-Za-z0-9_-]{20,100}\Z")
COVER_HOSTS = {'i.ytimg.com', 'img.youtube.com', 'yt3.googleusercontent.com', 'lh3.googleusercontent.com', 'yt3.ggpht.com'}
MEDIA_EXTS = {'.mp3', '.m4a', '.opus', '.ogg', '.flac'}


class UserError(ValueError):
    pass


def safe_name(value, fallback='Sin título'):
    value = unicodedata.normalize('NFC', str(value))
    value = re.sub(r'[\x00-\x1f\x7f<>:"/\\|?*]', ' ', value)
    value = re.sub(r'\s+', ' ', value).strip(' .')[:100].strip(' .') or fallback
    if value.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        value = '_' + value
    return value


def parse_link(value):
    try:
        u = urlsplit(value.strip())
        port = u.port
    except ValueError:
        raise UserError('El enlace no es válido.') from None
    if u.scheme != 'https' or u.username or u.password or port not in (None, 443):
        raise UserError('Usá un enlace HTTPS de YouTube o YouTube Music.')
    if u.hostname == 'youtu.be':
        ident = u.path.strip('/')
    elif u.hostname in ('youtube.com', 'www.youtube.com', 'music.youtube.com') and u.path == '/watch':
        ident = parse_qs(u.query).get('v', [''])[0]
    else:
        raise UserError('Pegá el enlace de una canción. Para álbumes, usá la búsqueda.')
    if not VIDEO_ID.fullmatch(ident):
        raise UserError('El enlace no contiene una canción válida.')
    return ident


def bounded_text(value, n=300):
    return str(value or '').strip()[:n]


def suggestion_client():
    session = requests.Session()
    session.request = partial(session.request, timeout=(2, 4))
    try:
        return YTMusic(language='es', requests_session=session)
    except Exception:
        session.close()
        raise


class Catalog:
    def __init__(self, data, factory=None, suggest_factory=None):
        self.data = Path(data)
        self.covers = self.data / 'covers'
        self.covers.mkdir(parents=True, exist_ok=True)
        self.factory = factory or (lambda: YTMusic(language='en', requests_session=True))
        self.lock = threading.RLock()
        self.cache = {}
        self.cover_sources = {}
        self.suggest_factory = suggest_factory or factory or suggestion_client
        self.suggestion_cache = {}
        self.suggestion_slots = threading.BoundedSemaphore(2)

    def suggestions(self, query):
        query = ' '.join(query.split())
        if len(query) > 200:
            raise UserError('La búsqueda admite hasta 200 caracteres.')
        if len(query) < 2 or query.lower().startswith(('http://', 'https://', 'www.')):
            return {'items': []}
        key = query.casefold()
        with self.lock:
            now = time.monotonic()
            self.suggestion_cache = {k: v for k, v in self.suggestion_cache.items() if now - v[0] < 60}
            cached = self.suggestion_cache.get(key)
            if cached:
                return {'items': list(cached[1])}
        # Autocomplete must not occupy the entire HTTP worker pool.
        if not self.suggestion_slots.acquire(blocking=False):
            return {'items': []}
        client = None
        try:
            client = self.suggest_factory()
            rows = client.get_search_suggestions(query)
            items, seen = [], set()
            for row in rows[:40] if isinstance(rows, list) else []:
                if not isinstance(row, str):
                    continue
                text = ' '.join(row.split())
                if not text or len(text) > 200 or text.casefold() in seen:
                    continue
                seen.add(text.casefold())
                items.append(text)
                if len(items) == 8:
                    break
            with self.lock:
                while len(self.suggestion_cache) >= 128 and key not in self.suggestion_cache:
                    self.suggestion_cache.pop(next(iter(self.suggestion_cache)))
                self.suggestion_cache[key] = (time.monotonic(), tuple(items))
            return {'items': items}
        finally:
            try:
                session = getattr(client, '_session', None)
                if session is not None:
                    session.close()
            finally:
                self.suggestion_slots.release()

    def cover(self, thumbs):
        valid = [x for x in thumbs or [] if isinstance(x, dict) and self.valid_cover(x.get('url', ''))]
        if not valid:
            return ''
        url = max(valid, key=lambda x: x.get('width') or 0)['url']
        ident = hashlib.sha256(url.encode()).hexdigest()
        with self.lock:
            while len(self.cover_sources) >= 2048 and ident not in self.cover_sources:
                self.cover_sources.pop(next(iter(self.cover_sources)))
            self.cover_sources[ident] = url
        return '/api/covers/' + ident

    @staticmethod
    def valid_cover(url):
        try:
            u = urlsplit(url)
            return u.scheme == 'https' and u.hostname in COVER_HOSTS and not u.username and not u.password and u.port in (None, 443)
        except (ValueError, TypeError):
            return False

    def cover_file(self, ident):
        if not re.fullmatch('[a-f0-9]{64}', ident):
            raise UserError('Portada no válida.')
        target = self.covers / (ident + '.jpg')
        if target.is_symlink() or target.resolve().parent != self.covers.resolve():
            raise UserError('Portada no válida.')
        if target.is_file():
            return target
        with self.lock:
            url = self.cover_sources.get(ident)
        if not url or not self.valid_cover(url):
            raise UserError('Esta portada ya no está disponible; repetí la búsqueda.')
        # Redirects never inherit trust; fixed host allowlist and bounded response.
        with requests.get(url, timeout=(8, 20), allow_redirects=False, stream=True) as response:
            if response.status_code != 200:
                raise UserError('No se pudo cargar la portada.')
            payload = bytearray()
            for chunk in response.iter_content(65536):
                payload.extend(chunk)
                if len(payload) > 5_000_000:
                    raise UserError('Portada demasiado grande.')
        with Image.open(io.BytesIO(payload)) as image:
            if image.width * image.height > 16_000_000:
                raise UserError('Portada demasiado grande.')
            image = image.convert('RGB')
            image.thumbnail((1000, 1000))
            output = io.BytesIO()
            image.save(output, 'JPEG', quality=90)
        tmp = target.with_suffix('.' + uuid.uuid4().hex + '.tmp')
        tmp.write_bytes(output.getvalue())
        os.replace(tmp, target)
        return target

    @staticmethod
    def artists(rows):
        return '; '.join(bounded_text(x.get('name'), 120) for x in rows or [] if isinstance(x, dict) and x.get('name'))

    def normalize(self, row):
        kind = row.get('resultType') or 'song'
        ident = row.get('videoId') if kind == 'song' else row.get('browseId')
        pattern = {'song': VIDEO_ID, 'album': ALBUM_ID, 'artist': ARTIST_ID}.get(kind)
        if not pattern or not pattern.fullmatch(ident or ''):
            return None
        if kind == 'artist':
            title = bounded_text(row.get('artist') or row.get('title'))
            return {'id': ident, 'type': kind, 'title': title, 'artist': title, 'album': '', 'cover': self.cover(row.get('thumbnails')), 'duration': ''}
        album = row.get('album') if isinstance(row.get('album'), dict) else {}
        return {'id': ident, 'type': kind, 'title': bounded_text(row.get('title')), 'artist': self.artists(row.get('artists')), 'album': bounded_text(album.get('name')), 'cover': self.cover(row.get('thumbnails')), 'duration': bounded_text(row.get('duration'), 20)}

    def search(self, query, kind):
        rows = self.factory().search(query, filter=kind, limit=20)
        result = []
        for row in rows:
            if row.get('resultType') not in ('song', 'album', 'artist'):
                continue
            item = self.normalize(row)
            if item:
                result.append(item)
        self.remember([item for item in result[:30] if item['type'] == 'song'])
        return {'items': result[:30]}

    def artist(self, ident):
        if not ARTIST_ID.fullmatch(ident or ''):
            raise UserError('Artista no válido.')
        raw = self.factory().get_artist(ident)
        title = bounded_text(raw.get('name'))
        if not title:
            raise UserError('Este artista no está disponible.')
        groups = {'songs': [], 'albums': []}
        for source, kind, destination in [('songs', 'song', 'songs'), ('albums', 'album', 'albums'), ('singles', 'album', 'albums')]:
            section = raw.get(source) or {}
            for row in section.get('results', [])[:30]:
                if not isinstance(row, dict):
                    continue
                item = self.normalize({**row, 'resultType': kind, 'artists': row.get('artists') or [{'name': title}]})
                if item and item['id'] not in {x['id'] for x in groups[destination]}:
                    groups[destination].append(item)
        self.remember(groups['songs'])
        return {'id': ident, 'type': 'artist', 'title': title, 'cover': self.cover(raw.get('thumbnails')), 'description': bounded_text(raw.get('description'), 1600), **groups}

    def remember(self, tracks):
        with self.lock:
            now = time.time()
            self.cache = {k: v for k, v in self.cache.items() if now - v[0] < 7200}
            if len(self.cache) > 3000:
                self.cache.clear()
            for track in tracks:
                self.cache[track['id']] = (now, dict(track))

    def selected(self, ids):
        if not ids or len(ids) > 50 or len(set(ids)) != len(ids):
            raise UserError('Elegí entre 1 y 50 canciones, sin repetirlas.')
        with self.lock:
            selected = []
            for ident in ids:
                entry = self.cache.get(ident)
                if not VIDEO_ID.fullmatch(ident) or not entry or time.time() - entry[0] > 7200:
                    raise UserError('Revisá de nuevo la selección antes de descargar.')
                selected.append(dict(entry[1]))
            return selected

    def preview(self, ident, kind='song'):
        api = self.factory()
        warnings = []
        if kind == 'album':
            if not ALBUM_ID.fullmatch(ident or ''):
                raise UserError('Álbum no válido.')
            album = api.get_album(ident)
            title = bounded_text(album.get('title'))
            artist = self.artists(album.get('artists'))
            cover = self.cover(album.get('thumbnails'))
            tracks = []
            for i, row in enumerate(album.get('tracks') or [], 1):
                tid = row.get('videoId') or ''
                if not VIDEO_ID.fullmatch(tid) or row.get('isAvailable') is False:
                    warnings.append('Una pista del álbum no está disponible.')
                    continue
                if any(t['id'] == tid for t in tracks):
                    continue
                tracks.append({'id': tid, 'title': bounded_text(row.get('title')), 'artist': self.artists(row.get('artists')) or artist, 'album': title, 'cover': cover, 'duration': bounded_text(row.get('duration'), 20), 'track': i})
            if len(tracks) > 50:
                warnings.append('Esta prueba muestra las primeras 50 pistas del álbum.')
                tracks = tracks[:50]
        else:
            if not VIDEO_ID.fullmatch(ident or ''):
                raise UserError('Canción no válida.')
            raw = api.get_song(ident).get('videoDetails') or {}
            if not raw.get('title') or raw.get('videoId') != ident:
                raise UserError('La canción no está disponible.')
            if int(raw.get('lengthSeconds') or 0) > 3600 or raw.get('isLiveContent'):
                raise UserError('Esta versión admite canciones de hasta una hora, no transmisiones en vivo.')
            title, artist = bounded_text(raw.get('title')), bounded_text(raw.get('author'))
            cover = self.cover((raw.get('thumbnail') or {}).get('thumbnails'))
            album_name = ''
            duration = str(raw.get('lengthSeconds') or '')
            try:
                watch = api.get_watch_playlist(videoId=ident, limit=1)
                row = next((t for t in watch.get('tracks') or [] if t.get('videoId') == ident), {})
                title = bounded_text(row.get('title')) or title
                artist = self.artists(row.get('artists')) or artist
                album_name = bounded_text((row.get('album') or {}).get('name'))
                cover = self.cover(row.get('thumbnail') or row.get('thumbnails')) or cover
                duration = bounded_text(row.get('length'), 20) or duration
            except Exception:
                warnings.append('Algunos datos del álbum no están disponibles; se conservarán los de la fuente.')
            tracks = [{'id': ident, 'title': title, 'artist': artist, 'album': album_name, 'cover': cover, 'duration': duration, 'track': 1}]
        if not tracks:
            raise UserError('No hay canciones disponibles en esta selección.')
        self.remember(tracks)
        return {'id': ident, 'title': title, 'artist': artist, 'cover': cover, 'tracks': tracks, 'warnings': list(dict.fromkeys(warnings))}


def tag_file(path, track, cover):
    from mutagen import File
    from mutagen.id3 import ID3, TIT2, TPE1, TALB, TRCK, APIC, TXXX, TCON, USLT, SYLT
    from mutagen.mp4 import MP4Cover
    from mutagen.flac import Picture
    title, artist, album = track['title'], track['artist'], track.get('album') or ''
    number = str(track.get('track') or 1)
    lyrics = bounded_text(track.get('lyrics'), 100000)
    synced = bounded_text(track.get('synced_lyrics'), 100000)
    genres = [bounded_text(x, 80) for x in (track.get('genres') or [])[:8] if isinstance(x, str) and x.strip()]
    if path.suffix == '.mp3':
        tags = ID3()
        for value in (TIT2(encoding=3, text=title), TPE1(encoding=3, text=artist), TALB(encoding=3, text=album), TRCK(encoding=3, text=number), TXXX(encoding=3, desc='Source ID', text=track['id'])):
            tags.add(value)
        if cover:
            tags.add(APIC(encoding=3, mime='image/jpeg', type=3, desc='Cover', data=cover))
        if genres:
            tags.add(TCON(encoding=3, text=genres))
        if lyrics:
            tags.add(USLT(encoding=3, lang='und', desc='', text=lyrics))
        if synced:
            tags.add(TXXX(encoding=3, desc='LYRICS_SYNCED', text=synced))
            timed = []
            for line in synced.splitlines():
                stamps = re.findall(r'\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]', line)
                text = re.sub(r'^((\[[^\]]+\])+)', '', line).strip()
                for minute, second, fraction in stamps:
                    timed.append((text, (int(minute) * 60 + int(second)) * 1000 + int((fraction or '0').ljust(3, '0'))))
            if timed:
                tags.add(SYLT(encoding=3, lang='und', format=2, type=1, desc='', text=sorted(timed, key=lambda x: x[1])))
        tags.save(path, v2_version=3)
    else:
        audio = File(path)
        if audio is None:
            raise UserError('El formato obtenido no admite etiquetas en esta versión.')
        if audio.tags is None:
            audio.add_tags()
        if path.suffix == '.m4a':
            audio.tags['\xa9nam'], audio.tags['\xa9ART'], audio.tags['\xa9alb'] = [title], [artist], [album]
            audio.tags['trkn'] = [(int(number), 0)]
            if cover:
                audio.tags['covr'] = [MP4Cover(cover, imageformat=MP4Cover.FORMAT_JPEG)]
            if genres:
                audio.tags['\xa9gen'] = genres
            if lyrics:
                audio.tags['\xa9lyr'] = [lyrics]
            if synced:
                audio.tags['----:com.apple.iTunes:LYRICS_SYNCED'] = [synced.encode('utf8')]
        else:
            audio.tags['title'], audio.tags['artist'], audio.tags['album'], audio.tags['tracknumber'] = [title], [artist], [album], [number]
            if cover:
                picture = Picture(); picture.type = 3; picture.mime = 'image/jpeg'; picture.data = cover
                audio.tags['metadata_block_picture'] = [base64.b64encode(picture.write()).decode()]
            if genres:
                audio.tags['genre'] = genres
            if lyrics:
                audio.tags['lyrics'] = [lyrics]
            if synced:
                audio.tags['syncedlyrics'] = [synced]
        audio.save()


def classify_error(text):
    lower = text.lower()
    if 'sign in' in lower or 'not a bot' in lower:
        return 'La fuente pide iniciar sesión. Esta prueba no importa cookies ni cuentas; probá otra canción.'
    if '403' in lower:
        return 'La fuente rechazó la descarga (403). Probá más tarde o con otra canción.'
    if '429' in lower:
        return 'La fuente limitó las solicitudes. Esperá unos minutos antes de reintentar.'
    if 'private' in lower or 'unavailable' in lower or 'removed' in lower:
        return 'La canción no está disponible desde este servidor.'
    return 'No se pudo obtener el audio. No se agregó ningún archivo incompleto; podés reintentar.'


class Store:
    def __init__(self, data, music, catalog):
        self.data, self.music, self.catalog = Path(data), Path(music), catalog
        self.data.mkdir(parents=True, exist_ok=True)
        self.music.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data / 'jobs.sqlite'
        self.lock = threading.RLock()
        self.event, self.stop_event = threading.Event(), threading.Event()
        self.thread = None
        self.enricher = None
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS library_options(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, status TEXT, payload TEXT, progress REAL, error TEXT, created_at REAL)')
            db.execute('CREATE TABLE IF NOT EXISTS files(source_id TEXT, format TEXT, name TEXT, metadata TEXT, job_id TEXT, PRIMARY KEY(source_id,format))')
            db.execute('CREATE TABLE IF NOT EXISTS managed_sidecars(name TEXT PRIMARY KEY)')
            db.execute("UPDATE jobs SET status='interrupted',error='El servidor se reinició. Podés reintentar las canciones pendientes.' WHERE status IN ('queued','running')")

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.db_path, timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def start(self):
        self.thread = threading.Thread(target=self.loop, name='music-ingest-worker', daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set(); self.event.set()
        if self.thread:
            self.thread.join(timeout=12)

    def enqueue(self, tracks, fmt):
        if fmt not in ('mp3', 'original'):
            raise UserError('Formato no válido.')
        payload = {'tracks': tracks, 'format': fmt}
        with self.lock, self.db() as db:
            if db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0] >= 10:
                raise UserError('La cola está llena. Esperá a que terminen algunas descargas.')
            ident = uuid.uuid4().hex
            db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?)', (ident, 'queued', json.dumps(payload, ensure_ascii=False), 0, '', time.time()))
        self.event.set()
        return {'id': ident}

    def update(self, ident, status=None, progress=None, error=None):
        values = {k: v for k, v in {'status': status, 'progress': progress, 'error': error}.items() if v is not None}
        with self.db() as db:
            db.execute('UPDATE jobs SET ' + ','.join(k + '=?' for k in values) + ' WHERE id=?', (*values.values(), ident))

    def retry(self, ident):
        with self.lock, self.db() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (ident,)).fetchone()
            if not row or row['status'] not in ('failed', 'interrupted'):
                raise UserError('Solo se pueden reintentar trabajos fallidos o interrumpidos.')
            if db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0] >= 10:
                raise UserError('La cola está llena.')
            db.execute("UPDATE jobs SET status='queued',error='',progress=0 WHERE id=?", (ident,))
        self.event.set()
        return {'id': ident}

    def public_file(self, row):
        try:
            path = music_path(self.music, row['name'])
        except (ValueError, OSError):
            return None
        if not path.is_file():
            return None
        item = json.loads(row['metadata'])
        # Lyrics live in audio tags / an LRC file, not repeatedly in polling JSON.
        # Also strips legacy rows written before this summary policy existed.
        item.pop('lyrics', None)
        item.pop('synced_lyrics', None)
        output = {**item, 'source_id': row['source_id'], 'format': row['format'], 'job_id': row['job_id'], 'name': row['name'], 'url': '/api/files/' + row['job_id'] + '/' + quote(row['name'], safe='')}
        if item.get('lyrics_file'):
            try:
                sidecar = music_path(self.music, item['lyrics_file'])
                if sidecar.is_file():
                    output['lyrics_url'] = '/api/files/' + row['job_id'] + '/' + quote(item['lyrics_file'], safe='/')
            except (ValueError, OSError):
                pass
        return output

    def library(self, offset=0, limit=500):
        if not isinstance(offset, int) or offset < 0 or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise UserError('Página de biblioteca no válida.')
        with self.db() as db:
            total = db.execute('SELECT count(*) FROM files').fetchone()[0]
            rows = db.execute('SELECT * FROM files ORDER BY rowid DESC LIMIT ? OFFSET ?', (limit, offset)).fetchall()
            return {'items': [item for row in rows if (item := self.public_file(row))], 'total': total,
                    'next_offset': offset + len(rows) if offset + len(rows) < total else None}

    def delete_file(self, source_id, fmt):
        """Remove only an app-registered audio and provably app-created sidecars."""
        if not VIDEO_ID.fullmatch(source_id or '') or fmt not in ('mp3', 'original'):
            raise UserError('Canción no válida.')
        warning = ''
        with self.lock, self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM files WHERE source_id=? AND format=?', (source_id, fmt)).fetchone()
            if not row:
                raise UserError('Esta canción ya no está en la biblioteca.')
            for job in db.execute("SELECT payload FROM jobs WHERE status IN ('queued','running')"):
                payload = json.loads(job['payload'])
                if payload['format'] == fmt and any(track['id'] == source_id for track in payload['tracks']):
                    raise UserError('Esta canción todavía está en una descarga. Esperá a que termine para eliminarla.')
            try:
                audio = music_path(self.music, row['name'])
                if not audio.is_file():
                    raise ValueError()
            except (ValueError, OSError):
                raise UserError('No se puede eliminar este archivo desde la biblioteca.') from None
            # Another registration may point to the same physical audio. Keep it.
            shared_audio = db.execute('SELECT count(*) FROM files WHERE name=?', (row['name'],)).fetchone()[0] > 1
            if not shared_audio:
                try:
                    audio.unlink()
                except OSError:
                    raise UserError('No pudimos eliminar el archivo. Revisá los permisos de la carpeta.') from None
            sidecar_name = json.loads(row['metadata']).get('lyrics_file')
            db.execute('DELETE FROM files WHERE source_id=? AND format=?', (source_id, fmt))
            if sidecar_name and db.execute('SELECT 1 FROM managed_sidecars WHERE name=?', (sidecar_name,)).fetchone():
                shared = db.execute("SELECT 1 FROM files WHERE json_extract(metadata,'$.lyrics_file')=? OR name=? LIMIT 1", (sidecar_name, sidecar_name)).fetchone()
                if not shared:
                    try:
                        sidecar = music_path(self.music, sidecar_name)
                        if sidecar.is_file():
                            sidecar.unlink()
                        db.execute('DELETE FROM managed_sidecars WHERE name=?', (sidecar_name,))
                    except (ValueError, OSError):
                        warning = 'La canción se eliminó, pero su archivo de letra se conservó.'
            # Keep automation discovery records, so the next scan does not undo
            # an intentional deletion. A manual download remains possible.
        return {'deleted': True, 'source_id': source_id, 'format': fmt, 'warning': warning}

    def jobs(self):
        with self.db() as db:
            jobs = db.execute('SELECT * FROM jobs ORDER BY created_at DESC LIMIT 100').fetchall()
            parsed = [(row, json.loads(row['payload'])) for row in jobs]
            needed = list({(t['id'], payload['format']) for _, payload in parsed for t in payload['tracks']})
            indexed = {}
            # Fetch only files referenced by visible jobs, and keep one small summary
            # per source/format. Never materialize all historic lyrics in memory.
            for offset in range(0, len(needed), 200):
                batch = needed[offset:offset + 200]
                sql = 'SELECT * FROM files WHERE ' + ' OR '.join('(source_id=? AND format=?)' for _ in batch)
                for row in db.execute(sql, [value for pair in batch for value in pair]):
                    indexed[(row['source_id'], row['format'])] = self.public_file(row)
        result = []
        for row, payload in parsed:
            files = []
            for track in payload['tracks']:
                found = indexed.get((track['id'], payload['format']))
                if found:
                    files.append(found)
            title = payload['tracks'][0]['title']
            if len(payload['tracks']) > 1:
                title += f" + {len(payload['tracks']) - 1} canciones"
            warnings = list(dict.fromkeys(f['warning'] for f in files if f.get('warning')))
            result.append({k: row[k] for k in ('id', 'status', 'progress', 'error', 'created_at')} | {'title': title, 'files': files, 'total': len(payload['tracks']), 'warnings': warnings})
        return {'items': result}

    def file_path(self, jobid, name):
        try:
            path = music_path(self.music, name)
        except (ValueError, OSError):
            raise UserError('Archivo no válido.') from None
        with self.db() as db:
            row = db.execute('SELECT * FROM files WHERE job_id=? AND name=?', (jobid, name)).fetchone()
            if not row and name.endswith('.lrc'):
                candidates = db.execute('SELECT * FROM files WHERE job_id=?', (jobid,)).fetchall()
                row = next((x for x in candidates if json.loads(x['metadata']).get('lyrics_file') == name), None)
        if not row or not self.public_file(row):
            raise UserError('Archivo no encontrado.')
        if not path.is_file():
            raise UserError('Archivo no encontrado.')
        return path

    def existing(self, track, fmt):
        with self.db() as db:
            row = db.execute('SELECT * FROM files WHERE source_id=? AND format=?', (track['id'], fmt)).fetchone()
        return bool(row and self.public_file(row))

    def publish_lyrics(self, destination, synced):
        """Reuse equal regular LRC files; never replace a user's different lyrics."""
        content = (bounded_text(synced, 100000) + '\n').encode('utf8')
        temporary = destination.parent / ('.lyrics-' + uuid.uuid4().hex + '.tmp')
        choices = [destination.with_suffix('.lrc'), destination.with_suffix(destination.suffix + '.lrc'),
                   destination.with_suffix(destination.suffix + '-' + uuid.uuid4().hex[:10] + '.lrc')]
        try:
            with temporary.open('xb') as stream:
                stream.write(content)
                stream.flush(); os.fsync(stream.fileno())
            for path in choices:
                try:
                    os.link(temporary, path)
                    relative = path.relative_to(self.music).as_posix()
                    with self.db() as db:
                        db.execute('INSERT OR IGNORE INTO managed_sidecars VALUES(?)', (relative,))
                    return relative
                except FileExistsError:
                    if path.is_symlink() or not path.is_file() or path.resolve().parent != destination.parent.resolve():
                        continue
                    # Bounded read; an existing arbitrary large file is not loaded.
                    with path.open('rb') as stream:
                        if stream.read(len(content) + 1) == content:
                            return path.relative_to(self.music).as_posix()
            raise OSError('No free lyric filename')
        finally:
            temporary.unlink(missing_ok=True)

    def loop(self):
        while not self.stop_event.is_set():
            with self.db() as db:
                row = db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if not row:
                self.event.wait(1); self.event.clear(); continue
            self.execute(row)

    def execute(self, row):
        ident = row['id']; payload = json.loads(row['payload'])
        self.update(ident, status='running', error='')
        try:
            for index, track in enumerate(payload['tracks']):
                if self.stop_event.is_set():
                    raise UserError('Descarga interrumpida; podés reintentarla.')
                if not self.existing(track, payload['format']):
                    self.download(ident, track, payload['format'], lambda p: self.update(ident, progress=(index + p / 100) * 100 / len(payload['tracks'])))
                self.update(ident, progress=(index + 1) * 100 / len(payload['tracks']))
            self.update(ident, status='completed', progress=100)
        except UserError as error:
            self.update(ident, status='interrupted' if self.stop_event.is_set() else 'failed', error=str(error))
        except Exception:
            self.update(ident, status='failed', error='No se pudo terminar el archivo. Comprobá espacio y permisos de las carpetas de datos y música.')

    def download(self, jobid, track, fmt, progress):
        if min(shutil.disk_usage(self.data).free, shutil.disk_usage(self.music).free) < 500_000_000:
            raise UserError('Queda poco espacio en disco. Liberá al menos 500 MB antes de descargar.')
        folder = self.data / 'temp' / uuid.uuid4().hex
        folder.mkdir(parents=True)
        try:
            command = [sys.executable, '-m', 'yt_dlp', '--ignore-config', '--no-cache-dir', '--no-playlist', '--newline', '--no-colors', '--socket-timeout', '20', '--retries', '1', '--fragment-retries', '1', '--max-filesize', '150M', '--match-filter', 'duration <= 3600 & !is_live', '--js-runtimes', 'deno', '-f', 'bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio', '-x', '--audio-format', 'mp3' if fmt == 'mp3' else 'best', '--audio-quality', '0', '-o', str(folder / 'audio.%(ext)s'), 'https://www.youtube.com/watch?v=' + track['id']]
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf8', errors='replace', start_new_session=(os.name == 'posix'))
            lines = queue.Queue()
            def reader():
                try:
                    for line in process.stdout:
                        lines.put(line)
                finally:
                    lines.put(None)
            threading.Thread(target=reader, daemon=True).start()
            deadline = time.monotonic() + 600
            tail = ''
            try:
                while True:
                    if self.stop_event.is_set() or time.monotonic() > deadline:
                        raise UserError('La descarga se interrumpió o tardó demasiado. Podés reintentarla.')
                    if sum(p.stat().st_size for p in folder.glob('*') if p.is_file()) > 400_000_000:
                        raise UserError('La descarga superó el límite de tamaño de esta prueba.')
                    try:
                        line = lines.get(timeout=1)
                    except queue.Empty:
                        continue
                    if line is None:
                        break
                    tail = (tail + line)[-6000:]
                    match = re.search(r'\[download\]\s+(\d+(?:\.\d+)?)%', line)
                    if match:
                        progress(min(96, float(match.group(1)) * .96))
                if process.wait(timeout=10):
                    raise UserError(classify_error(tail))
            finally:
                if process.poll() is None:
                    if os.name == 'posix':
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    else:
                        process.kill()
                    process.wait(timeout=10)
                process.stdout.close()
            candidates = [p for p in folder.iterdir() if p.suffix in MEDIA_EXTS]
            if len(candidates) != 1 or candidates[0].stat().st_size < 1000:
                raise UserError('La fuente no produjo un archivo de audio válido.')
            source = candidates[0]
            from mutagen import File
            audio = File(source)
            if audio is None or audio.info is None or not 0 < audio.info.length <= 3610:
                raise UserError('El audio obtenido no pasó la verificación.')
            track = dict(track)
            track['duration_seconds'] = float(audio.info.length)
            if self.enricher:
                try:
                    enrichment = self.enricher(dict(track))
                    for key in ('lyrics', 'synced_lyrics', 'genres', 'metadata_sources', 'metadata_status', 'metadata_attributions'):
                        if key in enrichment:
                            track[key] = enrichment[key]
                    if enrichment.get('warnings'):
                        track['warning'] = ' '.join(str(x) for x in enrichment['warnings'])[:1000]
                except Exception:
                    track['warning'] = 'El audio se guardó; no se pudieron completar las letras o los géneros.'
            cover = None
            if track.get('cover'):
                try:
                    cover = self.catalog.cover_file(track['cover'].rsplit('/', 1)[-1]).read_bytes()
                except Exception:
                    track['warning'] = (track.get('warning', '') + ' El audio se guardó, pero la fuente no entregó la portada.').strip()
            tag_file(source, track, cover)
            # Copy to destination filesystem, then publish with an exclusive hard link.
            name = safe_name(track['artist'], 'Artista') + ' - ' + safe_name(track['title']) + ' [' + track['id'] + ']' + source.suffix
            with self.db() as db:
                selected_folder = db.execute("SELECT value FROM library_options WHERE key='output_folder'").fetchone()
            try:
                output_directory = music_path(self.music, selected_folder[0] if selected_folder else '', directory=True)
            except (ValueError, OSError):
                raise UserError('La carpeta de salida ya no está disponible. Elegí otra en Ajustes.') from None
            destination = output_directory / name
            temporary = output_directory / ('.ingest-' + uuid.uuid4().hex + '.tmp')
            try:
                with temporary.open('xb') as output, source.open('rb') as original:
                    shutil.copyfileobj(original, output)
                    output.flush(); os.fsync(output.fileno())
                try:
                    os.link(temporary, destination)
                except FileExistsError:
                    # Never replace an existing user file or trust its contents as ours.
                    name = destination.stem + '-' + uuid.uuid4().hex[:8] + source.suffix
                    destination = output_directory / name
                    os.link(temporary, destination)
                name = destination.relative_to(self.music).as_posix()
                if track.get('synced_lyrics'):
                    try:
                        track['lyrics_file'] = self.publish_lyrics(destination, track['synced_lyrics'])
                    except (OSError, UnicodeError):
                        track['warning'] = (track.get('warning', '') + ' No se pudo guardar el archivo LRC adicional; se conservó la letra embebida.').strip()
                summary = {key: value for key, value in track.items() if key not in ('lyrics', 'synced_lyrics')}
                with self.db() as db:
                    db.execute('INSERT OR REPLACE INTO files VALUES(?,?,?,?,?)', (track['id'], fmt, name, json.dumps(summary, ensure_ascii=False), jobid))
            finally:
                temporary.unlink(missing_ok=True)
            progress(100)
        finally:
            shutil.rmtree(folder, ignore_errors=True)
