"""Resolve saved watch links to official audio and album artwork before displaying them."""
import threading
import time

from core import VIDEO_ID, ALBUM_ID
from music_home import ATV, album_art


def recording(raw):
    thumb=album_art(raw.get('thumbnail') or '')
    album=raw.get('type')=='album' and ALBUM_ID.fullmatch(raw.get('id',''))
    if thumb and (album or raw.get('type','song')=='song' and raw.get('video_type')==ATV):
        return {**raw,'thumbnail':thumb}
    return None


def lookup(catalog,ident,hint=None):
    client=catalog.suggest_factory()
    try:
        try:
            watch=client.get_watch_playlist(videoId=ident,limit=1)
            row=next((r for r in watch.get('tracks',[]) if r.get('videoId')==ident),None)
        except Exception:
            row=None
        if not row and hint and hint.get('title'):
            query=' '.join(str(hint.get(k) or '') for k in ('title','artist')).strip()
            results=client.search(query,filter='songs',limit=10)
            row=next((r for r in results if r.get('videoId')==ident),None)
        if not row:
            return None
        if row.get('videoType')!=ATV:
            # Only trust an official audio counterpart explicitly associated by the catalog.
            pair=row.get('counterpart')
            row=next((r for r in pair if isinstance(r,dict) and r.get('videoType')==ATV),None) if isinstance(pair,list) else pair
        if not isinstance(row,dict) or row.get('videoType')!=ATV:
            return None
        thumbs=row.get('thumbnail') or row.get('thumbnails') or []
        art=next((u for t in reversed(thumbs) if isinstance(t,dict) and (u:=album_art(t.get('url','')))), '')
        result=catalog.normalize({**row,'resultType':'song','thumbnails':thumbs})
        return recording({**result,'thumbnail':art}) if result else None
    finally:
        session=getattr(client,'_session',None)
        if session:
            session.close()


class HomeRecordings:
    def __init__(self,sources):
        self.sources=sources
        self.lock=threading.Lock()

    def sections(self,sections):
        saved=self.sources.option('official_home_cache',{})
        pending={}
        for section in sections:
            matches=[]
            for row in section['items']:
                if row.get('source','youtube')=='youtube' and row.get('type')=='album':
                    result=recording(row)
                    if result:
                        item={**result,'cover':self.sources.store.catalog.cover([{'url':result['thumbnail']}])}
                        item.pop('thumbnail',None)
                        matches.append(item)
                    continue
                if row.get('source','youtube')!='youtube' or not VIDEO_ID.fullmatch(row.get('id','')):
                    if row.get('source','youtube')!='youtube' and row.get('type','song') in ('song','album') and row.get('cover') and row.get('source') not in ('vimeo.com','dailymotion.com'):
                        matches.append(row)
                    continue
                if row.get('type','song')!='song':
                    continue
                result=recording(row)
                if not result:
                    existing=saved.get(row['id'],{})
                    if existing.get('until',0)>time.time():
                        result=existing.get('item')
                    else:
                        pending[row['id']]=row
                if result:
                    art=result['thumbnail']
                    item={**row,**result,'source':'youtube','cover':self.sources.store.catalog.cover([{'url':art}])}
                    item.pop('thumbnail',None)
                    matches.append(item)
            section['items']=matches
        if pending and self.lock.acquire(False):
            threading.Thread(target=self.verify,args=(list(pending.items())[:250],),daemon=True,name='home-recordings').start()
        return bool(pending)

    def verify(self,ids):
        try:
            for ident,hint in ids:
                if self.sources.store.stop_event.is_set() or 'youtube' not in self.sources.index.active():
                    break
                try:
                    item=lookup(self.sources.store.catalog,ident,hint)
                    ttl=86400*14
                except Exception:
                    item,ttl=None,180
                with self.sources.store.lock:
                    cache=self.sources.option('official_home_cache',{})
                    cache={k:v for k,v in cache.items() if v.get('until',0)>time.time()}
                    cache[ident]={'item':item,'until':time.time()+ttl}
                    self.sources.set_option('official_home_cache',dict(list(cache.items())[-1000:]))
        finally:
            self.lock.release()
