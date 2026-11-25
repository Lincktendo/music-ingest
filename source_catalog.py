"""Library-local source index and public URL imports."""
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

from core import UserError
from audio_formats import CATALOG, ORDER, EXTENSIONS, LOSSLESS, native_audio

NAMES={'youtube':'YouTube Music','qobuz':'Qobuz','soundcloud.com':'SoundCloud','vimeo.com':'Vimeo',
       'bandcamp.com':'Bandcamp','dailymotion.com':'Dailymotion','mixcloud.com':'Mixcloud','archive.org':'Internet Archive'}
DOMAINS={'youtube':'music.youtube.com','qobuz':'qobuz.com'}
EXID=re.compile(r'ex:[a-f0-9]{32}\Z')
SLOTS=threading.BoundedSemaphore(2)


def host_of(url):
    try:
        parsed=urlsplit(url.strip())
        host=(parsed.hostname or '').lower()
        if (parsed.scheme not in ('http','https') or not re.fullmatch(r'(?:[a-z0-9-]+\.)+[a-z]{2,63}',host)
                or parsed.username is not None or parsed.password is not None or parsed.port not in (None,443,80)
                or host.endswith(('.local','.localhost','.internal','.lan','.home.arpa')) or len(url)>2048
                or any(c.isspace() or ord(c)<32 for c in url) or '\\' in url):
            raise ValueError()
        return host
    except ValueError:
        raise UserError('Pegá un enlace público de música o video.') from None


def provider(url):
    host=host_of(url).removeprefix('www.')
    if host in ('youtu.be','m.youtube.com','music.youtube.com','youtube.com'):
        return 'youtube'
    for key,domain in [('qobuz','qobuz.com')]+[(x,x) for x in NAMES if '.' in x]:
        if host==domain or host.endswith('.'+domain):
            return key
    return host


def title_for(key):
    return NAMES.get(key,key)


class PageLinks(HTMLParser):
    def __init__(self,key):
        super().__init__()
        self.key=key
        self.items={}
        self.link=''
        self.parts=[]
        self.hint=''

    def handle_starttag(self,tag,attrs):
        if tag!='a':
            return
        data=dict(attrs)
        self.link=''
        self.parts=[]
        self.hint=data.get('title') or data.get('aria-label') or ''
        try:
            url=urljoin('https://'+DOMAINS.get(self.key,self.key)+'/',data.get('href') or '')
            u=urlsplit(url)
            if provider(url)!=self.key or u.path.strip('/')=='' or len(self.items)>=200:
                return
            if self.key=='qobuz' and not re.search(r'/(album|track|artist|interpreter)/',u.path):
                return
            if re.search(r'/(login|signup|settings|account|legal|terms|about|profile)(/|$)',u.path,re.I):
                return
            self.link=urlunsplit(('https',u.hostname,u.path,'',''))
        except (ValueError,TypeError):
            pass

    def handle_data(self,data):
        if self.link and len(self.parts)<15:
            self.parts.append(data[:180])

    def handle_endtag(self,tag):
        if tag!='a' or not self.link:
            return
        name=' '.join((' '.join(self.parts).strip() or self.hint).split())[:180]
        if name:
            path=urlsplit(self.link).path
            kind='album' if '/album/' in path else 'artist' if '/artist/' in path or '/interpreter/' in path else 'song'
            self.items[self.link]={'id':'ref:'+sha256(self.link.encode()).hexdigest()[:32], 'url':self.link,
                                   'title':name,'artist':'','type':kind,'source':self.key,'reference':True}
        self.link=''


class SourceIndex:
    def __init__(self,sources):
        self.sources=sources
        self.store=sources.store
        with self.store.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS source_index(id TEXT PRIMARY KEY, source TEXT, metadata TEXT, updated REAL)')
            db.execute('CREATE TABLE IF NOT EXISTS source_formats(source TEXT, format TEXT, PRIMARY KEY(source,format))')
            if not db.execute("SELECT 1 FROM library_options WHERE key='format_history_initialized'").fetchone():
                for (raw,) in db.execute("SELECT metadata FROM files WHERE source_id LIKE 'ex:%'"):
                    track=json.loads(raw)
                    if track.get('source'):
                        self.learn(db, track['source'], native_audio(track.get('native_format')))
                db.execute("INSERT INTO library_options VALUES('format_history_initialized', 'true')")
        self.related_lock=threading.Lock()
        self.search_cache={}

    def active(self):
        removed=set(self.sources.option('removed_sources', []))
        return [k for k in ('youtube','qobuz',*self.sources.option('extra_sources',[])) if k not in removed]

    @staticmethod
    def learn(db, key, native, ident=None):
        verified = {'mp3'}
        if native in ORDER:
            verified.add(native)
        if native in LOSSLESS:
            verified.add('flac')
        db.executemany('INSERT OR IGNORE INTO source_formats VALUES(?,?)', [(key, f) for f in verified])
        if ident and native in ORDER:
            row=db.execute('SELECT metadata FROM source_index WHERE id=? AND source=?',(ident,key)).fetchone()
            if row:
                track=json.loads(row[0])
                track['verified_native']=native
                track['offered_formats']=sorted(set(track.get('offered_formats',[]))|{native})
                db.execute('UPDATE source_index SET metadata=? WHERE id=?',(json.dumps(track),ident))

    def add(self,key):
        if key not in ('youtube','qobuz'):
            key=provider(key if '://' in key else 'https://'+key)
        with self.store.lock:
            removed=self.sources.option('removed_sources',[])
            extra=self.sources.option('extra_sources',[])
            if key not in ('youtube','qobuz') and key not in extra:
                if len(extra)>=32:
                    raise UserError('Ya tenés 32 fuentes adicionales.')
                self.sources.set_option('extra_sources',extra+[key])
            if key in removed:
                self.sources.set_option('removed_sources',[k for k in removed if k!=key])
        return key

    def import_html(self,key,content):
        if key not in self.active() or not isinstance(content,str) or len(content.encode())>12*1024*1024:
            raise UserError('Elegí la fuente y un HTML de hasta 12 MB.')
        if key=='youtube':
            return self.sources.html(content)
        parser=PageLinks(key)
        try:
            parser.feed(content);parser.close()
        except (ValueError,AssertionError,RecursionError):
            raise UserError('No se pudo leer la página.') from None
        if not parser.items:
            raise UserError('Esa página no contiene enlaces reconocibles de esta fuente.')
        with self.store.lock:
            if key not in self.active():
                raise UserError('La fuente se eliminó.')
            self.sources.set_option('page:'+key,list(parser.items.values()))
        return {'imported':len(parser.items)}

    def indexed(self):
        with self.store.db() as db:
            rows=db.execute('SELECT metadata FROM source_index ORDER BY updated DESC LIMIT 250').fetchall()
        return [json.loads(row[0]) for row in rows]

    def rows(self):
        items=self.indexed()
        for key in self.active():
            if key!='youtube':
                items.extend(self.sources.option('page:'+key,[]))
        return items

    def get(self,ident):
        with self.store.db() as db:
            row=db.execute('SELECT metadata FROM source_index WHERE id=?',(ident,)).fetchone()
        if not row:
            raise UserError('Volvé a pegar el enlace para revisar esa pista.')
        return json.loads(row[0])

    def search_soundcloud(self,query):
        stamp=time.monotonic()
        with self.store.lock:
            cached=self.search_cache.get(query)
            if cached and stamp-cached[0]<600:
                return cached[1]
        try:
            rows=self.run('', 'soundcloud.com', search=query)
            items=[{'id':'ref:'+sha256(t['url'].encode()).hexdigest()[:32],'type':'song','source':'soundcloud.com',
                    'reference':True,**t} for t in rows if provider(t['url'])=='soundcloud.com']
        except UserError:
            items=[]
        with self.store.lock:
            if len(self.search_cache)>=100:
                self.search_cache.pop(next(iter(self.search_cache)))
            self.search_cache[query]=(stamp,items)
        return items

    def run(self,url,key,output=None,fmt=None,search=None):
        if not SLOTS.acquire(timeout=3):
            raise UserError('Hay enlaces en proceso. Probá nuevamente en unos segundos.')
        cmd=self.store.extractor.command() if self.store.extractor else []
        engine=cmd[2] if len(cmd)==3 else ''
        try:
            with self.sources.vault.session_file(key) as cookie:
                args={'url':url,'search':search,'engine':engine,'cookies':cookie,'output':str(output) if output else None,'format':fmt}
                with subprocess.Popen([sys.executable,'-I',str(Path(__file__).with_name('public_audio_worker.py'))],
                                      stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf8') as job:
                    deadline=time.monotonic()+(420 if output else 7 if search else 24)
                    payload=json.dumps(args)
                    while not self.store.stop_event.is_set() and time.monotonic()<deadline:
                        try:
                            result,_=job.communicate(payload,timeout=1)
                            break
                        except subprocess.TimeoutExpired:
                            payload=None
                    else:
                        job.kill()
                        job.communicate()
                        raise UserError('La consulta se interrumpió o la fuente tardó demasiado en responder.')
                if job.returncode:
                    raise UserError('Esta fuente no ofreció audio descargable para ese enlace. Probá con una canción o un video público.')
                return json.loads(result)
        finally:
            SLOTS.release()

    def preview(self,url):
        key=provider(url)
        info=self.run(url,key)
        ident='ex:'+sha256(url.encode()).hexdigest()[:32]
        codec=info['acodec']
        if codec in ('','none','unknown'):
            codec=info['ext'] if info['ext'] in ('mp3','aac','opus','vorbis','flac','wav') else ''
        track={'id':ident,'type':'song','source':key,'provider':title_for(key),'title':info['title'],'artist':info['artist'] or info['uploader'],
               'album':info['album'],'duration':info['duration'],'cover':self.store.catalog.cover([{'url':info.get('thumbnail','')}]),'native_format':info['native_lossless'] or codec,
               'offered_formats':info.get('offered_formats',[]),'native_lossless':bool(info['native_lossless'])}
        with self.store.lock,self.store.db() as db:
            if key in self.sources.option('removed_sources',[]):
                raise UserError('La fuente se eliminó.')
            if not native_audio(track['native_format']) and not track['offered_formats']:
                old=db.execute('SELECT metadata FROM source_index WHERE id=?',(ident,)).fetchone()
                verified=json.loads(old[0]).get('verified_native') if old else None
                if verified:
                    track.update(verified_native=verified,offered_formats=[verified])
            db.execute('INSERT OR REPLACE INTO source_secrets VALUES(?,?)',(ident,self.sources.vault.seal(ident,url)))
            db.execute('INSERT OR REPLACE INTO source_index VALUES(?,?,?,?)',(ident,key,json.dumps(track),time.time()))
        return track

    def download(self,track,folder,fmt):
        url=self.sources.vault.read(track['id'])
        if not url:
            raise UserError('Volvé a revisar el enlace antes de descargar.')
        raw=folder/'input.media'
        self.run(url,provider(url),raw,fmt)
        local=['-protocol_whitelist','file,pipe','-format_whitelist','mp3,flac,wav,mov,matroska,webm,ogg,aac,mpegts,asf,aiff,flv,avi']
        probe=subprocess.run(['ffprobe','-v','error',*local,'-select_streams','a:0','-show_entries','stream=codec_name:format=format_name',
                              '-of','json',str(raw)],capture_output=True,text=True,timeout=15)
        if probe.returncode:
            raise UserError('No se pudo identificar el audio del enlace.')
        data=json.loads(probe.stdout)
        streams=data.get('streams') or [{}]
        native=native_audio(streams[0].get('codec_name'),data.get('format',{}).get('format_name'))
        if fmt=='flac' and native not in LOSSLESS or fmt not in ('mp3','flac') and native!=fmt:
            raise UserError('La fuente cambió el audio disponible. Volvé a abrir la pista.')
        codec=['-c:a','copy']
        if fmt=='flac' and native!='flac':
            codec=['-c:a','flac']
        elif fmt=='mp3' and native!='mp3':
            codec=['-c:a','libmp3lame','-q:a','0']
        ext=EXTENSIONS.get(fmt,fmt)
        result=subprocess.run(['ffmpeg','-nostdin','-v','error',*local,'-i',str(raw),'-map','0:a:0','-vn','-map_metadata','-1',
                               *codec,str(folder/('audio.'+ext))],stderr=subprocess.DEVNULL,timeout=180)
        if result.returncode:
            raise UserError('No se pudo guardar el audio en el formato elegido.')
        return native
