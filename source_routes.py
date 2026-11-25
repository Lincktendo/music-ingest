from typing import Literal

from fastapi import Request
from pydantic import BaseModel, Field

from core import UserError


class Preference(BaseModel):
    best: bool


class PurchaseLink(BaseModel):
    link: str = Field(default='', max_length=4096)


def install_sources(app, access, registry):
    def sources(request, library):
        _, lib = access(request, library, owner=True)
        return registry.get(lib['id']).sources

    def allow_session_import(request):
        # A forwarded request may originate outside the owner's computer.
        return request.url.hostname in ('localhost', '127.0.0.1', '::1') and not any(
            h in request.headers for h in ('forwarded', 'x-forwarded-host', 'x-forwarded-for'))

    def local_import(request):
        if not allow_session_import(request):
            raise UserError('Para conectar tu cuenta, abrí tu propia instalación en localhost desde la computadora del servidor.')

    @app.get('/api/sources')
    def settings(request: Request, library: str | None = None):
        return {**sources(request, library).settings(), 'can_import_sessions': allow_session_import(request)}

    @app.patch('/api/sources')
    def preferences(body: Preference, request: Request, library: str | None = None):
        source = sources(request, library)
        source.set_option('best_quality', body.best)
        return source.settings()

    @app.put('/api/sources/{provider}/cookies')
    def connect(provider: str, body: dict, request: Request, library: str | None = None):
        local_import(request)
        data = body.get('content')
        if not isinstance(data, str) or not data:
            raise UserError('Elegí tu archivo cookies.txt.')
        return sources(request, library).change_session(provider, data)

    @app.delete('/api/sources/{provider}/cookies')
    def disconnect(provider: str, request: Request, library: str | None = None):
        return sources(request, library).change_session(provider)

    @app.put('/api/sources/home-html')
    def import_page(body: dict, request: Request, library: str | None = None):
        return sources(request, library).html(body.get('content'))

    @app.delete('/api/sources/home-html')
    def clear_page(request: Request, library: str | None = None):
        source = sources(request, library)
        source.set_option('home_html', [])
        return source.settings()

    @app.get('/api/sources/qobuz/reference')
    def qobuz_reference(request:Request,id:str='',album:str='',library:str | None=None):
        _,lib=access(request,library)
        src=registry.get(lib['id']).sources
        if album:
            try:
                return {'album':src.purchases.album_preview(catalog_id=album[:120])['id']}
            except UserError:
                return {'album':None}
        with src.store.db() as db:
            row=db.execute('SELECT id FROM qobuz_purchases WHERE id=?',('qb:'+id[:16],)).fetchone()
        return {'track':row[0] if row else None}

    @app.post('/api/sources/add')
    def add_source(body: dict,request: Request,library: str | None = None):
        src=sources(request,library)
        value=body.get('site')
        if not isinstance(value,str) or len(value)>2048:
            raise UserError('Elegí una plataforma o pegá su enlace.')
        return {'source':src.index.add(value)}

    @app.put('/api/sources/{key}/html')
    def provider_html(key:str,body:dict,request: Request,library:str | None=None):
        return sources(request,library).index.import_html(key,body.get('content'))

    @app.delete('/api/sources/{key}/html')
    def remove_html(key:str,request:Request,library:str | None=None):
        src=sources(request,library)
        if key not in src.index.active():
            raise UserError('Fuente desconocida.')
        src.set_option('home_html' if key=='youtube' else 'page:'+key,[])
        return {'ok':True}

    @app.patch('/api/sources/{key}/search')
    def search_toggle(key:str,body:dict,request: Request,library:str | None=None):
        src=sources(request,library)
        if key not in src.index.active() or not isinstance(body.get('enabled'),bool):
            raise UserError('Elegí una fuente de tu biblioteca.')
        with src.store.lock:
            muted=set(src.option('muted_search',[]))
            if body['enabled']:
                muted.discard(key)
            else:
                muted.add(key)
            src.set_option('muted_search',sorted(muted))
        return {'ok':True}

    @app.patch('/api/sources/{key}/options')
    def source_options(key:str, body:dict, request:Request, library:str | None=None):
        src=sources(request,library)
        src.configure(key,body.get('field'),body.get('enabled'),body.get('format'))
        return {'ok':True}

    @app.delete('/api/sources/{key}')
    def delete_source(key:str,body:dict,request:Request,library:str | None=None):
        if body.get('confirm')!=key:
            raise UserError('Confirmá la fuente que querés eliminar.')
        sources(request,library).remove(key)
        return {'ok':True}

    @app.get('/api/home')
    def home(request: Request, library: str | None = None, refresh: bool = False):
        return sources(request, library).home(refresh)

    @app.post('/api/sources/qobuz/purchases')
    def purchases(body: PurchaseLink, request: Request, library: str | None = None):
        if body.link:
            local_import(request)
        return sources(request, library).refresh(body.link)
