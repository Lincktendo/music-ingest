"""Edit the tags of a managed audio file without altering its other metadata."""
import json
import os
from pathlib import Path
import shutil
import tempfile

from fastapi import Request
from mutagen import File
from mutagen.id3 import TALB, TIT2, TPE1, TRCK
from pydantic import BaseModel, Field

from accounts import scope_urls
from audio_formats import AudioFormat
from core import UserError
from storage import music_path


class Tags(BaseModel):
    title: str = Field(min_length=1,max_length=300)
    artist: str = Field(min_length=1,max_length=300)
    album: str = Field(default='',max_length=300)
    track: int | None = Field(default=None,ge=1,le=9999)
    revision: int = Field(default=0,ge=0)


def write_tags(path, fields):
    audio=File(path)
    if audio is None:
        raise UserError('No se pudo leer el formato del archivo.')
    if audio.tags is None:
        audio.add_tags()
    values=[fields['title'],fields['artist'],fields['album'],str(fields['track'] or '')]
    if path.suffix.lower() in ('.mp3','.wav','.aiff'):
        for frame,value in zip((TIT2,TPE1,TALB,TRCK),values):
            audio.tags.delall(frame.__name__)
            if value:
                audio.tags.add(frame(encoding=3,text=[value]))
    elif path.suffix.lower()=='.m4a':
        for key,value in zip(('©nam','©ART','©alb','trkn'),values):
            if value:
                audio.tags[key]=[(int(value),0)] if key=='trkn' else [value]
            else:
                audio.tags.pop(key,None)
    else:
        for key,value in zip(('title','artist','album','tracknumber'),values):
            if value:
                audio.tags[key]=[value]
            else:
                audio.tags.pop(key,None)
    audio.save()


def edit_tags(store,ident,fmt,body):
    fields={k:getattr(body,k).strip() for k in ('title','artist','album')}
    if not fields['title'] or not fields['artist'] or any(any(ord(c)<32 for c in v) for v in fields.values()):
        raise UserError('Escribí un título y un artista válidos.')
    fields['track']=body.track
    with store.lock,store.db() as db:
        row=db.execute('SELECT * FROM files WHERE source_id=? AND format=?',(ident,fmt)).fetchone()
        if row is None or not store.public_file(row):
            raise UserError('Esta versión ya no está en la biblioteca.')
        metadata=json.loads(row['metadata'])
        if body.revision!=metadata.get('tag_revision',0):
            raise UserError('Esta pista cambió. Abrí sus datos otra vez antes de guardar.')
        path=music_path(store.music,row['name'])
        fd,name=tempfile.mkstemp(prefix='.ingest-tags-',suffix=path.suffix,dir=path.parent)
        os.close(fd)
        tmp=Path(name)
        try:
            shutil.copy2(path,tmp)
            write_tags(tmp,fields)
            metadata.update(fields,tag_revision=body.revision+1)
            row=dict(row,metadata=json.dumps(metadata,ensure_ascii=False))
            db.execute('UPDATE files SET metadata=? WHERE source_id=? AND format=?',(row['metadata'],ident,fmt))
            os.replace(tmp,path)
        finally:
            tmp.unlink(missing_ok=True)
        return store.public_file(row)


def install_download_tools(app,access,registry):
    @app.get('/api/library/record/{ident}')
    def saved_record(ident:str,request:Request,library:str|None=None):
        _,lib=access(request,library)
        store=registry.get(lib['id'])
        with store.db() as db:
            rows=db.execute("""SELECT * FROM files WHERE source_id=? OR json_extract(metadata,'$.youtube_id')=?
                               ORDER BY format='mp3' DESC, rowid DESC""",(ident,ident))
            for row in rows:
                file=store.public_file(row)
                if file:
                    return {'file':scope_urls(file,lib['id'])}
        return {'file':None}

    @app.patch('/api/library/{ident}/{fmt}/metadata')
    def metadata(ident:str,fmt:AudioFormat,body:Tags,request:Request,library:str|None=None):
        _,lib=access(request,library,owner=True)
        item=edit_tags(registry.get(lib['id']),ident,fmt,body)
        return {'file':scope_urls(item,lib['id'])}

    @app.delete('/api/jobs/{ident}')
    def dismiss_attempt(ident:str,request:Request,library:str|None=None):
        _,lib=access(request,library,owner=True)
        store=registry.get(lib['id'])
        with store.lock,store.db() as db:
            result=db.execute("DELETE FROM jobs WHERE id=? AND status IN ('failed','interrupted')",(ident,))
            if not result.rowcount:
                raise UserError('Solo podés quitar intentos fallidos o interrumpidos.')
        return {'removed':True}
