"""Small account/library API; all permission checks are server-side."""
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from accounts import AccessError, COOKIE, SESSION_SECONDS, decide, propose, proposals


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class Registration(Login):
    display_name: str = Field(default='', max_length=80)


class Member(BaseModel):
    username: str = Field(min_length=3, max_length=32)


class LibrarySettings(BaseModel):
    auto_approve: bool


class KeyName(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class Choice(BaseModel):
    id: str = Field(min_length=11, max_length=11)


class Selection(BaseModel):
    tracks: list[Choice] = Field(min_length=1, max_length=50)
    format: Literal['mp3', 'original'] = 'mp3'


def install_account_routes(app, accounts, registry, catalog, integrations=None):
    router = APIRouter()

    def identity(request, allow_key=False):
        actor = accounts.authenticate(request.cookies.get(COOKIE), request.headers.get('authorization'))
        if actor['kind'] == 'key' and not allow_key:
            raise AccessError(403, 'Esta clave solo permite consultar catálogo y proponer música.')
        return actor

    def access(request, library=None, owner=False, allow_key=False):
        actor = identity(request, allow_key=allow_key)
        return actor, accounts.resolve(actor, library, owner=owner, allow_key=allow_key)

    def me(actor):
        libraries = accounts.libraries(actor['id'])
        return {'user': accounts.user(actor['id']), 'libraries': libraries, 'default_library': next(x['id'] for x in libraries if x['role'] == 'owner')}

    def set_session(request, response, user):
        token = accounts.new_session(user['id'], request.cookies.get(COOKIE))
        response.set_cookie(COOKIE, token, httponly=True, secure=request.url.scheme == 'https', samesite='strict', max_age=SESSION_SECONDS, path='/')
        return me(user)

    @router.get('/api/auth/status')
    def auth_status():
        return {'registration_open': True, 'has_users': accounts.has_users()}

    @router.post('/api/auth/register', status_code=201)
    def register(body: Registration, request: Request, response: Response):
        accounts.throttle(request.client.host if request.client else 'unknown', body.username)
        user = accounts.register(body.username, body.password, body.display_name)
        result = set_session(request, response, user)
        registry.get(result['default_library'])
        return result

    @router.post('/api/auth/login')
    def login(body: Login, request: Request, response: Response):
        accounts.throttle(request.client.host if request.client else 'unknown', body.username)
        user = accounts.login(body.username, body.password)
        return set_session(request, response, user)

    @router.post('/api/auth/logout')
    def logout(request: Request, response: Response):
        identity(request)
        accounts.logout(request.cookies.get(COOKIE))
        response.delete_cookie(COOKIE, path='/')
        return {'ok': True}

    @router.get('/api/auth/me')
    def current_user(request: Request):
        return me(identity(request))

    @router.get('/api/libraries')
    def libraries(request: Request):
        result = me(identity(request))
        return {'items': result['libraries'], 'default_library': result['default_library']}

    @router.patch('/api/libraries/{lid}')
    def settings(lid: str, body: LibrarySettings, request: Request):
        actor, _ = access(request, lid, owner=True)
        accounts.settings(lid, body.auto_approve)
        return next(x for x in accounts.libraries(actor['id']) if x['id'] == lid)

    @router.get('/api/libraries/{lid}/members')
    def members(lid: str, request: Request):
        access(request, lid)
        return accounts.members(lid)

    @router.post('/api/libraries/{lid}/members')
    def add_member(lid: str, body: Member, request: Request):
        access(request, lid, owner=True)
        return accounts.add_member(lid, body.username)

    @router.delete('/api/libraries/{lid}/members/{uid}')
    def remove_member(lid: str, uid: str, request: Request):
        access(request, lid, owner=True)
        return accounts.remove_member(lid, uid)

    @router.get('/api/libraries/{lid}/keys')
    def keys(lid: str, request: Request):
        access(request, lid, owner=True)
        return accounts.keys(lid)

    @router.post('/api/libraries/{lid}/keys', status_code=201)
    def create_key(lid: str, body: KeyName, request: Request):
        access(request, lid, owner=True)
        return accounts.create_key(lid, body.name)

    @router.delete('/api/libraries/{lid}/keys/{kid}')
    def revoke_key(lid: str, kid: str, request: Request):
        access(request, lid, owner=True)
        return accounts.revoke_key(lid, kid)

    @router.post('/api/proposals', status_code=201)
    def submit(body: Selection, request: Request, library: str | None = None):
        actor, lib = access(request, library, allow_key=True)
        tracks = catalog.selected([x.id for x in body.tracks])
        return propose(registry.get(lib['id']), lib, actor, tracks, body.format)

    @router.get('/api/proposals')
    def list_proposals(request: Request, library: str | None = None):
        actor, lib = access(request, library, allow_key=True)
        return proposals(registry.get(lib['id']), lib, actor)

    @router.get('/api/proposals/{ident}')
    def get_proposal(ident: str, request: Request, library: str | None = None):
        actor, lib = access(request, library, allow_key=True)
        return proposals(registry.get(lib['id']), lib, actor, ident)

    @router.post('/api/proposals/{ident}/approve')
    def approve(ident: str, request: Request, library: str | None = None):
        _, lib = access(request, library, owner=True)
        return decide(registry.get(lib['id']), lib, ident, True)

    @router.post('/api/proposals/{ident}/reject')
    def reject(ident: str, request: Request, library: str | None = None):
        _, lib = access(request, library, owner=True)
        return decide(registry.get(lib['id']), lib, ident, False)

    if integrations is not None:
        @router.get('/api/integrations')
        def selected_providers(request: Request, library: str | None = None):
            _, lib = access(request, library, owner=True)
            return integrations.get_settings(lib['id'])

        @router.patch('/api/integrations')
        def selected_save_providers(body: dict, request: Request, library: str | None = None):
            _, lib = access(request, library, owner=True)
            try:
                return integrations.save_settings(lib['id'], body)
            except ValueError as error:
                raise AccessError(400, str(error)) from None

        @router.get('/api/libraries/{lid}/providers')
        def providers(lid: str, request: Request):
            access(request, lid, owner=True)
            return integrations.get_settings(lid)

        @router.put('/api/libraries/{lid}/providers')
        def save_providers(lid: str, body: dict, request: Request):
            access(request, lid, owner=True)
            try:
                return integrations.save_settings(lid, body)
            except ValueError as error:
                raise AccessError(400, str(error)) from None

    app.include_router(router)
    return identity, access
