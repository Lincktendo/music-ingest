"""Import a saved YouTube Music home as text, or fetch recommendations from that library's session."""
from html.parser import HTMLParser
import json
import re
from urllib.parse import parse_qs, urljoin, urlsplit

import requests
from ytmusicapi import YTMusic

from core import ALBUM_ID, ARTIST_ID, VIDEO_ID, Catalog, UserError, bounded_text
from source_sessions import header_for

HOME = 'https://music.youtube.com/'
MAX_HTML = 12 * 1024 * 1024


def target(path):
    try:
        u = urlsplit(urljoin(HOME, path))
        if u.scheme != 'https' or u.hostname != 'music.youtube.com' or u.username or u.password or u.port not in (None, 443):
            return None
        args = parse_qs(u.query)
    except (ValueError, TypeError):
        return None
    if u.path == '/watch':
        ident = args.get('v', [''])[0]
        return ('song', ident) if VIDEO_ID.fullmatch(ident) else None
    if u.path.startswith(('/browse/', '/channel/')):
        ident = u.path.split('/')[-1]
        if ALBUM_ID.fullmatch(ident):
            return 'album', ident
        if ARTIST_ID.fullmatch(ident):
            return 'artist', ident
    if u.path == '/playlist' and re.fullmatch(r'[\w-]{8,150}', args.get('list', [''])[0], re.ASCII):
        return 'playlist', args['list'][0]
    return None



ATV = 'MUSIC_VIDEO_TYPE_ATV'


def album_art(url):
    if not public_thumbnail(url) or urlsplit(url).hostname not in ('lh3.googleusercontent.com','yt3.googleusercontent.com','yt3.ggpht.com'):
        return ''
    dims = re.search(r'=w(\d+)-h(\d+)',url)
    if dims and dims[1] != dims[2]:
        return ''
    return re.sub(r'=w\d+-h\d+', '=w640-h640', public_thumbnail(url), count=1)


def public_thumbnail(value):
    if not isinstance(value, str) or len(value) > 2048 or not Catalog.valid_cover(value):
        return ''
    return urlsplit(value)._replace(query='', fragment='').geturl()


class HomeLinks(HTMLParser):
    card_tags = {'ytmusic-two-row-item-renderer', 'ytmusic-responsive-list-item-renderer',
                 'ytmusic-grid-media', 'ytmusic-playlist-panel-video-renderer'}

    def __init__(self):
        super().__init__()
        self.items, self.current, self.parts = {}, None, []
        self.card = None
        self.title = self.aria = ''

    def add(self, entry, title, artist='', thumbnail='', video_type='', album='', album_id='', artist_id=''):
        title = ' '.join(title.split())[:200]
        if not entry or not title or len(self.items) >= 250 and entry not in self.items:
            return
        kind, ident = entry
        item = self.items.setdefault(entry, {'type': kind, 'id': ident, 'title': title, 'artist': '', 'cover': ''})
        if artist and artist != title:
            item['artist'] = bounded_text(artist, 160)
        if video_type:
            item['video_type'] = video_type
        if album:
            item.update(album=bounded_text(album), album_id=album_id)
        if artist_id and artist:
            item['artists'] = [{'name': artist, 'id': artist_id}]
        if thumbnail and (not item.get('thumbnail') or album_art(thumbnail)):
            item['thumbnail'] = thumbnail

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if tag in self.card_tags:
            self.card = {'tag': tag, 'entries': [], 'thumb': ''}
        elif tag == 'img' and self.card and not self.card['thumb']:
            self.card['thumb'] = public_thumbnail(fields.get('src') or fields.get('data-src'))
        elif tag == 'a':
            self.current = target(fields.get('href') or '')
            self.title, self.aria = fields.get('title') or '', fields.get('aria-label') or ''
            self.parts = []

    def handle_data(self, value):
        if self.current and len(self.parts) < 20:
            self.parts.append(value[:220])

    def handle_endtag(self, tag):
        if tag == 'a':
            name = self.title or ' '.join(self.parts).strip() or self.aria
            if self.card is not None and self.current and name:
                if len(self.card['entries']) < 16:
                    self.card['entries'].append((self.current, name))
            elif not self.card:
                self.add(self.current, name)
            self.current = None
        elif self.card and self.card['tag'] == tag:
            entries = self.card['entries']
            if entries:
                entry, title = entries[0]
                artist = next((name for (kind, ident), name in entries[1:] if kind == 'artist'), '')
                aid = next((i for (k,i),name in entries[1:] if k=='artist'), '')
                album = next(((name,i) for (k,i),name in entries[1:] if k=='album'), ('',''))
                self.add(entry, title, artist, self.card['thumb'], album=album[0], album_id=album[1], artist_id=aid)
            self.card = None


def import_home(content):
    if not isinstance(content, str) or len(content.encode()) > MAX_HTML:
        raise UserError('Elegí un HTML de YouTube Music de hasta 12 MB.')
    parser = HomeLinks()
    try:
        parser.feed(content)
        parser.close()
    except (AssertionError, ValueError, RecursionError):
        raise UserError('Ese HTML no se pudo leer. Guardá otra vez la página.') from None
    # Rendered pages have links. Some saved pages put the same rows in initial JSON instead.
    if len(parser.items) < 250:
        markers = re.finditer(r'"(?:musicResponsiveListItemRenderer|musicTwoRowItemRenderer)"\s*:\s*(?=\{)', content)
        for index, match in enumerate(markers):
            if index >= 400 or len(parser.items) == 250:
                break
            try:
                row, _ = json.JSONDecoder().raw_decode(content[match.end():match.end() + 65536])
                title = row.get('title') or row['flexColumns'][0]['musicResponsiveListItemFlexColumnRenderer']['text']
                runs = title.get('runs', [])
                text = ''.join(run.get('text', '') for run in runs)
                endpoint = row.get('navigationEndpoint') or (runs[0].get('navigationEndpoint') if runs else {}) or {}
                vid = (endpoint.get('watchEndpoint') or {}).get('videoId') or (row.get('playlistItemData') or {}).get('videoId')
                browse = (endpoint.get('browseEndpoint') or {}).get('browseId')
                entry = target('/watch?v=' + vid) if isinstance(vid, str) else target('/browse/' + browse) if isinstance(browse, str) else None
                thumbs = ((row.get('thumbnailRenderer') or row.get('thumbnail') or {}).get('musicThumbnailRenderer') or {}).get('thumbnail') or {}
                thumb = next((public_thumbnail(th.get('url')) for th in reversed(thumbs.get('thumbnails') or []) if isinstance(th, dict) and public_thumbnail(th.get('url'))), '')
                video_type = (endpoint.get('watchEndpoint') or {}).get('watchEndpointMusicSupportedConfigs',{}).get('watchEndpointMusicConfig',{}).get('musicVideoType','')
                metadata = list((row.get('subtitle') or {}).get('runs',[]))
                for col in (row.get('flexColumns') or [])[1:]:
                    metadata.extend(col.get('musicResponsiveListItemFlexColumnRenderer',{}).get('text',{}).get('runs',[]))
                links = [(r.get('navigationEndpoint',{}).get('browseEndpoint',{}).get('browseId',''),r.get('text','')) for r in metadata]
                aid, artist = next(((i,n) for i,n in links if ARTIST_ID.fullmatch(i)),('',''))
                bid, album = next(((i,n) for i,n in links if ALBUM_ID.fullmatch(i)),('',''))
                parser.add(entry, text, artist, thumb, video_type, album, bid, aid)
            except (TypeError, ValueError, KeyError, IndexError, AttributeError, RecursionError):
                continue
    if not parser.items:
        raise UserError('No encontré canciones, álbumes ni playlists. Abrí Inicio en music.youtube.com, bajá un poco y volvé a guardar la página.')
    return list(parser.items.values())


class MusicSession(requests.Session):
    def request(self, method, url, **kwargs):
        if urlsplit(url).scheme != 'https' or urlsplit(url).hostname != 'music.youtube.com':
            raise UserError('YouTube Music cambió el destino de la solicitud.')
        kwargs['timeout'] = (3, 7)
        kwargs['allow_redirects'] = False
        return super().request(method, url, **kwargs)


def live_home(rows, catalog):
    cookie = header_for(rows, HOME + 'youtubei/v1/browse')
    if not cookie:
        raise UserError('La sesión de YouTube Music venció. Volvé a cargar tus cookies.')
    headers = {'Cookie': cookie, 'Origin': HOME.rstrip('/'), 'X-Goog-AuthUser': '0',
               'Authorization': 'SAPISIDHASH', 'Content-Type': 'application/json',
               'User-Agent': 'Mozilla/5.0'}
    try:
        with MusicSession() as session:
            client = YTMusic(auth=headers, requests_session=session, language='es')
            account = client.get_account_info()
            if not account.get('accountName') and not account.get('channelHandle'):
                raise ValueError()
            result = []
            for section in client.get_home(limit=4):
                for row in section.get('contents', []):
                    if not isinstance(row, dict) or not (row.get('title') or row.get('artist')):
                        continue
                    kind = 'song' if row.get('videoId') else 'album'
                    item = catalog.normalize({**row, 'resultType': kind})
                    if not item:
                        browse = row.get('browseId') or ''
                        if ARTIST_ID.fullmatch(browse):
                            item = catalog.normalize({**row, 'resultType': 'artist'})
                        elif re.fullmatch(r'[\w-]{8,150}', row.get('playlistId') or '', re.ASCII):
                            item = {'type': 'playlist', 'id': row['playlistId'], 'title': bounded_text(row['title']),
                                    'artist': '', 'cover': catalog.cover(row.get('thumbnails'))}
                    if item:
                        thumb = next((public_thumbnail(t.get('url')) for t in reversed(row.get('thumbnails') or []) if isinstance(t, dict) and public_thumbnail(t.get('url'))), '')
                        if thumb:
                            item['thumbnail'] = thumb
                        if not any(old['id'] == item['id'] for old in result):
                            result.append(item)
                    if len(result) >= 60:
                        return result
            return result
    except Exception:
        raise UserError('YouTube Music no pudo cargar tu inicio. Revisá que las cookies sean de una sesión iniciada o importá el HTML.') from None
