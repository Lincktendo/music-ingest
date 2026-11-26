"""Listening and artwork belong to one library, including temporary auditions."""
import base64
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import Future, TimeoutError as FutureTimeout
from urllib.parse import quote, urlsplit, parse_qs
from typing import NamedTuple
import time
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response, StreamingResponse
import requests
from PIL import Image
from mutagen import File
from mutagen.flac import Picture
from mutagen.id3 import APIC
from mutagen.mp4 import MP4Cover

from core import UserError, VIDEO_ID, classify_error
from qobuz_store import QID
from source_catalog import EXID
from storage import music_path

AUDITIONS = threading.BoundedSemaphore(3)
COVER_PREFIX = '/api/covers/custom/'
NATIVE_STREAMS = threading.BoundedSemaphore(8)
MAX_AUDIO = 150 * 1024 * 1024


class NoNativeAudio(Exception):
    """Use the existing validated temporary-file player for this source."""


class NativeAudio(NamedTuple):
    url: str
    size: int
    duration: float
    agent: str
    expires: float


def native_info(store, ident):
    """Resolve only the browser-playable original. Signed URLs never leave this process."""
    prepare_track(store, ident)
    engine = store.extractor.command() if store.extractor else [sys.executable,'-I','-m','yt_dlp']
    with store.sources.vault.youtube_file() as cookies:
        args=engine+['--ignore-config','--no-cache-dir','--no-playlist','--no-warnings','--socket-timeout','10',
                     '--retries','0','--js-runtimes','deno','--match-filter','!is_live & duration <= 3600',
                     '-f','bestaudio[ext=m4a][protocol=https][vcodec=none][acodec^=mp4a]',
                     '--print','%(url)s','--print','%(filesize)s','--print','%(duration)s',
                     '--print','%(http_headers.User-Agent)s']
        if cookies:
            args+=['--cookies',cookies]
        args+=['https://www.youtube.com/watch?v='+ident]
        try:
            result=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=45,check=False)
        except (subprocess.TimeoutExpired,OSError) as exc:
            raise NoNativeAudio() from exc
    if result.returncode:
        message=classify_error(result.stderr[-4096:].decode('utf-8','replace'))
        if '(429)' in message:
            raise UserError(message)
        raise NoNativeAudio()
    try:
        url,length,duration,agent=result.stdout.decode('utf-8').splitlines()
        u=urlsplit(url)
        if not (u.scheme=='https' and (u.hostname or '').endswith('.googlevideo.com') and u.port in (None,443)
                and u.username is None and u.password is None and u.path=='/videoplayback' and len(url)<16000):
            raise ValueError()
        params=parse_qs(u.query,max_num_fields=180)
        size=int(length if length.isdigit() else params['clen'][0])
        duration=float(duration)
        if not (0<size<=MAX_AUDIO and 0<duration<=3600 and agent.isascii() and agent.isprintable() and len(agent)<512):
            raise ValueError()
        now=time.time()
        expires=min(now+900,float(params.get('expire',[now+900])[0])-10)
        if expires<=now:
            raise ValueError()
        return NativeAudio(url,size,duration,agent,expires)
    except (ValueError,OverflowError,KeyError):
        raise NoNativeAudio() from None


def native_ticket(store,ident):
    if not VIDEO_ID.fullmatch(ident) or 'youtube' not in store.sources.index.active():
        raise NoNativeAudio()
    key=(ident,store.sources.option('youtube_revision'))
    with store.lock:
        if not hasattr(store,'native_info_cache'):
            store.native_info_cache={}
            store.native_info_pending={}
        entry=store.native_info_cache.get(key)
        if entry and time.time()<entry[0]:
            if entry[1] is None:
                raise NoNativeAudio()
            return entry[1]
        flight=store.native_info_pending.get(key)
        if flight is None:
            if not AUDITIONS.acquire(False):
                raise UserError('Ya hay varias pistas preparándose. Volvé a intentar en un momento.')
            flight=store.native_info_pending[key]=Future()
            leader=True
        else:
            leader=False
    if not leader:
        try:
            return flight.result(timeout=60)
        except FutureTimeout:
            raise UserError('La fuente está tardando en responder. Probá de nuevo en un momento.') from None
    try:
        resolved=native_info(store,ident)
        with store.lock:
            if len(store.native_info_cache)>=40:
                store.native_info_cache.pop(next(iter(store.native_info_cache)))
            store.native_info_cache[key]=(resolved.expires,resolved)
        flight.set_result(resolved)
        return resolved
    except Exception as exc:
        if isinstance(exc,NoNativeAudio):
            with store.lock:
                if len(store.native_info_cache)>=40:
                    store.native_info_cache.pop(next(iter(store.native_info_cache)))
                store.native_info_cache[key]=(time.time()+30,None)
        flight.set_exception(exc)
        raise
    finally:
        with store.lock:
            store.native_info_pending.pop(key,None)
        AUDITIONS.release()


def media_range(value,size):
    if not value:
        return 0,size-1,200
    match=re.fullmatch(r'bytes=(\d{0,12})-(\d{0,12})',value.strip(),re.I)
    if match and any(match.groups()):
        left,right=match.groups()
        start=int(left) if left else max(0,size-int(right))
        end=min(size-1,int(right)) if left and right else size-1
        if start<=end and start<size:
            return start,end,206
    raise HTTPException(416,'Rango de audio inválido.',headers={'Content-Range':'bytes */'+str(size)})


def native_response(ticket,ident,request):
    etag='"'+hashlib.sha256(f'{ident}/{ticket.size}/{ticket.duration}'.encode()).hexdigest()+'"'
    requested=request.headers.get('range') if request.headers.get('if-range',etag)==etag else None
    start,end,code=media_range(requested,ticket.size)
    headers={'Accept-Ranges':'bytes','Content-Length':str(end-start+1),'ETag':etag,'Cache-Control':'private, no-store'}
    if code==206:
        headers['Content-Range']=f'bytes {start}-{end}/{ticket.size}'
    if request.method=='HEAD':
        return Response(status_code=code,headers=headers,media_type='audio/mp4')
    if not NATIVE_STREAMS.acquire(False):
        raise HTTPException(429,'Hay varias escuchas activas. Probá de nuevo en un momento.')
    session=requests.Session()
    session.trust_env=False
    active=None
    closed=False

    def close():
        nonlocal closed
        if not closed:
            closed=True
            if active is not None:
                active.close()
            session.close()
            NATIVE_STREAMS.release()

    def block(offset):
        nonlocal active
        stop=min(end,offset+2*1024*1024-1)
        active=session.get(ticket.url,headers={'Range':f'bytes={offset}-{stop}','User-Agent':ticket.agent,
                           'Accept-Encoding':'identity'},stream=True,timeout=(6,15),allow_redirects=False)
        if active.status_code==429:
            raise UserError(classify_error('HTTP 429'))
        expected=f'bytes {offset}-{stop}/{ticket.size}'
        exact=(active.status_code==206 and active.headers.get('Content-Range','').lower()==expected)
        full=(active.status_code==200 and offset==0 and stop==ticket.size-1)
        if not (exact or full) or active.headers.get('Content-Length')!=str(stop-offset+1):
            raise NoNativeAudio()
        return stop
    try:
        first_end=block(start)
    except UserError:
        close()
        raise
    except (requests.RequestException,NoNativeAudio) as exc:
        close()
        raise NoNativeAudio() from exc

    def chunks():
        cursor=start
        stop=first_end
        try:
            while cursor<=end:
                for chunk in active.iter_content(16*1024):
                    if not chunk:
                        continue
                    cursor+=len(chunk)
                    if cursor>stop+1:
                        raise IOError('Respuesta de audio no válida.')
                    yield chunk
                active.close()
                if cursor!=stop+1:
                    raise IOError('Respuesta de audio incompleta.')
                if cursor<=end:
                    stop=block(cursor)
        except (requests.RequestException,NoNativeAudio,UserError):
            raise IOError('La fuente interrumpió la transmisión.') from None
        finally:
            close()

    class AudioResponse(StreamingResponse):
        async def __call__(self,scope,receive,send):
            try:
                await super().__call__(scope,receive,send)
            finally:
                close()
    return AudioResponse(chunks(),status_code=code,media_type='audio/mp4',headers=headers)


def validate_track(key):
    if not any(p.fullmatch(key) for p in (VIDEO_ID, QID, EXID)):
        raise UserError('Elegí una pista válida.')


def embed_picture(path, image):
    audio = File(path)
    if audio is None:
        raise UserError('Este archivo no admite una portada.')
    if audio.tags is None:
        audio.add_tags()
    if path.suffix in ('.mp3', '.wav', '.aiff'):
        audio.tags.delall('APIC')
        audio.tags.add(APIC(encoding=3, mime='image/jpeg', type=3, desc='Cover', data=image))
    elif path.suffix == '.m4a':
        audio.tags['covr'] = [MP4Cover(image, imageformat=MP4Cover.FORMAT_JPEG)]
    else:
        pic = Picture()
        pic.type, pic.mime, pic.data = 3, 'image/jpeg', image
        if path.suffix == '.flac':
            audio.clear_pictures()
            audio.add_picture(pic)
        else:
            audio.tags['metadata_block_picture'] = [base64.b64encode(pic.write()).decode()]
    audio.save()


def set_artwork(store, ident, content):
    validate_track(ident)
    if not isinstance(content, str) or len(content)>1_600_000:
        raise UserError('La portada es demasiado grande.')
    try:
        raw = base64.b64decode(content, validate=True)
        with Image.open(io.BytesIO(raw)) as im:
            if im.format!='JPEG' or im.width!=im.height or not 32<=im.width<=1200:
                raise ValueError()
            out=io.BytesIO()
            im.convert('RGB').save(out,'JPEG',quality=93)
            image=out.getvalue()
    except (ValueError,OSError,Image.DecompressionBombError):
        raise UserError('Elegí una portada cuadrada válida.') from None
    token=hashlib.sha256(image).hexdigest()
    folder=store.data/'artwork'
    cover=COVER_PREFIX+token
    with store.lock, store.db() as db:
        records=db.execute("SELECT * FROM files WHERE source_id=? OR json_extract(metadata,'$.youtube_id')=?",(ident,ident)).fetchall()
        if not records:
            store.sources.selected([ident])
        folder.mkdir(exist_ok=True)
        path=folder/(token+'.jpg')
        if not path.exists():
            temp=folder/(uuid4().hex+'.tmp')
            try:
                temp.write_bytes(image)
                os.replace(temp,path)
            finally:
                temp.unlink(missing_ok=True)
        staged=[]
        try:
            for record in records:
                dest=music_path(store.music,record['name'])
                if not dest.is_file():
                    continue
                temp=dest.with_name('.cover-'+uuid4().hex+dest.suffix)
                staged.append((temp,dest))
                shutil.copyfile(dest,temp)
                embed_picture(temp,image)
                metadata=json.loads(record['metadata'])
                if not metadata.get('original_cover'):
                    metadata['original_cover']=metadata.get('cover','')
                metadata['cover']=cover
                db.execute('UPDATE files SET metadata=? WHERE source_id=? AND format=?',(json.dumps(metadata),record['source_id'],record['format']))
            for temp,dest in staged:
                os.replace(temp,dest)
            for key in {ident,*[r['source_id'] for r in records]}:
                db.execute('INSERT OR REPLACE INTO custom_art VALUES(?,?)',(key,cover))
        finally:
            for temp,_ in staged:
                temp.unlink(missing_ok=True)
    return {'cover':cover}


def stored_audio(store, ident):
    with store.db() as db:
        rows = db.execute("SELECT * FROM files WHERE source_id=? OR json_extract(metadata,'$.youtube_id')=? ORDER BY format='mp3' DESC",
                          (ident, ident))
        for row in rows:
            path = music_path(store.music, row['name'])
            if path.is_file():
                return path, '/api/files/' + quote(row['job_id'], safe='') + '/' + quote(row['name'], safe='/')
    return None


def prepare_track(store, ident):
    sources = store.sources
    try:
        tracks = sources.selected([ident])
    except UserError:
        # A saved Home or playlist card can outlive the short-lived search cache.
        if not VIDEO_ID.fullmatch(ident) or 'youtube' not in sources.index.active():
            raise
        tracks = store.catalog.preview(ident, 'song')['tracks']
    if not sources.describe(tracks):
        raise UserError('Esta pista ya no está disponible en las fuentes habilitadas.')
    return tracks[0]


def audio_cache(store, ident, fmt):
    return store.data/'auditions'/(hashlib.sha256(ident.encode()).hexdigest()+'.'+fmt)


def build_audition(store, ident, track, target):
    root = target.parent
    root.mkdir(exist_ok=True)
    if shutil.disk_usage(root).free < 500_000_000:
        raise UserError('No hay espacio temporal suficiente para reproducir esta pista.')
    with tempfile.TemporaryDirectory(dir=root) as tmp:
        folder = Path(tmp)
        audio = folder/('audio'+target.suffix)
        if QID.fullmatch(ident):
            store.sources.purchases.download(ident, audio, lambda _:None)
        elif EXID.fullmatch(ident):
            store.sources.index.download(track, folder, 'mp3')
        else:
            store.download_youtube(folder, track, 'mp3', lambda _:None)
        media = File(audio) if audio.is_file() and audio.stat().st_size>=1000 else None
        if media is None or media.info is None or not 0 < media.info.length <= 3610:
            raise UserError('La fuente no entregó una pista de audio reproducible.')
        expected = track.get('duration_seconds') or track.get('duration') or 0
        try:
            seconds = sum(float(part) * 60**pos for pos, part in enumerate(reversed(str(expected).split(':'))))
        except ValueError:
            seconds = 0
        if seconds and media.info.length + max(4,seconds*.015) < seconds:
            raise UserError('La fuente entregó una pista incompleta. Probá reproducirla de nuevo.')
        os.replace(audio, target)
    with store.lock:
        files = sorted((p for p in root.glob('*.*') if p.is_file()),key=lambda p:p.stat().st_atime,reverse=True)
        now = time.time()
        for index, old in enumerate(files):
            age = now - old.stat().st_atime
            if old != target and (age>86400 or (index>=16 and age>300)):
                old.unlink(missing_ok=True)


def listen(store, ident):
    validate_track(ident)
    stored = stored_audio(store, ident)
    if stored:
        return stored[0]
    # A single preparation per track, including simultaneous tabs and browser range probes.
    with store.lock:
        flight = store.auditions.get(ident)
        if flight is None:
            if not AUDITIONS.acquire(False):
                raise UserError('Ya hay varias pistas preparándose. Volvé a intentar en un momento.')
            flight = store.auditions[ident] = Future()
            leader = True
        else:
            leader = False
    if not leader:
        return flight.result(timeout=900)
    try:
        if VIDEO_ID.fullmatch(ident) and 'youtube' in store.sources.index.active():
            cached = audio_cache(store, ident, 'mp3')
            with store.lock:
                if cached.is_file() and time.time()-cached.stat().st_atime < 86400:
                    os.utime(cached,(time.time(),cached.stat().st_mtime))
                    flight.set_result(cached)
                    return cached
        track = prepare_track(store, ident)
        fmt = 'flac' if QID.fullmatch(ident) and track.get('native_format','FLAC')=='FLAC' else 'mp3'
        target = audio_cache(store, ident, fmt)
        with store.lock:
            fresh = target.is_file() and time.time()-target.stat().st_atime < 86400
            if fresh:
                os.utime(target,(time.time(),target.stat().st_mtime))
        if not fresh:
            build_audition(store, ident, track, target)
        flight.set_result(target)
        return target
    except Exception as error:
        flight.set_exception(error)
        raise
    finally:
        with store.lock:
            store.auditions.pop(ident, None)
        AUDITIONS.release()


def install_listening(app,access,registry):
    def failure(store,ident,message):
        with store.lock:
            if len(store.audition_errors)>=128:
                store.audition_errors.pop(next(iter(store.audition_errors)))
            store.audition_errors[ident]=(time.monotonic(),message)
        return HTTPException(429 if '(429)' in message else 400,detail=message)

    def try_native(store,ident):
        try:
            return native_ticket(store,ident)
        except NoNativeAudio:
            return None
        except UserError as exc:
            raise failure(store,ident,str(exc)) from None

    def prefer_native(store,ident):
        if not VIDEO_ID.fullmatch(ident) or stored_audio(store,ident):
            return False
        cached=audio_cache(store,ident,'mp3')
        try:
            return time.time()-cached.stat().st_atime>=86400
        except FileNotFoundError:
            return True

    def prepare(store, ident, lid):
        validate_track(ident)
        try:
            path = listen(store, ident)
            if path.parent == store.data/'auditions':
                url = '/api/listen/'+quote(ident, safe='')+'/audio/'+path.suffix[1:]
            else:
                stored = stored_audio(store, ident)
                if not stored:
                    raise UserError('La pista guardada ya no está disponible.')
                url = stored[1]
            with store.lock:
                store.audition_errors.pop(ident,None)
            return path,url+'?library='+quote(lid,safe='')
        except Exception as error:
            message = str(error) if isinstance(error,UserError) else 'No se pudo preparar el audio. Probá de nuevo.'
            raise failure(store,ident,message) from None

    @app.get('/api/listen/{ident}/status')
    def audition_status(ident:str,request:Request,library:str|None=None):
        _,lib=access(request,library)
        validate_track(ident)
        store=registry.get(lib['id'])
        with store.lock:
            at,detail=store.audition_errors.get(ident,(0,''))
        return {'error':detail if time.monotonic()-at < 300 else ''}

    @app.post('/api/listen/{ident}/prepare')
    def audition_details(ident:str,request:Request,library:str|None=None,native:bool=False):
        _,lib=access(request,library)
        validate_track(ident)
        store=registry.get(lib['id'])
        if native and prefer_native(store,ident):
            ticket=try_native(store,ident)
            if ticket:
                url='/api/listen/'+ident+'?native=1&library='+quote(lib['id'],safe='')
                return {'url':url,'duration':ticket.duration}
        path,url=prepare(store,ident,lib['id'])
        audio=File(path)
        return {'url':url,'duration':audio.info.length if audio is not None and audio.info is not None else None}

    @app.api_route('/api/listen/{ident}',methods=['GET','HEAD'])
    def audition(ident:str,request:Request,library:str|None=None,native:bool=False):
        _,lib=access(request,library)
        validate_track(ident)
        store=registry.get(lib['id'])
        if native and prefer_native(store,ident):
            ticket=try_native(store,ident)
            if ticket:
                try:
                    response=native_response(ticket,ident,request)
                    with store.lock:
                        store.audition_errors.pop(ident,None)
                    return response
                except UserError as exc:
                    raise failure(store,ident,str(exc)) from None
                except NoNativeAudio:
                    revision=store.sources.option('youtube_revision')
                    with store.lock:
                        store.native_info_cache[(ident,revision)]=(time.time()+30,None)
        _,url=prepare(store,ident,lib['id'])
        return RedirectResponse(url,status_code=307)

    @app.api_route('/api/listen/{ident}/audio/{fmt}',methods=['GET','HEAD'])
    def audition_bytes(ident:str,fmt:str,request:Request,library:str|None=None):
        _,lib=access(request,library)
        validate_track(ident)
        if fmt not in ('mp3','flac'):
            raise HTTPException(404,'Audio no disponible.')
        store=registry.get(lib['id'])
        path=audio_cache(store,ident,fmt)
        with store.lock:
            if not path.is_file():
                raise HTTPException(404,'La escucha temporal venció. Volvé a abrir la rola.')
            # Reserve against eviction if the listener seeks or resumes from another tab.
            os.utime(path,(time.time(),path.stat().st_mtime))
        return FileResponse(path,media_type='audio/mpeg' if fmt=='mp3' else 'audio/flac')


    @app.put('/api/artwork/{ident}')
    def artwork(ident:str,body:dict,request:Request,library:str|None=None):
        _,lib=access(request,library,owner=True)
        return set_artwork(registry.get(lib['id']),ident,body.get('image'))

    @app.get('/api/covers/custom/{token}')
    def image(token:str,request:Request,library:str|None=None):
        _,lib=access(request,library)
        if not re.fullmatch('[a-f0-9]{64}',token):
            raise UserError('Portada inválida.')
        path=registry.get(lib['id']).data/'artwork'/(token+'.jpg')
        if not path.is_file():
            raise UserError('Portada no disponible.')
        return FileResponse(path,media_type='image/jpeg')

    @app.post('/api/home/choices')
    def choice(body:dict,request:Request,library:str|None=None):
        _,lib=access(request,library,owner=True)
        src=registry.get(lib['id']).sources
        field=body.get('action')
        items=body.get('values')
        if field not in ('hide','unhide','favorite','unfavorite') or not isinstance(items,list) or not 1<=len(items)<=100:
            raise UserError('Elegí una selección válida.')
        if any(not isinstance(i,str) or not i.strip() or len(i)>400 for i in items):
            raise UserError('La selección contiene un valor inválido.')
        key='favorite_artists' if field in ('favorite','unfavorite') else 'hidden_home'
        with src.store.lock:
            values={v.casefold():v for v in src.option(key,[])}
            changed=[]
            for i in items:
                if field in ('favorite','hide'):
                    if i.strip().casefold() not in values:
                        changed.append(i.strip())
                    values[i.strip().casefold()]=i.strip()
                else:
                    values.pop(i.strip().casefold(),None)
            if len(values)>10000:
                raise UserError('Llegaste al límite de preferencias de esta biblioteca.')
            src.set_option(key,list(values.values()))
        return {'saved':True,'changed':changed}
