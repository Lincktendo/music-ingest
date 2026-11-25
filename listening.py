"""Listening and artwork belong to one library, including temporary auditions."""
import base64
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import threading
from concurrent.futures import Future
from urllib.parse import quote
import time
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from PIL import Image
from mutagen import File
from mutagen.flac import Picture
from mutagen.id3 import APIC
from mutagen.mp4 import MP4Cover

from core import UserError, VIDEO_ID
from qobuz_store import QID
from source_catalog import EXID
from storage import music_path

AUDITIONS = threading.BoundedSemaphore(3)
COVER_PREFIX = '/api/covers/custom/'


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
            with store.lock:
                if len(store.audition_errors)>=128:
                    store.audition_errors.pop(next(iter(store.audition_errors)))
                store.audition_errors[ident] = (time.monotonic(), message)
            raise HTTPException(429 if '(429)' in message else 400, detail=message) from None

    @app.get('/api/listen/{ident}/status')
    def audition_status(ident:str,request:Request,library:str|None=None):
        _,lib=access(request,library)
        validate_track(ident)
        store=registry.get(lib['id'])
        with store.lock:
            at,detail=store.audition_errors.get(ident,(0,''))
        return {'error':detail if time.monotonic()-at < 300 else ''}

    @app.post('/api/listen/{ident}/prepare')
    def audition_details(ident:str,request:Request,library:str|None=None):
        _,lib=access(request,library)
        path,url=prepare(registry.get(lib['id']),ident,lib['id'])
        audio=File(path)
        return {'url':url,'duration':audio.info.length if audio is not None and audio.info is not None else None}

    @app.api_route('/api/listen/{ident}',methods=['GET','HEAD'])
    def audition(ident:str,request:Request,library:str|None=None):
        _,lib=access(request,library)
        _,url=prepare(registry.get(lib['id']),ident,lib['id'])
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
