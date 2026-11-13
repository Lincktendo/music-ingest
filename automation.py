"""Persistent playlist imports and artist release watching, one bounded scheduler."""
import json
import re
import threading
import time
import uuid
from urllib.parse import urlsplit, parse_qs

from fastapi import Request
from pydantic import BaseModel, Field
from typing import Literal
from core import UserError, VIDEO_ID, ARTIST_ID, ALBUM_ID, bounded_text
from storage import Folders

PLAYLIST_ID = re.compile(r'(?:PL|OLAK5uy_|RDCLAK|UU)[A-Za-z0-9_-]{8,190}\Z')
INTERVALS = (60,300,900,3600,21600,43200,86400,604800)
MAX_TRACKS = 5000


def playlist_id(url):
    try:
        parsed=urlsplit(url.strip())
        ident=parse_qs(parsed.query).get('list',[''])[0]
        if parsed.scheme!='https' or parsed.hostname not in ('music.youtube.com','www.youtube.com','youtube.com') or parsed.username or parsed.password or parsed.port not in (None,443) or parsed.path not in ('/playlist','/watch') or not PLAYLIST_ID.fullmatch(ident):
            raise ValueError()
    except (ValueError,AttributeError):
        raise UserError('Pegá el enlace de una playlist pública o no listada de YouTube Music. No se admiten mixes personales ni listas privadas.') from None
    return ident


class Following:
    def __init__(self, registry):
        self.registry=registry
        self.stop_event=threading.Event()
        self.thread=None
        self.scan_lock=threading.Lock()
        self.initialized=set()
        self.lock=threading.RLock()

    def setup(self, store):
        with self.lock:
            if store in self.initialized:return
            with store.db() as db:
                db.executescript('''
                CREATE TABLE IF NOT EXISTS follows(id TEXT PRIMARY KEY,kind TEXT NOT NULL,source_id TEXT NOT NULL,title TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1,initialized INTEGER NOT NULL DEFAULT 0,last_check REAL,next_check REAL NOT NULL DEFAULT 0,error TEXT NOT NULL DEFAULT '',UNIQUE(kind,source_id));
                CREATE TABLE IF NOT EXISTS releases(follow_id TEXT NOT NULL,release_id TEXT NOT NULL,PRIMARY KEY(follow_id,release_id));
                CREATE TABLE IF NOT EXISTS auto_tracks(track_id TEXT PRIMARY KEY,payload TEXT NOT NULL,job_id TEXT,added_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS follow_tracks(follow_id TEXT NOT NULL,track_id TEXT NOT NULL,PRIMARY KEY(follow_id,track_id));
                ''')
                if 'follow_updates' not in {column[1] for column in db.execute('PRAGMA table_info(follows)')}:
                    # Existing playlists continue to update exactly as before.
                    db.execute('ALTER TABLE follows ADD COLUMN follow_updates INTEGER NOT NULL DEFAULT 1')
                columns={column[1] for column in db.execute('PRAGMA table_info(follows)')}
                if 'include_existing' not in columns:
                    db.execute('ALTER TABLE follows ADD COLUMN include_existing INTEGER NOT NULL DEFAULT 0')
                if 'existing_imported' not in columns:
                    db.execute('ALTER TABLE follows ADD COLUMN existing_imported INTEGER NOT NULL DEFAULT 0')
                # Store marks work interrupted after a restart. Only automatically
                # discovered work resumes here; manual downloads keep their retry UI.
                db.execute("UPDATE jobs SET status='queued',error='' WHERE status='interrupted' AND id IN (SELECT job_id FROM auto_tracks WHERE job_id IS NOT NULL)")
            self.initialized.add(store)
            store.event.set()

    def interval(self, store):
        with store.db() as db:
            row=db.execute("SELECT value FROM library_options WHERE key='check_interval'").fetchone()
        return int(row[0]) if row else 86400

    def listing(self, store):
        self.setup(store)
        with store.db() as db:
            rows=db.execute('SELECT * FROM follows ORDER BY rowid DESC').fetchall()
            pending=db.execute('SELECT count(*) FROM auto_tracks a WHERE job_id IS NULL AND EXISTS(SELECT 1 FROM follow_tracks t JOIN follows f ON f.id=t.follow_id WHERE t.track_id=a.track_id AND f.enabled=1)').fetchone()[0]
            counts={r['follow_id']:dict(r) for r in db.execute("SELECT t.follow_id,count(*) AS track_count,sum(CASE WHEN a.job_id IS NULL THEN 1 ELSE 0 END) AS pending_tracks,sum(CASE WHEN j.status IN ('queued','running','interrupted') THEN 1 ELSE 0 END) AS active_tracks,sum(CASE WHEN j.status='failed' THEN 1 ELSE 0 END) AS failed_tracks FROM follow_tracks t JOIN auto_tracks a ON a.track_id=t.track_id LEFT JOIN jobs j ON j.id=a.job_id GROUP BY t.follow_id")}
        items=[]
        for row in rows:
            item=dict(row);item['follow_updates']=bool(item['follow_updates'])
            item['include_existing']=bool(item['include_existing'])
            item['existing_imported']=bool(item['existing_imported'])
            tally=counts.get(item['id'],{})
            item.update({key:tally.get(key,0) for key in ('track_count','pending_tracks','active_tracks','failed_tracks')})
            if not item['enabled']:item['state']='paused'
            elif item['error']:item['state']='error'
            elif not item['initialized'] or (item['include_existing'] and not item['existing_imported']):item['state']='pending'
            elif item['follow_updates']:item['state']='following'
            elif item['pending_tracks'] or item['active_tracks']:item['state']='importing'
            elif item['failed_tracks']:item['state']='needs_retry'
            else:item['state']='imported'
            if item['initialized'] and not item['follow_updates']:item['next_check']=None
            items.append(item)
        return {'items':items,'interval_seconds':self.interval(store),'pending_tracks':pending,'max_playlist_tracks':MAX_TRACKS}

    def add(self, store, kind, source, follow_updates=True, include_existing=False):
        self.setup(store)
        if kind=='playlist':
            if include_existing:raise UserError('La playlist ya incluye sus canciones actuales. Esta opción es solo para artistas.')
            ident=playlist_id(source);title='Tu playlist · preparando primera revisión'
        else:
            if not follow_updates:raise UserError('Los artistas favoritos se mantienen actualizados. Para una descarga única, elegí un álbum o una canción.')
            ident=source
            if not ARTIST_ID.fullmatch(ident):raise UserError('Buscá el artista y agregalo desde su ficha.')
            title='Artista favorito · preparando primera revisión'
        with store.lock,store.db() as db:
            existing=db.execute('SELECT id,follow_updates,include_existing,existing_imported FROM follows WHERE kind=? AND source_id=?',(kind,ident)).fetchone()
            if existing:
                upgraded=kind=='artist' and include_existing and not existing['include_existing']
                if upgraded:
                    # Keep release history and queued/downloaded tracks. A separate
                    # flag asks the next scan to include the known catalogue once.
                    db.execute("UPDATE follows SET include_existing=1,next_check=0,error='' WHERE id=?",(existing['id'],))
                return {'id':existing['id'],'already_following':True,'follow_updates':bool(existing['follow_updates']),
                        'include_existing':bool(existing['include_existing'] or upgraded),'existing_imported':bool(existing['existing_imported']),
                        'catalogue_queued':bool(upgraded)}
            if db.execute('SELECT count(*) FROM follows').fetchone()[0]>=30:raise UserError('Esta biblioteca admite hasta 30 playlists y artistas seguidos.')
            follow=uuid.uuid4().hex
            db.execute('INSERT INTO follows(id,kind,source_id,title,follow_updates,include_existing) VALUES(?,?,?,?,?,?)',(follow,kind,ident,title,int(follow_updates),int(include_existing)))
        return {'id':follow,'already_following':False,'follow_updates':bool(follow_updates),
                'include_existing':bool(include_existing),'existing_imported':False,'catalogue_queued':bool(include_existing)}

    def update(self, store, ident, *, enabled=None, remove=False, check=False):
        self.setup(store)
        with store.lock,store.db() as db:
            row=db.execute('SELECT * FROM follows WHERE id=?',(ident,)).fetchone()
            if not row:raise UserError('Este seguimiento ya no existe.')
            if remove:
                db.execute('DELETE FROM follows WHERE id=?',(ident,))
                db.execute('DELETE FROM follow_tracks WHERE follow_id=?',(ident,))
                db.execute('DELETE FROM releases WHERE follow_id=?',(ident,))
            elif check:
                if row['initialized'] and not row['follow_updates']:raise UserError('Esta playlist se importó una sola vez. Sus descargas siguen en la cola; no volveremos a buscar canciones nuevas.')
                if not row['enabled']:raise UserError('Reanudá el seguimiento para revisarlo.')
                if row['last_check'] and row['last_check']>time.time()-60:raise UserError('Ya se revisó hace un momento. Esperá un minuto entre revisiones.')
                db.execute('UPDATE follows SET next_check=0 WHERE id=?',(ident,))
            else:
                due=max(time.time(),(row['last_check'] or 0)+60)
                db.execute('UPDATE follows SET enabled=?,next_check=? WHERE id=?',(int(enabled),due,ident))
        return {'ok':True}

    def set_interval(self, store, seconds):
        self.setup(store)
        if seconds not in INTERVALS:raise UserError('Elegí una frecuencia de la lista.')
        with store.lock,store.db() as db:
            db.execute("INSERT OR REPLACE INTO library_options VALUES('check_interval',?)",(str(seconds),))
            db.execute('UPDATE follows SET next_check=CASE WHEN last_check IS NULL THEN 0 ELSE last_check+? END WHERE follow_updates=1 OR initialized=0',(seconds,))
        return self.listing(store)

    def tracks(self, store, rows, album='', artist='', cover=''):
        found={}
        for index,row in enumerate(rows):
            ident=row.get('videoId')
            if not VIDEO_ID.fullmatch(ident or '') or row.get('isAvailable') is False:continue
            duration=row.get('duration_seconds')
            if row.get('isLive') or (isinstance(duration,(int,float)) and duration>3600):continue
            info=row.get('album') if isinstance(row.get('album'),dict) else {}
            found.setdefault(ident,{'id':ident,'title':bounded_text(row.get('title')) or 'Sin título',
                'artist':store.catalog.artists(row.get('artists')) or artist or 'Artista',
                'album':bounded_text(info.get('name')) or album,'cover':store.catalog.cover(row.get('thumbnails')) or cover,
                'duration':bounded_text(row.get('duration'),20),'track':index+1})
        return list(found.values())

    def fetch(self, store, row):
        api=store.catalog.factory()
        session=getattr(api,'_session',None)
        if session is not None:
            request=session.request
            deadline=time.monotonic()+180
            def bounded_request(*args,**kwargs):
                remaining=deadline-time.monotonic()
                if remaining<=0 or self.stop_event.is_set():
                    raise UserError('La revisión tardó demasiado. Volveremos a intentarlo automáticamente.')
                kwargs['timeout']=min(30,remaining)
                return request(*args,**kwargs)
            session.request=bounded_request
        try:
            if row['kind']=='playlist':
                raw=api.get_playlist(row['source_id'],limit=MAX_TRACKS+1)
                rows=raw.get('tracks')
                if not isinstance(rows,list) or not raw.get('title'):raise UserError('No pudimos abrir esa playlist. Comprobá que sea pública o no listada y que el enlace siga activo.')
                count=raw.get('trackCount')
                if len(rows)>MAX_TRACKS or (isinstance(count,int) and count>MAX_TRACKS):raise UserError('Esta versión admite playlists de hasta 5.000 canciones. Dividí esa lista en varias.')
                return bounded_text(raw['title']),self.tracks(store,rows),[]
            raw=api.get_artist(row['source_id'])
            title=bounded_text(raw.get('name'))
            if not title:raise UserError('No pudimos encontrar el catálogo de este artista.')
            releases={}
            for section in ('albums','singles'):
                group=raw.get(section) or {}
                rows=group.get('results',[])
                if group.get('browseId') and group.get('params'):
                    rows=api.get_artist_albums(group['browseId'],group['params'],limit=1001,order='Recency')
                if len(rows)>1000:raise UserError('El catálogo de este artista supera el límite de 1.000 lanzamientos por sección.')
                for release in rows:
                    if ALBUM_ID.fullmatch(release.get('browseId','')):releases[release['browseId']]=release
            with store.db() as db:
                known={r[0] for r in db.execute('SELECT release_id FROM releases WHERE follow_id=?',(row['id'],))}
            tracks={}
            import_existing=row.get('include_existing',False) and not row.get('existing_imported',False)
            if row['initialized'] or import_existing:
                targets=list(releases) if import_existing else [ident for ident in releases if ident not in known]
                for ident in targets:
                    if self.stop_event.is_set():raise UserError('La revisión se reanudará al encender el servidor.')
                    album=api.get_album(ident)
                    album_tracks=album.get('tracks')
                    if not isinstance(album_tracks,list):raise UserError('Un lanzamiento no está disponible; volveremos a revisar sin marcarlo como descargado.')
                    for track in self.tracks(store,album_tracks,bounded_text(album.get('title')),title,store.catalog.cover(album.get('thumbnails'))):
                        tracks.setdefault(track['id'],track)
                    if len(tracks)>MAX_TRACKS:raise UserError('Este catálogo supera las 5.000 canciones por revisión. Elegí los álbumes que querés importar desde la búsqueda.')
            return title,list(tracks.values()),list(releases)
        finally:
            session=getattr(api,'_session',None)
            if session is not None:session.close()

    def scan(self, store, row):
        now=time.time()
        with store.lock,store.db() as db:
            live=db.execute('SELECT * FROM follows WHERE id=? AND enabled=1',(row['id'],)).fetchone()
            if not live or live['next_check']>now:return
            if live['initialized'] and not live['follow_updates']:return
            row=dict(live)
            db.execute("UPDATE follows SET last_check=?,next_check=?,error='' WHERE id=?",(now,now+self.interval(store),row['id']))
        try:
            title,tracks,releases=self.fetch(store,row)
            with store.lock,store.db() as db:
                db.execute('BEGIN IMMEDIATE')
                live=db.execute('SELECT * FROM follows WHERE id=? AND enabled=1',(row['id'],)).fetchone()
                if not live:return
                for track in tracks:
                    db.execute('INSERT OR IGNORE INTO auto_tracks VALUES(?,?,NULL,?)',(track['id'],json.dumps(track,ensure_ascii=False),now))
                    db.execute('INSERT OR IGNORE INTO follow_tracks VALUES(?,?)',(row['id'],track['id']))
                db.executemany('INSERT OR IGNORE INTO releases VALUES(?,?)',[(row['id'],r) for r in releases])
                # Do not mark a newly requested backfill complete if this fetch
                # started before the user checked include_existing.
                imported=bool(row['kind']=='artist' and row['include_existing'])
                db.execute("UPDATE follows SET title=?,initialized=1,error='',existing_imported=CASE WHEN ? THEN 1 ELSE existing_imported END WHERE id=?",(title,imported,row['id']))
        except Exception as error:
            message=str(error) if isinstance(error,UserError) else 'YouTube Music no pudo responder. Volveremos a revisar automáticamente; tus archivos siguen intactos.'
            with store.db() as db:db.execute('UPDATE follows SET error=? WHERE id=?',(message[:500],row['id']))

    def drain(self, store):
        # Discovery is persisted separately from the bounded download queue. A full
        # queue or restart never loses the rest of a large playlist.
        with store.lock,store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            active=db.execute("SELECT id,payload FROM jobs WHERE status IN ('queued','running')").fetchall()
            if len(active)>=10:return
            rows=db.execute('SELECT a.* FROM auto_tracks a WHERE job_id IS NULL AND EXISTS(SELECT 1 FROM follow_tracks t JOIN follows f ON f.id=t.follow_id WHERE t.track_id=a.track_id AND f.enabled=1) ORDER BY added_at,track_id LIMIT 25').fetchall()
            if not rows:return
            busy={t['id']:j['id'] for j in active for t in json.loads(j['payload'])['tracks'] if json.loads(j['payload'])['format']=='mp3'}
            batch=[]
            for item in rows:
                existing=db.execute("SELECT * FROM files WHERE source_id=? AND format='mp3'",(item['track_id'],)).fetchone()
                job=busy.get(item['track_id']) or (existing['job_id'] if existing and store.public_file(existing) else None)
                if job:db.execute('UPDATE auto_tracks SET job_id=? WHERE track_id=?',(job,item['track_id']))
                else:batch.append(json.loads(item['payload']))
            if batch:
                for track in batch[:10-len(active)]:
                    ident=uuid.uuid4().hex
                    db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?)',(ident,'queued',json.dumps({'tracks':[track],'format':'mp3'},ensure_ascii=False),0,'',time.time()))
                    db.execute('UPDATE auto_tracks SET job_id=? WHERE track_id=?',(ident,track['id']))
        store.event.set()

    def tick(self):
        if not self.scan_lock.acquire(blocking=False):return
        try:
            with self.registry.accounts.db() as db:ids=[r[0] for r in db.execute('SELECT id FROM libraries')]
            for lid in ids:
                if self.stop_event.is_set():return
                try:
                    store=self.registry.get(lid);self.setup(store)
                    with store.db() as db:rows=db.execute('SELECT * FROM follows WHERE enabled=1 AND (follow_updates=1 OR initialized=0) AND next_check<=? ORDER BY next_check LIMIT 1',(time.time(),)).fetchall()
                    for row in rows:self.scan(store,dict(row))
                    self.drain(store)
                except Exception:
                    continue  # A broken library cannot starve other libraries.
        finally:self.scan_lock.release()

    def start(self):
        if self.thread and self.thread.is_alive():return
        self.stop_event.clear()
        def loop():
            while not self.stop_event.is_set():
                try:self.tick()
                except Exception:pass  # One unavailable library does not terminate scheduling.
                self.stop_event.wait(5)
        self.thread=threading.Thread(target=loop,name='music-ingest-following',daemon=True);self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=5)


class Source(BaseModel):
    kind:Literal['playlist','artist']
    source:str=Field(min_length=3,max_length=2048)
    follow_updates:bool=True
    include_existing:bool=False
class Enabled(BaseModel):
    enabled:bool
class Interval(BaseModel):
    seconds:int=Field(ge=60,le=604800)
class FolderSelection(BaseModel):
    path:str=Field(default='',max_length=600)
class FolderCreate(FolderSelection):
    name:str=Field(min_length=1,max_length=80)


def install(app,access,registry,following):
    def owned(request,library):
        _,lib=access(request,library,owner=True)
        return registry.get(lib['id'])
    @app.get('/api/following')
    def listing(request:Request,library:str|None=None):return following.listing(owned(request,library))
    @app.post('/api/following',status_code=201)
    def add(body:Source,request:Request,library:str|None=None):return following.add(owned(request,library),body.kind,body.source,body.follow_updates,body.include_existing)
    @app.patch('/api/following/settings')
    def settings(body:Interval,request:Request,library:str|None=None):return following.set_interval(owned(request,library),body.seconds)
    @app.patch('/api/following/{ident}')
    def enabled(ident:str,body:Enabled,request:Request,library:str|None=None):return following.update(owned(request,library),ident,enabled=body.enabled)
    @app.post('/api/following/{ident}/check')
    def check(ident:str,request:Request,library:str|None=None):return following.update(owned(request,library),ident,check=True)
    @app.delete('/api/following/{ident}')
    def remove(ident:str,request:Request,library:str|None=None):return following.update(owned(request,library),ident,remove=True)
    def folders(request,library,action,*args):
        try:return getattr(Folders(owned(request,library)),action)(*args)
        except (ValueError,OSError) as error:
            raise UserError(str(error) if isinstance(error,ValueError) else 'No pudimos abrir esa carpeta. Comprobá el montaje y los permisos de música.') from None
    @app.get('/api/folders')
    def browse(request:Request,path:str='',library:str|None=None):return folders(request,library,'browse',path)
    @app.post('/api/folders',status_code=201)
    def create_folder(body:FolderCreate,request:Request,library:str|None=None):return folders(request,library,'create',body.path,body.name)
    @app.patch('/api/folders')
    def select_folder(body:FolderSelection,request:Request,library:str|None=None):return folders(request,library,'select',body.path)
