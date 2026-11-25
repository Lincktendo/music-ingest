"""Scheduled music discovery with ownership-scoped, opt-in Navidrome rotation."""
import hashlib
import ipaddress
import json
import os
from pathlib import PurePosixPath
import random
import secrets
import threading
import time
import uuid
import unicodedata
from urllib.parse import urlsplit

from fastapi import Request
from pydantic import BaseModel, Field
import requests

from core import UserError, VIDEO_ID
from listening_collection import collection_for
from storage import music_path


DEFAULTS = {'enabled':False, 'interval_seconds':86400, 'cleanup':False,
            'navidrome_url':'', 'username':'', 'path_prefix':'', 'revision':0,
            'next_run':0, 'last_run':0, 'error':'', 'latest_count':0, 'last_cleanup':0, 'next_cleanup':0}


def server_url(value):
    value=value.strip().rstrip('/')
    if not value:
        return ''
    try:
        p=urlsplit(value)
        if p.scheme not in ('http','https') or not p.hostname or p.username or p.password or p.query or p.fragment:
            raise ValueError()
        p.port
        try:
            address=ipaddress.ip_address(p.hostname)
        except ValueError:
            address=None
        if address and (address.is_link_local or address.is_multicast or address.is_unspecified):
            raise ValueError()
    except ValueError:
        raise UserError('Escribí la dirección de tu Navidrome, por ejemplo http://navidrome:4533.') from None
    return value


def relative_prefix(value):
    value=value.strip().strip('/').replace('\\','/')
    if value and any(p in ('','.','..') or ':' in p or any(ord(c)<32 for c in p) for p in value.split('/')):
        raise UserError('La subcarpeta debe ser relativa a la carpeta de música de Navidrome.')
    return value


class Navidrome:
    def __init__(self, config, credentials):
        self.url=server_url(config['navidrome_url'])
        self.username=config['username']
        self.credentials=credentials
        if (not self.url or not self.username or not credentials.get('token') or
                credentials.get('url')!=self.url or credentials.get('username')!=self.username):
            raise UserError('Configurá y probá tu conexión con Navidrome primero.')

    def call(self, method, **params):
        query={'u':self.username,'t':self.credentials['token'],'s':self.credentials['salt'],
               'v':'1.16.1','c':'MusicIngest','f':'json',**params}
        try:
            with requests.get(self.url+'/rest/'+method+'.view', params=query,
                              timeout=(5,15), allow_redirects=False, stream=True) as response:
                if response.status_code!=200:
                    raise ValueError()
                body=bytearray()
                for piece in response.iter_content(65536):
                    body.extend(piece)
                    if len(body)>8_000_000:
                        raise ValueError()
                result=json.loads(body).get('subsonic-response',{})
                if result.get('status')!='ok':
                    raise ValueError()
                return result
        except (requests.RequestException,ValueError,KeyError):
            raise UserError('Navidrome no respondió correctamente. Revisá dirección, usuario y contraseña. La rotación conserva los archivos hasta poder verificar sus favoritos.') from None

    def snapshot(self):
        scan=self.call('getScanStatus').get('scanStatus',{})
        if scan.get('scanning') is not False:
            raise UserError('Navidrome está revisando su biblioteca. Esperaremos a que termine para revisar los favoritos.')
        starred=self.call('getStarred2').get('starred2')
        if not isinstance(starred,dict):
            raise UserError('Navidrome no devolvió sus favoritos. La limpieza queda pendiente.')
        return {kind:{str(x['id']) for x in starred.get(kind,[]) if isinstance(x,dict) and x.get('id')}
                for kind in ('song','album','artist')}

    def same_file(self, ident, local):
        before=local.stat()
        fingerprint=(before.st_size,before.st_mtime_ns,before.st_ino)
        with local.open('rb') as stream:
            local_hash=hashlib.file_digest(stream,'sha256').digest()
        params={'u':self.username,'t':self.credentials['token'],'s':self.credentials['salt'],
                'v':'1.16.1','c':'MusicIngest','f':'json','id':ident}
        received=0
        remote_hash=hashlib.sha256()
        deadline=time.monotonic()+90
        try:
            with requests.get(self.url+'/rest/download.view',params=params,headers={'Accept-Encoding':'identity'},
                              timeout=(5,15),allow_redirects=False,stream=True) as response:
                if response.status_code!=200:
                    raise ValueError()
                for chunk in response.iter_content(65536):
                    received+=len(chunk)
                    if received>before.st_size or time.monotonic()>deadline:
                        raise ValueError()
                    remote_hash.update(chunk)
        except (requests.RequestException,ValueError):
            raise UserError('Navidrome no pudo verificar el archivo original. La rola seguirá guardada hasta la próxima revisión.') from None
        after=local.stat()
        if (received!=before.st_size or remote_hash.digest()!=local_hash or
                (after.st_size,after.st_mtime_ns,after.st_ino)!=fingerprint):
            return None
        return fingerprint

    def exact_song(self, metadata, path, local):
        # Navidrome exposes a virtual tag-based path. Use metadata to locate a
        # unique candidate, then compare its complete original bytes.
        def text(value):
            return ' '.join(unicodedata.normalize('NFKC',str(value or '')).casefold().split())
        size=local.stat().st_size
        def compatible(song):
            if song.get('size')!=size:
                return False
            if song.get('path','').replace('\\','/')==path:
                return True
            if not metadata.get('title') or not metadata.get('artist'):
                return False
            if any(text(song.get(k))!=text(metadata.get(k)) for k in ('title','artist','album')):
                return False
            return not metadata.get('track') or str(song.get('track'))==str(metadata['track'])

        matches={}
        for offset in range(0,1000,100):
            data=self.call('search3',query=metadata.get('title') or PurePosixPath(path).stem,
                           songCount=100,songOffset=offset,albumCount=0,artistCount=0).get('searchResult3',{})
            songs=data.get('song',[])
            for song in songs:
                if song.get('id') and compatible(song):
                    matches[song['id']]=song
            if len(matches)>1:
                return None
            if len(songs)<100:
                break
        else:
            return None
        if len(matches)!=1:
            return None
        ident=next(iter(matches))
        song=self.call('getSong',id=ident).get('song')
        if not song or not compatible(song):
            return None
        fingerprint=self.same_file(ident,local)
        if fingerprint is None:
            return None
        # Refresh the heart after the content transfer, immediately before removal.
        song=self.call('getSong',id=ident).get('song')
        if not song or not compatible(song):
            return None
        return {**song,'verified_file':True,'local_stamp':fingerprint}


class Rotation:
    def __init__(self, registry):
        self.registry=registry
        self.stop_event=threading.Event()
        self.wake=threading.Event()
        self.lock=threading.Lock()
        self.thread=None
        self.initialized=set()

    def setup(self, store):
        with store.lock:
            if store in self.initialized:
                return
            with store.db() as db:
                db.executescript("""
                CREATE TABLE IF NOT EXISTS rotation_batches(id TEXT PRIMARY KEY,job_id TEXT NOT NULL,created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS rotation_tracks(batch TEXT NOT NULL,source_id TEXT NOT NULL,format TEXT NOT NULL,
                    job_id TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'pending',name TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(batch,source_id,format));
                """)
                db.execute("UPDATE jobs SET status='queued',error='' WHERE status='interrupted' AND id IN (SELECT job_id FROM rotation_batches)")
            self.initialized.add(store)
        store.event.set()

    def config(self, store):
        self.setup(store)
        with store.db() as db:
            row=db.execute("SELECT value FROM library_options WHERE key='rotation'").fetchone()
        default={**DEFAULTS,'path_prefix':store.music.relative_to(self.registry.music).as_posix()}
        if default['path_prefix']=='.':
            default['path_prefix']=''
        return {**default,**(json.loads(row[0]) if row else {})}

    def write(self, store, config):
        with store.db() as db:
            db.execute("INSERT OR REPLACE INTO library_options VALUES('rotation',?)",(json.dumps(config),))

    def credentials(self, store):
        path=store.data/'navidrome-session.json'
        try:
            return json.loads(path.read_text(encoding='utf8'))
        except (FileNotFoundError,ValueError):
            return {}

    def status(self, store):
        config=self.config(store)
        with store.db() as db:
            count=db.execute("""SELECT count(*) FROM rotation_tracks r JOIN files f
                ON f.source_id=r.source_id AND f.format=r.format AND f.job_id=r.job_id
                WHERE r.state='managed' AND r.name=f.name""").fetchone()[0]
        return {**config,'credential_set':bool(self.credentials(store).get('token')),'owned_count':count,
                'batch_size':20, 'bundled_url':os.environ.get('NAVIDROME_URL','http://navidrome:4533')}

    def update(self, store, body):
        with store.lock:
            config=self.config(store)
            incoming=body.model_dump(exclude_unset=True,exclude_none=True)
            password=incoming.pop('password',None)
            if 'navidrome_url' in incoming:
                incoming['navidrome_url']=server_url(incoming['navidrome_url'])
            if 'username' in incoming:
                incoming['username']=incoming['username'].strip()
            if 'path_prefix' in incoming:
                incoming['path_prefix']=relative_prefix(incoming['path_prefix'])
            changed=any(incoming.get(k,config[k])!=config[k] for k in ('navidrome_url','username'))
            cred=self.credentials(store)
            if password:
                salt=secrets.token_hex(16)
                cred={'salt':salt,'token':hashlib.md5((password+salt).encode()).hexdigest(),
                      'url':incoming.get('navidrome_url',config['navidrome_url']),
                      'username':incoming.get('username',config['username'])}
            elif changed:
                cred={}
            updated={**config,**incoming,'revision':config['revision']+1,'error':''}
            if updated['cleanup'] and (not cred or not updated['navidrome_url'] or not updated['username']):
                raise UserError('Para conservar favoritos, conectá tu usuario de Navidrome antes de activar la rotación.')
            path=store.data/'navidrome-session.json'
            tmp=path.with_suffix('.tmp')
            try:
                with open(tmp,'w',encoding='utf8') as file:
                    os.chmod(tmp,0o600)
                    json.dump(cred,file)
                os.replace(tmp,path)
            finally:
                tmp.unlink(missing_ok=True)
            if not config['enabled'] and updated['enabled']:
                updated['next_run']=time.time()
            elif updated['interval_seconds']!=config['interval_seconds']:
                updated['next_run']=max(time.time(),updated['last_run']+updated['interval_seconds'])
            self.write(store,updated)
        self.wake.set()
        return self.status(store)

    def test(self, store):
        with store.lock:
            client=Navidrome(self.config(store),self.credentials(store))
        reply=client.call('ping')
        client.snapshot()
        return {'connected':True,'server':reply.get('type','Navidrome'),
                'message':'Conectado. Se conservarán los favoritos de este usuario de Navidrome.'}

    def request_run(self, store):
        with store.lock:
            config=self.config(store)
            if not config['enabled']:
                raise UserError('Activá primero la descarga automática.')
            if config['last_run']>time.time()-60:
                raise UserError('El último lote acaba de iniciar. Esperá un minuto.')
            config['next_run']=0
            self.write(store,config)
        self.wake.set()
        return self.status(store)

    def candidates(self, store):
        data=store.sources.home()
        candidates={t['id']:t for section in data['sections'] for t in section['items']
                    if t.get('type','song')=='song' and not t.get('reference')}
        seeds=list(candidates)
        with store.db() as db:
            seeds += [r[0] for r in db.execute('SELECT source_id FROM files ORDER BY rowid DESC LIMIT 10')]
        random.SystemRandom().shuffle(seeds)
        for seed in seeds[:3]:
            if len(candidates)>=60:
                break
            if VIDEO_ID.fullmatch(seed):
                for track in collection_for(store).station(seed):
                    candidates.setdefault(track['id'],track)
        pool=list(candidates.values())
        random.SystemRandom().shuffle(pool)
        result=[]
        with store.db() as db:
            existing={row[0] for row in db.execute('SELECT source_id FROM files')}
            known={row[0] for row in db.execute('SELECT source_id FROM rotation_tracks')}
            busy={t['id'] for row in db.execute("SELECT payload FROM jobs WHERE status IN ('queued','running','interrupted')")
                  for t in json.loads(row[0])['tracks']}
        for item in pool:
            try:
                track=store.sources.plan([item],'auto')[0]
            except UserError:
                continue
            if track['id'] in existing|known|busy or track.get('youtube_id') in existing|known|busy:
                continue
            result.append(track)
            existing.add(track['id'])
            if len(result)==20:
                break
        return result

    def schedule(self, store, config):
        tracks=self.candidates(store)
        if not tracks:
            raise UserError('Faltan rolas nuevas para este lote. Escuchá música, marcá artistas favoritos o importá tu Inicio para alimentar las recomendaciones.')
        with store.lock,store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            live=self.config(store)
            if not live['enabled'] or live['revision']!=config['revision']:
                return
            if db.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]>=10:
                raise UserError('La cola está llena. La descarga automática esperará su turno.')
            # A manual download might finish while discovery was fetching.
            busy={t['id'] for row in db.execute("SELECT payload FROM jobs WHERE status IN ('queued','running','interrupted')")
                  for t in json.loads(row[0])['tracks']}
            safe=[]
            for track in tracks:
                ids={track['id'],track.get('youtube_id'),track.get('flac_id')}-{None,''}
                if ids&busy or any(db.execute("SELECT 1 FROM files WHERE source_id=? OR json_extract(metadata,'$.youtube_id')=?",(key,key)).fetchone() for key in ids):
                    continue
                safe.append(track)
            if not safe:
                return
            ident=uuid.uuid4().hex
            db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?)',(ident,'queued',json.dumps({'format':'auto','tracks':safe}),0,'',time.time()))
            db.execute('INSERT INTO rotation_batches VALUES(?,?,?)',(ident,ident,time.time()))
            db.executemany('INSERT INTO rotation_tracks(batch,source_id,format,job_id) VALUES(?,?,?,?)',
                           [(ident,t['id'],t['output_format'],ident) for t in safe])
            live.update(last_run=time.time(),next_run=time.time()+live['interval_seconds'],latest_count=len(safe),error='')
            db.execute("INSERT OR REPLACE INTO library_options VALUES('rotation',?)",(json.dumps(live),))
        store.event.set()

    def reconcile(self, store):
        with store.lock,store.db() as db:
            rows=db.execute("""SELECT r.*, f.name AS filename,f.job_id AS creator FROM rotation_tracks r
                LEFT JOIN files f ON f.source_id=r.source_id AND f.format=r.format WHERE r.state='pending'""").fetchall()
            for row in rows:
                if row['filename']:
                    state='managed' if row['creator']==row['job_id'] else 'kept'
                    db.execute('UPDATE rotation_tracks SET state=?,name=? WHERE batch=? AND source_id=? AND format=?',
                               (state,row['filename'],row['batch'],row['source_id'],row['format']))

    def cleanup(self, store, config):
        if not config['cleanup']:
            return
        with store.db() as db:
            latest=db.execute("""SELECT b.* FROM rotation_batches b JOIN jobs j ON j.id=b.job_id
                                WHERE j.status='completed' ORDER BY b.created DESC LIMIT 1""").fetchone()
            if not latest:
                return
            rows=db.execute("""SELECT r.*,f.metadata,f.name AS filename,f.job_id AS creator
                   FROM rotation_tracks r JOIN rotation_batches b ON b.id=r.batch
                   JOIN files f ON f.source_id=r.source_id AND f.format=r.format
                   WHERE r.state='managed' AND b.created<? ORDER BY b.created LIMIT 100""",(latest['created'],)).fetchall()
        if not rows:
            return
        with store.lock:
            if self.config(store)['revision']!=config['revision']:
                return
            client=Navidrome(config,self.credentials(store))
        stars=client.snapshot()
        missing=0
        for row in rows:
            if self.stop_event.is_set():
                return
            if row['creator']!=row['job_id'] or row['filename']!=row['name']:
                continue
            path='/'.join(filter(None,[config['path_prefix'],row['name']]))
            file_path=music_path(store.music,row['name'])
            if not file_path.is_file():
                continue
            song=client.exact_song(json.loads(row['metadata']),path,file_path)
            if not song or not song.get('verified_file'):
                missing+=1
                continue
            keep=bool(song.get('starred') or str(song.get('id','')) in stars['song'] or
                      str(song.get('albumId','')) in stars['album'] or str(song.get('artistId','')) in stars['artist'])
            with store.lock:
                live=self.config(store)
                if not live['enabled'] or not live['cleanup'] or live['revision']!=config['revision']:
                    return
                with store.db() as db:
                    current=db.execute('SELECT name,job_id FROM files WHERE source_id=? AND format=?',(row['source_id'],row['format'])).fetchone()
                if (not current or current['name']!=row['name'] or current['job_id']!=row['job_id']
                        or not file_path.is_file()):
                    continue
                current_stat=file_path.stat()
                if (current_stat.st_size,current_stat.st_mtime_ns,current_stat.st_ino)!=song['local_stamp']:
                    continue
                # delete_file checks confinement, active jobs and shared sidecars.
                if not keep:
                    store.delete_file(row['source_id'],row['format'])
                with store.db() as db:
                    db.execute('UPDATE rotation_tracks SET state=? WHERE batch=? AND source_id=? AND format=?',
                               ('kept' if keep else 'removed',row['batch'],row['source_id'],row['format']))
        with store.lock:
            live=self.config(store)
            if live['revision']==config['revision']:
                live['last_cleanup']=time.time()
                live['next_cleanup']=time.time()+(300 if missing else 60)
                live['error']=f'{missing} rolas quedan pendientes de ubicar en Navidrome. Revisá el escaneo y la subcarpeta compartida.' if missing else ''
                self.write(store,live)

    def tick(self):
        if not self.lock.acquire(False):
            return
        try:
            with self.registry.accounts.db() as db:
                ids=[r[0] for r in db.execute('SELECT id FROM libraries')]
            for lid in ids:
                if self.stop_event.is_set():
                    return
                store=self.registry.get(lid)
                config=self.config(store)
                if not config['enabled']:
                    continue
                try:
                    self.reconcile(store)
                    if config['next_cleanup']<=time.time():
                        self.cleanup(store,config)
                    config=self.config(store)
                    if config['next_run']<=time.time():
                        self.schedule(store,config)
                except Exception as error:
                    with store.lock:
                        live=self.config(store)
                        if live['revision']==config['revision']:
                            live['error']=str(error)[:500] if isinstance(error,UserError) else 'La actualización automática quedó pendiente. Revisaremos de nuevo.'
                            live['next_run']=max(live['next_run'],time.time()+60)
                            live['next_cleanup']=time.time()+60
                            self.write(store,live)
        finally:
            self.lock.release()

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        def loop():
            while not self.stop_event.is_set():
                self.tick()
                self.wake.wait(30)
                self.wake.clear()
        self.thread=threading.Thread(target=loop,name='music-rotation',daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=20)


class RotationSettings(BaseModel):
    enabled: bool | None = None
    interval_seconds: int | None = Field(default=None,ge=60,le=2592000)
    cleanup: bool | None = None
    navidrome_url: str | None = Field(default=None,max_length=500)
    username: str | None = Field(default=None,max_length=200)
    password: str | None = Field(default=None,max_length=500)
    path_prefix: str | None = Field(default=None,max_length=500)


def install_rotation(app, access, registry):
    rotation=Rotation(registry)
    def own(request,library):
        _,lib=access(request,library,owner=True)
        return registry.get(lib['id'])

    @app.get('/api/rotation')
    def status(request:Request,library:str|None=None):
        return rotation.status(own(request,library))

    @app.patch('/api/rotation')
    def update(body:RotationSettings,request:Request,library:str|None=None):
        return rotation.update(own(request,library),body)

    @app.post('/api/rotation/test')
    def test(request:Request,library:str|None=None):
        return rotation.test(own(request,library))

    @app.post('/api/rotation/run')
    def run(request:Request,library:str|None=None):
        return rotation.request_run(own(request,library))

    return rotation
