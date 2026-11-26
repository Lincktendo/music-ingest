"""Music Ingest HTTP API. Intentionally limited to a trusted private network."""
from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path
import re
from audio_formats import AudioFormat, DownloadMode
from typing import Literal
from urllib.parse import parse_qs, unquote, urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from source_catalog import provider, EXID
from qobuz_store import QID
from download_tools import install_download_tools
from rotation import install_rotation
from recommendations import install_recommendations, record_search
from playlist_imports import install_imports
from listening_collection import install_collection
from listening import install_listening
from source_routes import install_sources
from extractor_updates import ExtractorUpdates
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from core import ALBUM_ID, ARTIST_ID, Catalog, Store, UserError, parse_link
from accounts import Accounts, Registry, AccessError, propose, scope_urls
from account_routes import install_account_routes
from automation import PLAYLIST_ID, Following, install as install_following

log = logging.getLogger('music_ingest')
VERSION = '0.12.0'
data = Path(os.environ.get('DATA_DIR', '/data'))
music = Path(os.environ.get('MUSIC_DIR', '/music'))
catalog = Catalog(data)
accounts = Accounts(data)
registry = Registry(accounts, music, catalog)
following = Following(registry)
updates = ExtractorUpdates(data)
try:
    from integrations import Enrichment
except ImportError:
    integrations = None
else:
    integrations = Enrichment(data)


def configure_library(library_id, store):
    store.extractor = updates
    if integrations:
        store.enricher = lambda track: integrations.enrich(library_id, track)


registry.configure_all(configure_library)


@asynccontextmanager
async def lifespan(app):
    registry.start()
    following.start()
    rotation.start()
    updates.start()
    try:
        yield
    finally:
        rotation.stop()
        updates.stop()
        following.stop()
        registry.stop()


app = FastAPI(title='Music Ingest', version=VERSION, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
allowed = [x.strip() for x in os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',') if x.strip() and x.strip() != '*']
app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed or ['localhost', '127.0.0.1'])
identity, access = install_account_routes(app, accounts, registry, catalog, integrations)
install_following(app, access, registry, following)
rotation = install_rotation(app, access, registry)
install_recommendations(app, access, registry, rotation)
install_sources(app, access, registry)
install_listening(app, access, registry)
install_collection(app, access, registry)
install_imports(app, access, registry, following)
install_download_tools(app, access, registry)


@app.middleware('http')
async def protect(request: Request, call_next):
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        origin = request.headers.get('origin')
        if origin:
            try:
                parsed = urlsplit(origin)
            except ValueError:
                return JSONResponse({'detail': 'Origen de solicitud no válido.'}, status_code=403)
            if parsed.scheme not in ('http', 'https') or parsed.netloc != request.headers.get('host') or parsed.path or parsed.query or parsed.fragment:
                return JSONResponse({'detail': 'Origen de solicitud no autorizado.'}, status_code=403)
        if request.headers.get('sec-fetch-site') == 'cross-site':
            return JSONResponse({'detail': 'Origen de solicitud no autorizado.'}, status_code=403)
        if request.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
            return JSONResponse({'detail': 'Esta acción requiere JSON.'}, status_code=415)
        # Read a bounded request body; Content-Length alone can be omitted or forged.
        limit = 65536
        if request.url.path.startswith('/api/sources'):
            try:
                access(request, request.query_params.get('library'), owner=True)
            except AccessError as error:
                return JSONResponse({'detail': error.message}, status_code=error.status)
            if request.method == 'PUT' and (request.url.path == '/api/sources/home-html' or request.url.path.endswith('/html')):
                limit = 24 * 1024 * 1024
            elif request.url.path.endswith('/cookies'):
                limit = 384 * 1024
        if request.url.path.startswith('/api/artwork/'):
            try:
                access(request, request.query_params.get('library'), owner=True)
            except AccessError as error:
                return JSONResponse({'detail': error.message}, status_code=error.status)
            limit=1_650_000
        total = 0
        chunks = []
        async for chunk in request.stream():
            total += len(chunk)
            if total > limit:
                return JSONResponse({'detail': 'Solicitud demasiado grande.'}, status_code=413)
            chunks.append(chunk)
        request._body = b''.join(chunks)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; media-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    if request.url.path == '/' or request.url.path.startswith('/static/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.exception_handler(RequestValidationError)
async def invalid_request(request, error):
    if request.url.path.startswith(('/api/sources','/api/rotation')):
        return JSONResponse({'detail': 'El archivo o la solicitud no tiene el formato esperado.'}, status_code=422)
    return await request_validation_exception_handler(request, error)


@app.exception_handler(UserError)
async def friendly_error(request, error):
    return JSONResponse({'detail': str(error)}, status_code=400)


@app.exception_handler(AccessError)
async def access_error(request, error):
    return JSONResponse({'detail': error.message}, status_code=error.status)


def catalog_call(fn, *args):
    try:
        return fn(*args)
    except UserError:
        raise
    except Exception:
        # Do not expose provider URLs, host paths, cookies or exception dumps in HTTP.
        raise HTTPException(status_code=502, detail='No se pudo consultar el catálogo. Revisá la conexión o intentá de nuevo.') from None


@app.get('/api/health')
def health():
    return {'status': 'ok', 'version': VERSION, 'mode': 'private-network'}


@app.get('/api/maintenance/engine')
def engine_status(request: Request, library: str | None = None):
    access(request, library, owner=True)
    return updates.status()


@app.get('/api/search')
def search(request: Request, q: str = '', kind: Literal['songs', 'albums', 'artists'] = 'songs', library: str | None = None):
    actor, lib = access(request, library, allow_key=True)
    sources = registry.get(lib['id']).sources
    q = q.strip()
    if not 2 <= len(q) <= 200:
        raise UserError('Escribí entre 2 y 200 caracteres para buscar.')
    if actor['kind']=='user':
        record_search(registry.get(lib['id']), actor['id'], q)
    muted=set(sources.option('muted_search',[])) | set(sources.option('removed_sources',[]))
    purchases=[]
    if 'qobuz' not in muted:
        if kind=='songs':
            purchases=sources.purchases.search(q)
        elif kind=='albums':
            purchases=sources.purchases.albums(q)
    kind_name={'songs':'song','albums':'album','artists':'artist'}[kind]
    extras=[t for t in sources.index.rows() if t['source'] not in muted and t['type']==kind_name
            and all(word in (t['title']+' '+t.get('artist','')).casefold() for word in q.casefold().split())][:35]
    if kind=='songs' and 'soundcloud.com' in sources.index.active() and 'soundcloud.com' not in muted:
        known={t.get('url') for t in extras}
        extras.extend(t for t in sources.index.search_soundcloud(q) if t['url'] not in known)
    items=[]
    if 'youtube' not in muted:
        try:
            items=catalog_call(catalog.search,q,kind)['items']
        except HTTPException:
            if not purchases and not extras:
                raise
    items=sources.describe(items)
    matched={item.get('flac_id') for item in items}
    distinct=[t for t in purchases if t['id'] not in matched]
    return {'items': sources.describe(distinct+extras)+items}


@app.get('/api/suggestions')
def suggestions(request: Request, q: str = Query(default='', max_length=200), library: str | None = None):
    _,lib=access(request,library,allow_key=True)
    src=registry.get(lib['id']).sources
    query=q.strip().casefold()
    candidates=[t for t in src.index.rows()+src.purchases.search(q) if query in t['title'].casefold()] if len(query)>=2 else []
    local=[t['title'] for t in src.describe(candidates)]
    try:
        upstream=catalog_call(catalog.suggestions,q)['items'] if 'youtube' in src.index.active() else []
    except HTTPException:
        if not local:
            raise
        upstream=[]
    return {'items':list(dict.fromkeys(local[:3]+upstream+local[3:]))[:8]}


@app.get('/api/artists/{ident}')
def artist(ident: str, request: Request, library: str | None = None):
    _, lib = access(request, library, allow_key=True)
    result = catalog_call(catalog.artist, ident)
    return {**result, 'songs': registry.get(lib['id']).sources.describe(result['songs'])}


class PreviewRequest(BaseModel):
    id: str | None = Field(default=None, max_length=160)
    type: Literal['song', 'album','playlist'] = 'song'
    url: str | None = Field(default=None, max_length=2048)


@app.get('/api/collection')
def collection(request:Request, kind:Literal['artist','album'], name:str=Query(min_length=1,max_length=300),
               source:str='youtube', artist:str='', library:str|None=None):
    _,lib=access(request,library)
    src=registry.get(lib['id']).sources
    if source not in src.index.active():
        raise UserError('Esta fuente ya no está activa.')
    norm=lambda value:' '.join(str(value or '').split()).casefold()
    if source=='youtube':
        result=catalog_call(catalog.search,name,'artists' if kind=='artist' else 'albums')['items']
        matches=[t for t in result if norm(t['title'])==norm(name) and (kind=='artist' or not artist or norm(artist)==norm(t['artist']))]
        if len(matches)==1:
            return {'open':matches[0]}
    rows=src.index.rows()
    if source=='qobuz':
        with src.store.db() as db:
            rows.extend(src.purchases.public_track(r[0]) for r in db.execute('SELECT metadata FROM qobuz_purchases'))
    if source=='youtube':
        rows.extend(catalog_call(catalog.search,name,'songs')['items'])
    songs=[r for r in rows if r.get('source','youtube')==source and r.get('type','song')=='song'
           and (norm(name) in [norm(a) for a in r.get('artist','').split(';')] if kind=='artist'
                else norm(r.get('album'))==norm(name) and (not artist or norm(r.get('artist'))==norm(artist)))]
    return {'type':kind,'title':name,'songs':src.describe(songs[:100])}


@app.post('/api/search/link')
def resolve_search_link(body:PreviewRequest, request:Request, library:str|None=None):
    _,lib=access(request,library)
    url=body.url or ''
    key=provider(url)
    source=registry.get(lib['id']).sources
    if key in source.option('removed_sources',[]):
        raise UserError('Agregá esta fuente para abrir sus enlaces.')
    u=urlsplit(url)
    path=unquote(u.path).strip('/').split('/')
    if key=='youtube':
        if u.scheme!='https':
            raise UserError('Pegá el enlace HTTPS de YouTube o YouTube Music.')
        if len(path)==2 and path[0] in ('browse','channel','artist'):
            if ARTIST_ID.fullmatch(path[1]):
                return {'type':'artist','id':path[1]}
            if path[0]=='browse' and ALBUM_ID.fullmatch(path[1]):
                return {'type':'album','id':path[1]}
        if len(path)==1 and re.fullmatch(r'@[\w.-]{2,100}',path[0]):
            # Resolve the public handle against a fixed YouTube endpoint.
            import requests
            try:
                with requests.get('https://www.youtube.com/'+path[0],timeout=(3,8),stream=True,allow_redirects=False) as reply:
                    content=reply.raw.read(2_000_000,decode_content=True).decode('utf8',errors='replace')
                match=re.search(r'<meta[^>]+itemprop="channelId"[^>]+content="(UC[\w-]+)"',content) or re.search(r'"externalId":"(UC[\w-]+)"',content) or re.search(r'<link[^>]+rel="canonical"[^>]+href="https://www.youtube.com/channel/(UC[\w-]+)',content)
                if match and ARTIST_ID.fullmatch(match[1]):
                    return {'type':'artist','id':match[1]}
            except requests.RequestException:
                pass
            raise UserError('No pude identificar ese canal. Pegá el enlace del artista desde YouTube Music.')
        if path==['playlist'] or (len(path)==2 and path[0]=='browse' and path[1].startswith('VL')):
            ident=path[1][2:] if path[0]=='browse' else parse_qs(u.query).get('list',[''])[0]
            if not PLAYLIST_ID.fullmatch(ident):
                raise UserError('Pegá el enlace de una playlist pública de YouTube Music.')
            if ident.startswith('OLAK5uy'):
                aid=catalog_call(catalog.factory().get_album_browse_id,ident)
                if ALBUM_ID.fullmatch(aid or ''):
                    return {'type':'album','id':aid}
            return {'type':'playlist','id':ident}
        parse_link(url)
        return {'type':'song','url':url}
    if key=='qobuz':
        if any(k in path for k in ('artist','interpreter','interprète')):
            pos=next(i for i,k in enumerate(path) if k in ('artist','interpreter','interprète'))
            if len(path)>pos+1:
                slug=path[pos+1].replace('-',' ').strip()
                if slug and not slug.isdecimal():
                    return {'type':'artist','name':slug,'source':key}
    return {'type':'link','url':url}


@app.post('/api/preview')
def preview(body: PreviewRequest, request: Request, library: str | None = None):
    _, lib = access(request, library, allow_key=True)
    source = registry.get(lib['id']).sources
    ident, kind = body.id, body.type
    if body.url:
        key=provider(body.url)
        if key in source.option('removed_sources',[]):
            raise UserError('Agregá esta fuente para volver a usarla.')
        if key=='youtube':
            ident,kind=parse_link(body.url),'song'
        elif key=='qobuz':
            album=re.search(r'/album/(?:[^/?]+/)?([A-Za-z0-9]+)(?:[/?#]|$)',body.url)
            if album:
                result=source.purchases.album_preview(catalog_id=album[1])
                return {**result,'tracks':source.describe(result['tracks'])}
            m=re.search(r'/track/(?:[^/?]+/)?(\d{1,16})(?:[/?#]|$)',body.url)
            if m:
                ident='qb:'+m[1]
            else:
                raise UserError('Este enlace de Qobuz es una referencia. Buscá el título o conectá tus archivos disponibles desde Inicio.')
        else:
            track=source.index.preview(body.url)
            with source.store.lock:
                if lib['role']=='owner' and key not in source.index.active() and key not in source.option('removed_sources',[]) and len(source.index.active())<34:
                    source.index.add(key)
            return {**track,'tracks':source.describe([track]),'warnings':[]}
    if kind=='playlist':
        if not PLAYLIST_ID.fullmatch(ident or '') or 'youtube' not in source.index.active():
            raise UserError('Elegí una playlist pública de YouTube Music.')
        playlist=catalog_call(catalog.factory().get_playlist,ident,50)
        tracks=[]
        for row in playlist.get('tracks',[])[:50]:
            if row.get('isAvailable') is False or row.get('videoType') not in (None,'','MUSIC_VIDEO_TYPE_ATV'):
                continue
            t=catalog.normalize({**row,'resultType':'song'})
            if t and t['id'] not in {old['id'] for old in tracks}:
                tracks.append(t)
        catalog.remember(tracks)
        return {'type':'playlist','id':ident,'title':playlist.get('title','Playlist'),'artist':'YouTube Music',
                'cover':catalog.cover(playlist.get('thumbnails')),'tracks':source.describe(tracks),
                'warnings':['Se muestran las primeras 50 pistas.'] if len(playlist.get('tracks',[]))>=50 else []}
    if ident and re.fullmatch(r'qa:[a-f0-9]{32}',ident):
        result=source.purchases.album_preview(ident=ident)
        return {**result,'tracks':source.describe(result['tracks'])}
    if ident and EXID.fullmatch(ident):
        track=source.index.get(ident)
        return {**track,'tracks':source.describe([track]),'warnings':[]}
    if not ident:
        raise UserError('Elegí una canción o pegá su enlace.')
    if kind == 'song' and QID.fullmatch(ident):
        track = source.purchases.get(ident)
        result = {**track, 'tracks': [track], 'warnings': []}
    else:
        result = catalog_call(catalog.preview, ident, kind)
    return {**result, 'tracks': source.describe(result['tracks'])}


class TrackChoice(BaseModel):
    id: str = Field(pattern=r'^(?:[A-Za-z0-9_-]{11}|qb:[0-9]{1,16}|ex:[a-f0-9]{32})$')
    expected_format: AudioFormat | None = None


class JobRequest(BaseModel):
    tracks: list[TrackChoice] = Field(min_length=1, max_length=50)
    format: DownloadMode = 'auto'


@app.post('/api/jobs', status_code=201)
def enqueue(body: JobRequest, request: Request, library: str | None = None):
    actor, lib = access(request, library)
    store = registry.get(lib['id'])
    # Only IDs are accepted; metadata and image URLs come from server-verified previews.
    tracks = store.sources.selection(body.tracks, body.format)
    if lib['role'] != 'owner':
        return propose(store, lib, actor, tracks, body.format)
    return store.enqueue(tracks, body.format) | {'kind': 'job'}


@app.get('/api/jobs')
def jobs(request: Request, library: str | None = None):
    _, lib = access(request, library)
    return scope_urls(registry.get(lib['id']).jobs(), lib['id'])


@app.post('/api/jobs/{ident}/retry')
def retry(ident: str, request: Request, library: str | None = None):
    _, lib = access(request, library, owner=True)
    return registry.get(lib['id']).retry(ident)


@app.get('/api/library')
def library_files(request: Request, library: str | None = None, offset: int = Query(default=0, ge=0), limit: int = Query(default=500, ge=1, le=500)):
    _, lib = access(request, library)
    return scope_urls(registry.get(lib['id']).library(offset=offset, limit=limit), lib['id'])


@app.delete('/api/library/{source_id}/{fmt}')
def delete_library_file(source_id: str, fmt: AudioFormat, request: Request, library: str | None = None):
    _, lib = access(request, library, owner=True)
    return registry.get(lib['id']).delete_file(source_id, fmt)


@app.api_route('/api/files/{jobid}/{filename:path}', methods=['GET', 'HEAD'])
def output_file(jobid: str, filename: str, request: Request, library: str | None = None):
    _, lib = access(request, library)
    try:
        path = registry.get(lib['id']).file_path(jobid, filename)
    except UserError:
        raise HTTPException(404, 'Archivo no encontrado.') from None
    return FileResponse(path, filename=path.name)


@app.get('/api/covers/{ident}')
def cover(ident: str):
    path = catalog_call(catalog.cover_file, ident)
    return FileResponse(path, media_type='image/jpeg')


@app.get('/favicon.ico')
def favicon():
    return RedirectResponse('/static/brand/lincktendo-32.png')


@app.get('/apple-touch-icon.png')
@app.get('/apple-touch-icon-precomposed.png')
def touch_icon():
    return RedirectResponse('/static/brand/lincktendo-180.png')


@app.get('/')
def index():
    path = Path(__file__).parent / 'static' / 'index.html'
    if not path.is_file():
        return JSONResponse({'detail': 'Interfaz en preparación.'}, status_code=503)
    return FileResponse(path, headers={'Cache-Control': 'no-cache'})


static = Path(__file__).parent / 'static'
static.mkdir(exist_ok=True)
app.mount('/static', StaticFiles(directory=static), name='static')
