"""Opt-in metadata providers; isolated library settings, no personal integrations."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading
import time
import unicodedata
from urllib.parse import urlsplit
import uuid

import requests

USER_AGENT = 'MusicIngest/0.2 (https://github.com/Lincktendo)'
LIBRARY_ID = re.compile(r'[A-Za-z0-9_-]{1,64}\Z')
MBID = re.compile(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z')
MAX_JSON = 1_000_000
MAX_LYRICS = 160_000
DEFAULTS = {'lrclib': {'enabled': True}, 'musicbrainz': {'enabled': True},
            'lastfm': {'enabled': False}, 'duckduckgo': {'enabled': False}}
PROVIDERS = [
    {'id': 'lrclib', 'name': 'LRCLIB', 'description': 'Letras normales y sincronizadas, verificadas por título, artista y duración. Puede no haber letra para algunas canciones.',
     'requires_key': False, 'available': True, 'fields': [{'name': 'api_key', 'label': 'API key opcional de LRCLIB', 'type': 'password', 'required': False}],
     'links': [{'label': 'Documentación oficial', 'url': 'https://lrclib.net/docs'}, {'label': 'Registro opcional de aplicación', 'url': 'https://lrclib.net/developers'}],
     'steps': ['Activá LRCLIB: funciona sin cuenta ni clave.', 'Opcional: registrá una aplicación de servidor en el portal de desarrolladores.', 'Si recibís una API key de servidor, pegala aquí y guardá. Nunca la incluyás en un video.', 'Si no hay una coincidencia fiable, la canción se guarda sin letra; no se inventa una.']},
    {'id': 'musicbrainz', 'name': 'MusicBrainz', 'description': 'Géneros de la grabación o del artista cuando existe una coincidencia verificable. Sin cuenta ni contraseña.',
     'requires_key': False, 'available': True, 'fields': [],
     'links': [{'label': 'Documentación oficial', 'url': 'https://musicbrainz.org/doc/MusicBrainz_API'}, {'label': 'Límites del servicio', 'url': 'https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting'}],
     'steps': ['Activá la integración; no necesitás registrarte.', 'Se consulta la grabación por título, artista y duración; los géneros del artista se identifican como tales.', 'Las consultas respetan una separación superior a un segundo. No todos los registros tienen géneros.']},
    {'id': 'lastfm', 'name': 'Last.fm', 'description': 'Fuente adicional de géneros a partir de etiquetas públicas. Requiere tu propia API key; no necesita tu contraseña ni Shared Secret.',
     'requires_key': True, 'available': True, 'fields': [{'name': 'api_key', 'label': 'API key de Last.fm', 'type': 'password', 'required': True}],
     'links': [{'label': 'Crear una API key', 'url': 'https://www.last.fm/api/account/create'}, {'label': 'Tus aplicaciones', 'url': 'https://www.last.fm/api/accounts'}, {'label': 'Documentación oficial', 'url': 'https://www.last.fm/api/show/track.getTopTags'}],
     'steps': ['Iniciá sesión o creá una cuenta en Last.fm.', 'Abrí Crear una API key y registrá tu aplicación con un nombre y descripción.', 'Copiá únicamente API key (32 caracteres); no copies Shared Secret ni tu contraseña.', 'Pegala aquí, activá Last.fm y guardá. Dejar el campo sin enviar conserva la clave existente.']},
    {'id': 'duckduckgo', 'name': 'DuckDuckGo · experimental', 'description': 'Compatibilidad opcional con Instant Answers. Solo usa géneros estructurados de un artista exacto; la documentación oficial está archivada y la cobertura puede ser escasa.',
     'requires_key': False, 'available': True, 'experimental': True, 'fields': [],
     'links': [{'label': 'Documentación oficial archivada', 'url': 'https://github.com/duckduckgo/duckduckgo-publisher/blob/master/share/site/duckduckgo/api.tx'}, {'label': 'DuckDuckGo', 'url': 'https://duckduckgo.com/'}],
     'steps': ['Está desactivado inicialmente y no necesita una clave.', 'Activá solo si querés probar esta fuente adicional.', 'No analiza párrafos ni adivina géneros. Solo acepta el campo Genre con un artista coincidente.', 'Si mostrás sus datos, mantené la atribución a DuckDuckGo y a la fuente indicada. La falta de respuesta no impide guardar música.']},
]
KNOWN_GENRES = set('''rock|pop|jazz|blues|classical|country|folk|soul|funk|reggae|ska|metal|heavy metal|black metal|death metal|thrash metal|doom metal|power metal|progressive metal|alternative metal|nu metal|punk|punk rock|post-punk|hardcore punk|pop punk|alternative rock|indie rock|indie pop|hard rock|progressive rock|psychedelic rock|garage rock|grunge|post-rock|soft rock|symphonic metal|industrial metal|gothic metal|metalcore|deathcore|electronic|electronica|ambient|techno|house|deep house|trance|dubstep|drum and bass|jungle|breakbeat|dance|dance-pop|disco|synth-pop|synthpop|new wave|industrial|idm|trip-hop|hip hop|hip-hop|rap|trap|r&b|rhythm and blues|contemporary r&b|neo soul|gospel|latin|latin pop|latin rock|reggaeton|reggaetón|salsa|cumbia|bachata|merengue|bolero|ranchera|regional mexicano|mariachi|flamenco|bossa nova|samba|tango|afrobeat|afrobeats|k-pop|j-pop|j-rock|jazz fusion|smooth jazz|bebop|swing|bluegrass|americana|folk rock|singer-songwriter|acoustic|soundtrack|orchestral|opera|baroque|chamber music|world|new age|downtempo|electro|electropop|emo|shoegaze|dream pop|gothic rock|rock and roll|rockabilly|soul jazz|dub|dancehall|roots reggae|synthwave'''.split('|'))


class IntegrationError(ValueError):
    """A safe, user-facing configuration error; never contains credentials."""


class ProviderUnavailable(Exception):
    pass


def normal(value):
    text = unicodedata.normalize('NFKD', str(value or '').casefold())
    return ''.join(c for c in text if c.isalnum() and not unicodedata.combining(c))


def text(value, limit=300):
    return ' '.join(value.split())[:limit] if isinstance(value, str) else ''


def primary_artist(track):
    rows = track.get('artists')
    if isinstance(rows, list) and rows:
        first = rows[0]
        artist = first.get('name', '') if isinstance(first, dict) else first
    else:
        value = track.get('artist')
        artist = value.split(';')[0] if isinstance(value, str) else ''
    return text(artist)


def same_artist(candidate, wanted):
    return bool(normal(wanted)) and normal(candidate) == normal(wanted)


def genres(rows, known_only=False):
    result, seen = [], set()
    for row in rows[:100] if isinstance(rows, list) else []:
        name = text(row.get('name') if isinstance(row, dict) else row, 80)
        key = name.casefold()
        if not name or len(name) > 60 or key in seen or (known_only and key not in KNOWN_GENRES):
            continue
        seen.add(key); result.append(name)
        if len(result) == 8:
            break
    return result


class Enrichment:
    def __init__(self, data_dir):
        self.directory = Path(data_dir) / 'integration-settings'
        if self.directory.is_symlink():
            raise IntegrationError('La carpeta de integraciones no puede ser un enlace simbólico.')
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        self.provider_locks = {key: threading.Lock() for key in DEFAULTS}
        self.last_call = {key: 0.0 for key in DEFAULTS}
        self.cooldown = {key: 0.0 for key in DEFAULTS}
        self.response_cache = {}

    def _path(self, library_id):
        if not isinstance(library_id, str) or not LIBRARY_ID.fullmatch(library_id) or library_id.upper() in {'CON', 'PRN', 'AUX', 'NUL'}:
            raise IntegrationError('Biblioteca no válida.')
        path = self.directory / (library_id + '.json')
        if path.is_symlink() or path.resolve().parent != self.directory.resolve():
            raise IntegrationError('Ruta de configuración no válida.')
        return path

    def _load(self, library_id):
        path = self._path(library_id)
        result = copy.deepcopy(DEFAULTS)
        if not path.exists():
            return result
        if path.stat().st_size > 16_384:
            raise IntegrationError('La configuración de integraciones no es válida.')
        try:
            saved = json.loads(path.read_text(encoding='utf8'))
            if not isinstance(saved, dict):
                raise ValueError()
            for key in DEFAULTS:
                row = saved.get(key, {})
                if isinstance(row, dict):
                    if isinstance(row.get('enabled'), bool): result[key]['enabled'] = row['enabled']
                    if key in ('lastfm', 'lrclib') and isinstance(row.get('api_key'), str): result[key]['api_key'] = self._key(key, row['api_key'])
        except (ValueError, OSError, TypeError):
            raise IntegrationError('No se pudo leer la configuración de integraciones.') from None
        return result

    @staticmethod
    def _key(provider, value):
        if not isinstance(value, str):
            raise IntegrationError('La clave debe ser texto.')
        value = value.strip()
        if not value: return ''
        if provider == 'lastfm' and not re.fullmatch('[A-Fa-f0-9]{32}', value):
            raise IntegrationError('La API key de Last.fm debe tener 32 caracteres hexadecimales.')
        if provider == 'lrclib' and (len(value) > 512 or not re.fullmatch(r'[A-Za-z0-9_./+=:-]{8,512}', value)):
            raise IntegrationError('La API key de LRCLIB no tiene un formato válido.')
        return value

    def get_settings(self, library_id):
        with self.lock:
            saved = self._load(library_id)
        definitions = copy.deepcopy(PROVIDERS)
        for definition in definitions:
            row = saved[definition['id']]
            definition.update(enabled=row['enabled'], configured=bool(row.get('api_key')) if definition['fields'] else True)
        return {'version': 1, 'providers': definitions}

    def save_settings(self, library_id, payload):
        if not isinstance(payload, dict) or set(payload) - {'providers'} or not isinstance(payload.get('providers'), dict):
            raise IntegrationError('Configuración no válida.')
        changes = payload['providers']
        if set(changes) - set(DEFAULTS):
            raise IntegrationError('Proveedor no válido.')
        with self.lock:
            saved = self._load(library_id)
            for provider, values in changes.items():
                allowed = {'enabled', 'api_key'} if provider in ('lrclib', 'lastfm') else {'enabled'}
                if not isinstance(values, dict) or set(values) - allowed:
                    raise IntegrationError('Campos de integración no válidos.')
                if 'enabled' in values:
                    if not isinstance(values['enabled'], bool): raise IntegrationError('El estado de integración debe ser verdadero o falso.')
                    saved[provider]['enabled'] = values['enabled']
                if 'api_key' in values: saved[provider]['api_key'] = self._key(provider, values['api_key'])
            target = self._path(library_id)
            temporary = self.directory / (uuid.uuid4().hex + '.tmp')
            try:
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'w', encoding='utf8') as stream:
                    json.dump(saved, stream, ensure_ascii=False); stream.flush(); os.fsync(stream.fileno())
                os.chmod(temporary, 0o600)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
            self.response_cache.clear()
        return self.get_settings(library_id)

    def _request(self, provider, path, params, key=''):
        # Caller cannot provide a host: paths are constants or validated MusicBrainz UUIDs.
        bases = {'lrclib': 'https://lrclib.net', 'musicbrainz': 'https://musicbrainz.org', 'lastfm': 'https://ws.audioscrobbler.com', 'duckduckgo': 'https://api.duckduckgo.com'}
        permitted = {'lrclib': path == '/api/get', 'lastfm': path == '/2.0/', 'duckduckgo': path == '/',
                     'musicbrainz': bool(re.fullmatch(r'/ws/2/(?:recording|artist)/(?:[0-9a-f-]{36})?', path))}
        if provider not in bases or not permitted[provider]: raise ProviderUnavailable()
        digest = hashlib.sha256(json.dumps([provider, path, params, key], sort_keys=True).encode()).hexdigest()
        with self.lock:
            cached = self.response_cache.get(digest)
            if cached and time.monotonic() - cached[0] < 3600: return copy.deepcopy(cached[1])
        with self.provider_locks[provider]:
            now = time.monotonic()
            if now < self.cooldown[provider]: raise ProviderUnavailable()
            pause = self.last_call[provider] + (1.1 if provider == 'musicbrainz' else 0.4) - now
            if pause > 0: time.sleep(pause)
            headers = {'User-Agent': USER_AGENT, 'Accept': 'application/json'}
            if key and provider == 'lrclib': headers['Lrclib-Api-Key'] = key
            try:
                with requests.Session() as session:
                    session.trust_env = False  # No inherited proxies, netrc, or personal credentials.
                    with session.get(bases[provider] + path, params=params, headers=headers, timeout=(3, 7), allow_redirects=False, stream=True) as response:
                        if response.status_code in (429, 503):
                            delay = 60.0
                            raw = response.headers.get('Retry-After', '')
                            try: delay = max(delay, float(raw))
                            except ValueError:
                                try: delay = max(delay, (parsedate_to_datetime(raw) - datetime.now(timezone.utc)).total_seconds())
                                except (ValueError, TypeError, OverflowError): pass
                            self.cooldown[provider] = time.monotonic() + delay + 1
                            raise ProviderUnavailable()
                        if response.status_code == 404: return None
                        if response.status_code != 200: raise ProviderUnavailable()
                        payload = bytearray(); deadline = time.monotonic() + 15
                        for chunk in response.iter_content(32_768):
                            payload.extend(chunk)
                            if len(payload) > MAX_JSON or time.monotonic() > deadline: raise ProviderUnavailable()
                        result = json.loads(payload)
            finally:
                self.last_call[provider] = time.monotonic()
        with self.lock:
            while len(self.response_cache) >= 256: self.response_cache.pop(next(iter(self.response_cache)))
            self.response_cache[digest] = (time.monotonic(), result)
        return copy.deepcopy(result)

    def _lyrics(self, track, settings):
        artist, title = primary_artist(track), text(track.get('title'))
        duration = track.get('duration_seconds')
        if isinstance(duration, bool) or not isinstance(duration, (float, int)) or not math.isfinite(duration) or not 1 <= duration <= 3600:
            return '', '', 'unverified'
        row = self._request('lrclib', '/api/get', {'artist_name': artist, 'track_name': title, 'album_name': text(track.get('album')), 'duration': round(duration, 2)}, settings.get('api_key', ''))
        if not isinstance(row, dict): return '', '', 'missing'
        actual = row.get('duration')
        if not normal(title) or normal(row.get('trackName')) != normal(title) or not same_artist(row.get('artistName'), artist) or not isinstance(actual, (int, float)) or not math.isfinite(actual) or abs(actual - duration) > 2:
            return '', '', 'unverified'
        if row.get('instrumental') is True: return '', '', 'instrumental'
        plain, synced = row.get('plainLyrics'), row.get('syncedLyrics')
        plain = plain.strip() if isinstance(plain, str) and len(plain) <= MAX_LYRICS else ''
        synced = synced.strip() if isinstance(synced, str) and len(synced) <= MAX_LYRICS and re.search(r'\[\d{1,3}:\d{2}(?:[.:]\d{1,3})?\]', synced) else ''
        return plain, synced, 'synced' if synced else 'plain' if plain else 'missing'

    def _musicbrainz(self, track):
        artist, title = primary_artist(track), text(track.get('title'))
        quote = lambda value: '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'
        found = self._request('musicbrainz', '/ws/2/recording/', {'query': 'recording:' + quote(title) + ' AND artist:' + quote(artist), 'fmt': 'json', 'limit': 5}) or {}
        duration = track.get('duration_seconds')
        matches = []
        for row in found.get('recordings', [])[:5]:
            credits = row.get('artist-credit', [])
            names = [credit.get('artist', {}).get('name', '') for credit in credits if isinstance(credit, dict)]
            length = row.get('length')
            if normal(row.get('title')) != normal(title) or not any(same_artist(name, artist) for name in names): continue
            if not isinstance(duration, (float, int)) or not math.isfinite(duration) or not isinstance(length, (float, int)) or abs(length / 1000 - duration) > 3: continue
            if MBID.fullmatch(str(row.get('id', ''))): matches.append(row)
        if matches:
            row = min(matches, key=lambda r: abs(r['length'] / 1000 - duration))
            detail = self._request('musicbrainz', '/ws/2/recording/' + row['id'], {'inc': 'genres', 'fmt': 'json'}) or {}
            result = genres(detail.get('genres'))
            if result: return result, 'recording'
        # Artist-level genres are explicitly reported as artist-derived, never track-specific.
        found = self._request('musicbrainz', '/ws/2/artist/', {'query': 'artist:' + quote(artist), 'fmt': 'json', 'limit': 5}) or {}
        exact = [row for row in found.get('artists', [])[:5] if same_artist(row.get('name'), artist) and MBID.fullmatch(str(row.get('id', '')))]
        ids = {row['id'] for row in exact}
        if len(ids) != 1: return [], 'missing'
        detail = self._request('musicbrainz', '/ws/2/artist/' + next(iter(ids)), {'inc': 'genres', 'fmt': 'json'}) or {}
        result = genres(detail.get('genres'))
        return result, 'artist' if result else 'missing'

    def _lastfm(self, track, settings):
        artist, title = primary_artist(track), text(track.get('title'))
        result = self._request('lastfm', '/2.0/', {'method': 'track.getTopTags', 'artist': artist, 'track': title, 'api_key': settings['api_key'], 'format': 'json', 'autocorrect': 0}) or {}
        if result.get('error'): raise ProviderUnavailable()
        tags = result.get('toptags', {}); identity = tags.get('@attr', {})
        if not same_artist(identity.get('artist'), artist) or normal(identity.get('track')) != normal(title): return []
        return genres(tags.get('tag'), known_only=True)

    def _duckduckgo(self, track):
        artist = primary_artist(track)
        result = self._request('duckduckgo', '/', {'q': artist + ' musician', 'format': 'json', 'no_html': 1, 'no_redirect': 1, 'skip_disambig': 1}) or {}
        if not same_artist(result.get('Heading'), artist): return [], []
        structured = []
        box = result.get('Infobox') or {}
        for item in box.get('content', [])[:80] if isinstance(box, dict) else []:
            if isinstance(item, dict) and text(item.get('label')).casefold() in ('genre', 'genres'):
                structured.extend(re.split(r'[,/;\n]', text(item.get('value'), 1000)))
        values = genres(structured)
        source_url = result.get('AbstractURL', '')
        try:
            parsed = urlsplit(source_url)
            safe = parsed.scheme == 'https' and not parsed.username and not parsed.password and parsed.port in (None, 443) and parsed.hostname and (parsed.hostname == 'wikipedia.org' or parsed.hostname.endswith('.wikipedia.org'))
        except (ValueError, TypeError): safe = False
        # Without a validated underlying-source attribution, leave the optional data unused.
        if not values or not safe: return [], []
        return values, [{'provider': 'DuckDuckGo', 'label': 'DuckDuckGo Instant Answers', 'url': 'https://duckduckgo.com/'}, {'provider': 'DuckDuckGo', 'label': text(result.get('AbstractSource')) or 'Fuente original', 'url': source_url}]

    def enrich(self, library_id, track):
        output = {'lyrics': '', 'synced_lyrics': '', 'genres': [], 'metadata_sources': [], 'metadata_attributions': [], 'metadata_status': {'lyrics': 'disabled', 'genres': 'disabled'}, 'warnings': []}
        try:
            with self.lock: settings = self._load(library_id)
        except Exception:
            output['warnings'].append('No se pudo leer la configuración de metadatos. El audio se conserva.'); return output
        if not isinstance(track, dict) or not primary_artist(track) or not text(track.get('title')):
            output['metadata_status'] = {'lyrics': 'unverified', 'genres': 'unverified'}; return output
        if settings['lrclib']['enabled']:
            try:
                plain, synced, status = self._lyrics(track, settings['lrclib'])
                output.update(lyrics=plain, synced_lyrics=synced); output['metadata_status']['lyrics'] = status
                if plain or synced or status == 'instrumental': output['metadata_sources'].append('LRCLIB')
            except Exception:
                output['metadata_status']['lyrics'] = 'unavailable'; output['warnings'].append('LRCLIB no pudo responder. El audio se guardó sin añadir letras.')
        for provider in ('musicbrainz', 'lastfm', 'duckduckgo'):
            if not settings[provider]['enabled']: continue
            if output['metadata_status']['genres'] == 'disabled': output['metadata_status']['genres'] = 'missing'
            if provider == 'lastfm' and not settings[provider].get('api_key'):
                output['warnings'].append('Last.fm está activado, pero falta su API key.'); continue
            try:
                scope = 'recording'
                if provider == 'musicbrainz': values, scope = self._musicbrainz(track)
                elif provider == 'lastfm': values = self._lastfm(track, settings[provider])
                else:
                    values, credits = self._duckduckgo(track); scope = 'artist'
                    output['metadata_attributions'].extend(credits)
                if values:
                    output['genres'] = genres(output['genres'] + values)
                    output['metadata_sources'].append({'musicbrainz': 'MusicBrainz', 'lastfm': 'Last.fm', 'duckduckgo': 'DuckDuckGo'}[provider])
                    if output['metadata_status']['genres'] != 'recording': output['metadata_status']['genres'] = scope
            except Exception:
                output['warnings'].append({'musicbrainz': 'MusicBrainz', 'lastfm': 'Last.fm', 'duckduckgo': 'DuckDuckGo'}[provider] + ' no pudo consultar los géneros. El audio se conserva.')
        if output['metadata_status']['lyrics'] in ('missing', 'unverified'): output['warnings'].append('No se encontró una letra con título, artista y duración suficientemente coincidentes.')
        if output['metadata_status']['genres'] == 'missing': output['warnings'].append('No se encontraron géneros verificables para esta selección.')
        return output
