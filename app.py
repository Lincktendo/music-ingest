"""Music Ingest HTTP API. Intentionally limited to a trusted private network."""
from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path
import re
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from core import Catalog, Store, UserError, parse_link
from accounts import Accounts, Registry, AccessError, propose, scope_urls
from account_routes import install_account_routes
from automation import Following, install as install_following

log = logging.getLogger('music_ingest')
data = Path(os.environ.get('DATA_DIR', '/data'))
music = Path(os.environ.get('MUSIC_DIR', '/music'))
catalog = Catalog(data)
accounts = Accounts(data)
registry = Registry(accounts, music, catalog)
following = Following(registry)
try:
    from integrations import Enrichment
except ImportError:
    integrations = None
else:
    integrations = Enrichment(data)
    registry.configure_all(lambda lid, store: setattr(store, 'enricher', lambda track: integrations.enrich(lid, track)))


@asynccontextmanager
async def lifespan(app):
    registry.start()
    following.start()
    yield
    following.stop()
    registry.stop()


app = FastAPI(title='Music Ingest', version='0.4.0-beta.1', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
allowed = [x.strip() for x in os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',') if x.strip() and x.strip() != '*']
app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed or ['localhost', '127.0.0.1'])
identity, access = install_account_routes(app, accounts, registry, catalog, integrations)
install_following(app, access, registry, following)


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
        total = 0
        chunks = []
        async for chunk in request.stream():
            total += len(chunk)
            if total > 65536:
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
    return {'status': 'ok', 'version': '0.4.0-beta.1', 'mode': 'private-network'}


@app.get('/api/search')
def search(request: Request, q: str = '', kind: Literal['songs', 'albums', 'artists'] = 'songs', library: str | None = None):
    access(request, library, allow_key=True)
    q = q.strip()
    if not 2 <= len(q) <= 200:
        raise UserError('Escribí entre 2 y 200 caracteres para buscar.')
    return catalog_call(catalog.search, q, kind)


@app.get('/api/suggestions')
def suggestions(request: Request, q: str = Query(default='', max_length=200), library: str | None = None):
    access(request, library, allow_key=True)
    return catalog_call(catalog.suggestions, q)


@app.get('/api/artists/{ident}')
def artist(ident: str, request: Request, library: str | None = None):
    access(request, library, allow_key=True)
    return catalog_call(catalog.artist, ident)


class PreviewRequest(BaseModel):
    id: str | None = Field(default=None, max_length=160)
    type: Literal['song', 'album'] = 'song'
    url: str | None = Field(default=None, max_length=2048)


@app.post('/api/preview')
def preview(body: PreviewRequest, request: Request, library: str | None = None):
    access(request, library, allow_key=True)
    ident, kind = body.id, body.type
    if body.url:
        ident, kind = parse_link(body.url), 'song'
    if not ident:
        raise UserError('Elegí una canción o pegá su enlace.')
    return catalog_call(catalog.preview, ident, kind)


class TrackChoice(BaseModel):
    id: str = Field(min_length=11, max_length=11)


class JobRequest(BaseModel):
    tracks: list[TrackChoice] = Field(min_length=1, max_length=50)
    format: Literal['mp3', 'original'] = 'mp3'


@app.post('/api/jobs', status_code=201)
def enqueue(body: JobRequest, request: Request, library: str | None = None):
    actor, lib = access(request, library)
    store = registry.get(lib['id'])
    # Only IDs are accepted; metadata and image URLs come from server-verified previews.
    tracks = catalog.selected([x.id for x in body.tracks])
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
def delete_library_file(source_id: str, fmt: Literal['mp3', 'original'], request: Request, library: str | None = None):
    _, lib = access(request, library, owner=True)
    return registry.get(lib['id']).delete_file(source_id, fmt)


@app.get('/api/files/{jobid}/{filename:path}')
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


@app.get('/')
def index():
    path = Path(__file__).parent / 'static' / 'index.html'
    if not path.is_file():
        return JSONResponse({'detail': 'Interfaz en preparación.'}, status_code=503)
    return FileResponse(path, headers={'Cache-Control': 'no-cache'})


static = Path(__file__).parent / 'static'
static.mkdir(exist_ok=True)
app.mount('/static', StaticFiles(directory=static), name='static')
