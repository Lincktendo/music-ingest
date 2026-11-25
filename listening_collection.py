"""Personal listening lists and anonymous-to-other-members discovery signals."""
import json
import random
import re
import threading
import time
from uuid import uuid4
from typing import Literal

from fastapi import Request
from pydantic import BaseModel, Field
from accounts import scope_urls
from core import UserError, VIDEO_ID
from music_home import ATV, album_art
from source_catalog import EXID
from qobuz_store import QID

FAVORITES = 'favorites'
RADIO_SLOTS = threading.BoundedSemaphore(2)
TRACK_FIELDS = ('id', 'title', 'artist', 'album', 'duration', 'duration_seconds', 'cover', 'type', 'artists',
                'album_id', 'album_browse_id', 'album_artist','track','disc','source', 'output_format', 'video_type')


def check_track(ident):
    if not isinstance(ident, str) or not any(rule.fullmatch(ident) for rule in (VIDEO_ID, QID, EXID)):
        raise UserError('Elegí una rola de la biblioteca o de una fuente habilitada.')


def collection_for(store):
    with store.lock:
        if not hasattr(store, 'listening_collection'):
            store.listening_collection = ListeningCollection(store)
        return store.listening_collection


class ListeningCollection:
    def __init__(self, store):
        self.store = store
        self.radio_cache = {}
        self.album_cache = {}
        with store.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS listening_lists(
                    user TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL COLLATE NOCASE,
                    created REAL NOT NULL, PRIMARY KEY(user,id), UNIQUE(user,name));
                CREATE TABLE IF NOT EXISTS listening_entries(
                    user TEXT NOT NULL, list_id TEXT NOT NULL, track TEXT NOT NULL,
                    metadata TEXT NOT NULL, added REAL NOT NULL, PRIMARY KEY(user,list_id,track));
                CREATE INDEX IF NOT EXISTS ix_listening_order ON listening_entries(user,list_id,added);
                CREATE TABLE IF NOT EXISTS listening_history(
                    user TEXT NOT NULL, track TEXT NOT NULL, artist TEXT NOT NULL,
                    last_played REAL NOT NULL, contribute INTEGER NOT NULL, PRIMARY KEY(user,track));
                CREATE INDEX IF NOT EXISTS ix_listening_recent ON listening_history(contribute,last_played);
            ''')

    def lists(self, uid):
        with self.store.db() as db:
            playlists = db.execute('''SELECT l.id,l.name,COUNT(e.track) AS count
                FROM listening_lists l LEFT JOIN listening_entries e ON l.id=e.list_id AND l.user=e.user
                WHERE l.user=? GROUP BY l.id,l.name ORDER BY l.created,l.id''', (uid,)).fetchall()
            favorites = db.execute('SELECT track FROM listening_entries WHERE user=? AND list_id=? ORDER BY added DESC',
                                   (uid, FAVORITES)).fetchall()
        return {'playlists': [dict(r) for r in playlists], 'favorites': [r[0] for r in favorites]}

    def create(self, uid, name):
        name = ' '.join(name.split())
        if not 1 <= len(name) <= 100:
            raise UserError('El nombre de la playlist debe tener entre 1 y 100 caracteres.')
        with self.store.lock, self.store.db() as db:
            existing = db.execute('SELECT id FROM listening_lists WHERE user=? AND name=?', (uid, name)).fetchone()
            if existing:
                return {'id': existing[0], 'name': name}
            ident = uuid4().hex
            db.execute('INSERT INTO listening_lists VALUES(?,?,?,?)', (uid, ident, name, time.time()))
            return {'id': ident, 'name': name}

    @staticmethod
    def check_list(db, uid, key):
        if key != FAVORITES and not db.execute('SELECT 1 FROM listening_lists WHERE user=? AND id=?',
                                               (uid, key)).fetchone():
            raise UserError('Esa playlist no está en tu colección.')

    def remove_list(self, uid, key):
        if key == FAVORITES:
            raise UserError('Podés quitar canciones individuales de Favoritas.')
        with self.store.lock, self.store.db() as db:
            self.check_list(db, uid, key)
            db.execute('DELETE FROM listening_entries WHERE user=? AND list_id=?', (uid, key))
            db.execute('DELETE FROM listening_lists WHERE user=? AND id=?', (uid, key))

    def local_files(self, ids):
        if not ids:
            return {}
        # File paths are checked against this library's own root by public_file().
        marks = ','.join('?' for _ in ids)
        sql = f"""SELECT * FROM files WHERE source_id IN ({marks}) OR json_extract(metadata,'$.youtube_id') IN ({marks})
                  ORDER BY format='mp3' DESC"""
        with self.store.db() as db:
            rows = db.execute(sql, [*ids, *ids]).fetchall()
        files = {}
        for row in rows:
            item = self.store.public_file(row)
            if item:
                files.setdefault(item['source_id'], item)
                if item.get('youtube_id'):
                    files.setdefault(item['youtube_id'], item)
        return files

    def verified_track(self, ident):
        check_track(ident)
        file = self.local_files([ident]).get(ident)
        if file:
            return {**file, 'id': ident}
        try:
            track = self.store.sources.selected([ident])[0]
        except UserError:
            if not VIDEO_ID.fullmatch(ident) or 'youtube' not in self.store.sources.index.active():
                raise
            try:
                track = self.store.catalog.preview(ident)['tracks'][0]
            except Exception:
                raise UserError('No pude confirmar la rola en YouTube Music. Volvé a abrirla e intentá de nuevo.') from None
        choices = self.store.sources.describe([track])
        if not choices:
            raise UserError('Esa pista no está disponible en tus fuentes.')
        return choices[0]

    def snapshot(self, track):
        item = {k: track[k] for k in TRACK_FIELDS if k in track}
        item['type'] = 'song'
        cover = item.get('cover', '')
        if re.fullmatch('/api/covers/[a-f0-9]{64}', cover):
            catalog = self.store.catalog
            with catalog.lock:
                url = catalog.cover_sources.get(cover.rsplit('/', 1)[-1])
            if url and catalog.valid_cover(url):
                item['art_source'] = url
        return item

    def set_entry(self, uid, key, ident, enabled):
        check_track(ident)
        with self.store.db() as db:
            self.check_list(db, uid, key)
            if enabled and db.execute('SELECT 1 FROM listening_entries WHERE user=? AND list_id=? AND track=?',
                                      (uid, key, ident)).fetchone():
                return
        meta = json.dumps(self.snapshot(self.verified_track(ident)), ensure_ascii=False) if enabled else ''
        with self.store.lock, self.store.db() as db:
            self.check_list(db, uid, key)
            if enabled:
                db.execute('INSERT OR IGNORE INTO listening_entries VALUES(?,?,?,?,?)', (uid, key, ident, meta, time.time()))
            else:
                db.execute('DELETE FROM listening_entries WHERE user=? AND list_id=? AND track=?', (uid, key, ident))

    def page(self, uid, key, offset, limit=50, shuffle=False, exclude=(), after=None):
        with self.store.db() as db:
            self.check_list(db, uid, key)
            order = 'added DESC,track' if key == FAVORITES else 'added,track'
            where='user=? AND list_id=?'
            params=[uid,key]
            if after:
                check_track(after)
                cursor = db.execute('SELECT added FROM listening_entries WHERE user=? AND list_id=? AND track=?',
                                    (uid,key,after)).fetchone()
                if cursor:
                    before = '>' if key==FAVORITES else '<'
                    offset = db.execute(f'SELECT count(*) FROM listening_entries WHERE user=? AND list_id=? AND '
                                        f'(added {before} ? OR (added=? AND track<=?))',
                                        (uid,key,cursor[0],cursor[0],after)).fetchone()[0]
            if exclude:
                where+=' AND track NOT IN ('+','.join('?' for _ in exclude)+')'
                params.extend(exclude)
            if shuffle:
                order='random()'
            rows = db.execute(f'SELECT track,metadata FROM listening_entries WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?',
                              (*params,limit+1,offset)).fetchall()
            ids = [r[0] for r in rows[:limit]]
            marks = ','.join('?' for _ in ids)
            art = dict(db.execute(f'SELECT id,cover FROM custom_art WHERE id IN ({marks})',ids)) if ids else {}
        files = self.local_files(ids)
        items = []
        for ident, meta in rows[:limit]:
            item = json.loads(meta)
            art_source = item.pop('art_source', '')
            if art_source:
                item['cover'] = self.store.catalog.cover([{'url': art_source}])
            if ident in art:
                item['cover'] = art[ident]
            file = files.get(ident)
            if file:
                item.update(file, id=ident, type='song')
            items.append(item)
        return {'items': items, 'next_offset': offset+limit if len(rows)>limit else None}

    def played(self, uid, ident, contributes):
        track = self.verified_track(ident)
        artist = track.get('artist','').strip()
        if not artist:
            return
        now=time.time()
        with self.store.lock, self.store.db() as db:
            db.execute('''INSERT INTO listening_history VALUES(?,?,?,?,?) ON CONFLICT(user,track)
                       DO UPDATE SET artist=excluded.artist,last_played=excluded.last_played,contribute=excluded.contribute
                       WHERE listening_history.last_played<excluded.last_played-10''', (uid, ident, artist, now, int(contributes)))
            db.execute('''DELETE FROM listening_history WHERE user=? AND track NOT IN
                       (SELECT track FROM listening_history WHERE user=? ORDER BY last_played DESC LIMIT 250)''', (uid,uid))

    def recent_artists(self):
        with self.store.db() as db:
            return [r[0] for r in db.execute('SELECT artist FROM listening_history WHERE contribute=1 ORDER BY last_played DESC LIMIT 120')]

    def station(self, seed):
        if not VIDEO_ID.fullmatch(seed or '') or 'youtube' not in self.store.sources.index.active():
            return []
        now=time.monotonic()
        with self.store.lock:
            entry=self.radio_cache.get(seed)
            if entry and entry[0]>now:
                return entry[1]
        if not RADIO_SLOTS.acquire(False):
            return []
        client=None
        try:
            client=self.store.catalog.suggest_factory()
            result=client.get_watch_playlist(videoId=seed,radio=True,limit=26)
            songs=[]
            for row in result.get('tracks',[])[:40]:
                if row.get('videoType')!=ATV or row.get('isAvailable') is False:
                    continue
                thumbs=row.get('thumbnail') or row.get('thumbnails') or []
                square=[{**t,'url':uri} for t in thumbs if isinstance(t,dict) and (uri:=album_art(t.get('url','')))]
                if square:
                    item=self.store.catalog.normalize({**row,'resultType':'song','thumbnails':square})
                    if item:
                        songs.append(item)
            self.store.catalog.remember(songs)
            with self.store.lock:
                self.radio_cache={k:v for k,v in self.radio_cache.items() if v[0]>now}
                if len(self.radio_cache)>=32:
                    self.radio_cache.pop(next(iter(self.radio_cache)))
                self.radio_cache[seed]=(now+(300 if songs else 40),songs)
            return songs
        except Exception:
            return []
        finally:
            if client is not None and getattr(client,'_session',None):
                client._session.close()
            RADIO_SLOTS.release()

    def dj_candidates(self, uid, list_id, criterion):
        # Read only a bounded sample; a library may contain tens of thousands of tracks.
        if list_id or criterion == 'favorites':
            return self.page(uid,list_id or FAVORITES,0,120,shuffle=True)['items']
        values = {}
        with self.store.db() as db:
            files = db.execute('SELECT * FROM files ORDER BY random() LIMIT 120').fetchall()
            personal = [] if criterion == 'library' else db.execute(
                'SELECT metadata FROM listening_entries WHERE user=? ORDER BY added DESC LIMIT 120',(uid,)).fetchall()
        for row in files:
            item = self.store.public_file(row)
            if item:
                values[item['source_id']] = {**item,'id':item['source_id'],'type':'song'}
        active = set(self.store.sources.index.active())
        for row in personal:
            item=json.loads(row[0])
            art_source=item.pop('art_source','')
            if art_source:
                item['cover']=self.store.catalog.cover([{'url':art_source}])
            if item.get('source','youtube') in active:
                values.setdefault(item['id'],item)
        return list(values.values())

    @staticmethod
    def album_key(track):
        if track.get('album_id'):
            return (track.get('source','youtube'),str(track['album_id']))
        return (str(track.get('album_artist') or track.get('artist') or '').casefold(),
                str(track.get('album') or '').casefold())

    def album_order(self, candidates, limit, skip, anchor, allow_online, eligible=None):
        groups={}
        for row in candidates:
            key=self.album_key(row)
            if key[1]:
                groups.setdefault(key,[]).append(row)
        keys=list(groups)
        random.shuffle(keys)
        if anchor and self.album_key(anchor) in groups:
            current=self.album_key(anchor)
            keys.remove(current)
            keys.insert(0,current)
        selected=[]
        online_budget=1
        for key in keys:
            group=groups[key]
            first=group[0]
            album_id=first.get('album_id') or ''
            if allow_online and online_budget and album_id and not first.get('job_id'):
                tracks=self.album_tracks(first,album_id)
                online_budget-=1
                if tracks:
                    group=tracks
            def track_order(row):
                def number(field):
                    digits=str(row.get(field) or '').split('/',1)[0]
                    return int(digits) if digits.isdigit() else 0
                return number('disc'),number('track')
            group=sorted(group,key=track_order)
            if anchor and key==self.album_key(anchor):
                pos=next((i for i,t in enumerate(group) if t['id']==anchor['id']),None)
                if pos is not None:
                    group=group[pos+1:]
            for row in group:
                if row['id'] in skip or row.get('youtube_id') in skip or (eligible is not None and row['id'] not in eligible):
                    continue
                selected.append(row)
                skip.add(row['id'])
                if len(selected)>=limit:
                    return selected
        return selected

    def album_tracks(self, first, album_id):
        from core import ALBUM_ID
        key=(first.get('source','youtube'),str(album_id))
        now=time.monotonic()
        with self.store.lock:
            hit=self.album_cache.get(key)
            if hit and hit[0]>now:
                return self.store.sources.describe(hit[1])
        if not RADIO_SLOTS.acquire(False):
            return []
        try:
            if key[0]=='youtube' and ALBUM_ID.fullmatch(key[1]):
                tracks=self.store.catalog.preview(key[1],'album')['tracks']
            elif key[0]=='qobuz':
                tracks=self.store.sources.purchases.album_preview(catalog_id=key[1])['tracks']
            else:
                return []
            with self.store.lock:
                if len(self.album_cache)>=16:
                    self.album_cache.pop(next(iter(self.album_cache)))
                self.album_cache[key]=(now+300,tracks)
            return self.store.sources.describe(tracks)
        except Exception:
            return []
        finally:
            RADIO_SLOTS.release()

    def next_tracks(self, uid, seed, exclude, limit, criterion='random', group='songs', strict=False,
                    list_id=None, tail=None):
        check_track(seed)
        if tail:
            check_track(tail)
        skip={seed,*exclude}
        candidates=self.dj_candidates(uid,list_id,criterion)
        opened=list_id is None and criterion not in ('favorites','library')
        similar=criterion=='similar' or strict
        available={t['id']:t for t in candidates}
        source_artist=''
        if similar:
            try:
                source_artist=self.verified_track(seed).get('artist','').split(';')[0].strip().casefold()
            except UserError:
                pass
        hidden=set(self.store.sources.option('hidden_home',[]))
        if similar or (opened and len(set(available)-skip)<limit):
            station={row['id']:row for row in self.store.sources.describe(self.station(seed)) if row['id'] not in hidden}
        else:
            station={}
        preferred={}
        if similar:
            for key,row in available.items():
                artists={a.strip().casefold() for a in row.get('artist','').split(';')}
                if key in station or (source_artist and source_artist in artists):
                    preferred[key]=row
        if opened:
            preferred.update(station)
        restrict=strict and similar
        pool=preferred if restrict else {**available,**preferred}
        if group=='albums':
            anchor=pool.get(tail) if tail else None
            if tail and not anchor and opened:
                try:
                    anchor=self.verified_track(tail)
                except UserError:
                    pass
                if anchor:
                    pool[tail]=anchor
            if similar and preferred and not restrict:
                order=self.album_order(list(preferred.values()),limit,skip,anchor,opened)
                if len(order)>=limit:
                    return order
                return order+self.album_order(list(pool.values()),limit-len(order),skip,anchor,opened)
            return self.album_order(list(pool.values()),limit,skip,anchor,opened, set(pool) if not opened else None)
        take=lambda rows:[r for k,r in rows.items() if k not in skip and r.get('youtube_id') not in skip]
        primary=take(preferred) if similar else []
        random.shuffle(primary)
        rr=primary[:limit]
        if len(rr)<limit and not restrict:
            taken={t['id'] for t in rr}
            extra=[t for t in take(pool) if t['id'] not in taken]
            rr.extend(random.sample(extra,min(len(extra),limit-len(rr))))
        return rr


class ListName(BaseModel):
    name: str = Field(min_length=1,max_length=100)


class TrackRequest(BaseModel):
    id: str = Field(min_length=1,max_length=120)


class RadioRequest(TrackRequest):
    exclude: list[str] = Field(default_factory=list,max_length=100)
    limit: int = Field(default=10,ge=1,le=10)
    list_id: str | None = Field(default=None,max_length=40)
    criterion: Literal['random','similar','favorites','library'] = 'random'
    group: Literal['songs','albums'] = 'songs'
    strict: bool = False
    tail: str | None = Field(default=None,max_length=120)


def install_collection(app,access,registry):
    def personal(request,library):
        actor,lib=access(request,library)
        return actor['id'],lib,collection_for(registry.get(lib['id']))

    @app.get('/api/listening/lists')
    def lists(request:Request,library:str|None=None):
        uid,_,collection=personal(request,library)
        return collection.lists(uid)

    @app.post('/api/listening/lists',status_code=201)
    def create(body:ListName,request:Request,library:str|None=None):
        uid,_,collection=personal(request,library)
        return collection.create(uid,body.name)

    @app.get('/api/listening/lists/{key}')
    def tracks(key:str,request:Request,offset:int=0,limit:int=50,after:str|None=None,library:str|None=None):
        uid,lib,collection=personal(request,library)
        if offset<0 or not 1<=limit<=50:
            raise UserError('Página no válida.')
        return scope_urls(collection.page(uid,key,offset,limit,after=after),lib['id'])

    @app.delete('/api/listening/lists/{key}')
    def remove(key:str,request:Request,library:str|None=None):
        uid,_,collection=personal(request,library)
        collection.remove_list(uid,key)
        return {'removed':True}

    @app.put('/api/listening/lists/{key}/{ident}')
    def add_track(key:str,ident:str,request:Request,library:str|None=None):
        uid,_,collection=personal(request,library)
        collection.set_entry(uid,key,ident,True)
        return {'saved':True}

    @app.delete('/api/listening/lists/{key}/{ident}')
    def remove_track(key:str,ident:str,request:Request,library:str|None=None):
        uid,_,collection=personal(request,library)
        collection.set_entry(uid,key,ident,False)
        return {'removed':True}

    @app.post('/api/listening/played')
    def played(body:TrackRequest,request:Request,library:str|None=None):
        uid,lib,collection=personal(request,library)
        collection.played(uid,body.id,lib['role']=='owner')
        return {'saved':True}

    @app.post('/api/listening/next')
    def radio(body:RadioRequest,request:Request,library:str|None=None):
        uid,lib,collection=personal(request,library)
        items=collection.next_tracks(uid,body.id,body.exclude,body.limit,body.criterion,
                                     body.group,body.strict,body.list_id,body.tail)
        return scope_urls({'items':items},lib['id'])
