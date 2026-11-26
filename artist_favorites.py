"""Private artist bookmarks. Saving an artist never schedules a download."""
import hashlib
import re
import time

from fastapi import Request
from pydantic import BaseModel, Field

from core import ARTIST_ID, UserError


def artist_key(source, name, ident=''):
    identity = ident if source == 'youtube' and ARTIST_ID.fullmatch(ident or '') else ' '.join(name.split()).casefold()
    return hashlib.sha256((source+'\n'+identity).encode()).hexdigest()[:32]


class ArtistFavorites:
    def __init__(self, store):
        self.store = store
        with store.db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS artist_favorites(
                user TEXT NOT NULL, key TEXT NOT NULL, source TEXT NOT NULL, artist_id TEXT NOT NULL,
                name TEXT NOT NULL, cover TEXT NOT NULL, art_source TEXT NOT NULL, created REAL NOT NULL,
                PRIMARY KEY(user,key))''')

    def public(self, row):
        cover = row['cover']
        if row['art_source']:
            cover = self.store.catalog.cover([{'url': row['art_source']}])
        return {'key': row['key'], 'id': row['artist_id'], 'source': row['source'],
                'type': 'artist', 'title': row['name'], 'artist': row['name'], 'cover': cover}

    def listing(self, uid):
        with self.store.db() as db:
            rows = db.execute('SELECT * FROM artist_favorites WHERE user=? ORDER BY created DESC,name', (uid,)).fetchall()
        return {'items': [self.public(row) for row in rows]}

    def save(self, uid, name, source='youtube', ident='', cover=''):
        name = ' '.join(name.split())
        if not name or len(name)>200 or any(ord(c)<32 for c in name):
            raise UserError('Elegí un artista con nombre válido.')
        if source not in self.store.sources.index.active():
            raise UserError('Esta fuente ya no está activa.')
        if source=='youtube' and ident and not ARTIST_ID.fullmatch(ident):
            raise UserError('El identificador del artista no es válido.')
        if source!='youtube':
            ident=''  # Other catalogs currently open by source + name, never arbitrary URLs.
        art_source=''
        if not re.fullmatch(r'/api/covers/[a-f0-9]{64}', cover):
            cover=''
        elif cover:
            with self.store.catalog.lock:
                candidate=self.store.catalog.cover_sources.get(cover.rsplit('/',1)[-1], '')
            if candidate and self.store.catalog.valid_cover(candidate):
                art_source=candidate
        key=artist_key(source,name,ident)
        with self.store.lock, self.store.db() as db:
            if not db.execute('SELECT 1 FROM artist_favorites WHERE user=? AND key=?',(uid,key)).fetchone() and db.execute('SELECT count(*) FROM artist_favorites WHERE user=?',(uid,)).fetchone()[0]>=500:
                raise UserError('Podés guardar hasta 500 artistas. Quitá uno antes de agregar otro.')
            # Upgrade a name-only bookmark after its catalog ID becomes available.
            if ident:
                db.execute('DELETE FROM artist_favorites WHERE user=? AND key=? AND artist_id=?',
                           (uid,artist_key(source,name),''))
            db.execute('''INSERT INTO artist_favorites VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(user,key)
                DO UPDATE SET name=excluded.name,cover=excluded.cover,art_source=excluded.art_source''',
                       (uid,key,source,ident,name,cover,art_source,time.time()))
            row=db.execute('SELECT * FROM artist_favorites WHERE user=? AND key=?',(uid,key)).fetchone()
        return self.public(row)

    def remove(self, uid, key):
        with self.store.lock, self.store.db() as db:
            db.execute('DELETE FROM artist_favorites WHERE user=? AND key=?',(uid,key))
        return {'removed':True}


class ArtistBookmark(BaseModel):
    name: str = Field(min_length=1,max_length=200)
    source: str = Field(default='youtube',max_length=253)
    id: str = Field(default='',max_length=160)
    cover: str = Field(default='',max_length=512)


def install_artist_favorites(app,access,registry):
    def personal(request,library):
        actor,lib=access(request,library)
        store=registry.get(lib['id'])
        with store.lock:
            if not hasattr(store,'artist_favorites'):
                store.artist_favorites=ArtistFavorites(store)
        return actor['id'],store.artist_favorites

    @app.get('/api/listening/artists')
    def listing(request:Request,library:str|None=None):
        uid,service=personal(request,library)
        return service.listing(uid)

    @app.put('/api/listening/artists')
    def save(body:ArtistBookmark,request:Request,library:str|None=None):
        uid,service=personal(request,library)
        return service.save(uid,body.name,body.source,body.id,body.cover)

    @app.delete('/api/listening/artists/{key}')
    def remove(key:str,request:Request,library:str|None=None):
        uid,service=personal(request,library)
        return service.remove(uid,key)
