"""Source settings, recommendations and concrete per-track download plans."""
import json
from collections import Counter
import threading
import time
import uuid

from core import VIDEO_ID, UserError
from audio_formats import CATALOG, ORDER, track_formats, prefer
from music_home import import_home, live_home
from source_catalog import SourceIndex, EXID, NAMES, title_for
from qobuz_store import PurchaseCatalog, QID
from source_sessions import PrivateSources, cookie_rows


class Sources:
    def __init__(self, store):
        self.store = store
        from home_recordings import HomeRecordings
        self.recordings = HomeRecordings(self)
        self.vault = PrivateSources(store)
        self.purchases = PurchaseCatalog(store, self.vault)
        self.home_lock = threading.Lock()
        self.sync_lock = threading.Lock()
        self.index = SourceIndex(self)

    def option(self, name, default=None):
        with self.store.db() as db:
            row = db.execute('SELECT value FROM library_options WHERE key=?', (name,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_option(self, name, value):
        with self.store.db() as db:
            db.execute('INSERT OR REPLACE INTO library_options VALUES(?,?)', (name, json.dumps(value, ensure_ascii=False)))

    def settings(self):
        with self.store.db() as db:
            names = {r[0] for r in db.execute("SELECT name FROM source_secrets WHERE name NOT LIKE 'purchase:%' AND name NOT LIKE 'ex:%'")}
            count = db.execute('SELECT COUNT(*) FROM qobuz_purchases').fetchone()[0]
        active=self.index.active()
        preferences=self.option('source_preferences', {})
        with self.store.db() as db:
            learned={}
            for key,fmt in db.execute('SELECT source,format FROM source_formats'):
                learned.setdefault(key,set()).add(fmt)
        sources=[]
        for key in active:
            prefs=preferences.get(key,{})
            capabilities=set(CATALOG.get(key,()))|learned.get(key,set())
            formats=[f for f in ORDER if f in capabilities]
            sources.append({'id':key,'name':title_for(key),'search':key not in self.option('muted_search',[]),
                            'formats':formats,'enabled_formats':[f for f in formats if f not in prefs.get('off',[])],
                            'home':prefs.get('home',True),'favorite':prefs.get('favorite',False),
                            'html':self.index.imported_count(key), 'session':key in names})
        return {'sources':sources,
                'available':[{'id':k,'name':n} for k,n in NAMES.items() if k not in active], 'best': self.option('best_quality', True), 'youtube': 'youtube' in names,
                'qobuz': 'qobuz' in names, 'purchases': count, 'html_count': self.index.imported_count('youtube')}

    def configure(self,key,field,value,fmt=None):
        with self.store.lock:
            src=next((s for s in self.settings()['sources'] if s['id']==key),None)
            if not src or type(value) is not bool or not isinstance(field,str):
                raise UserError('Elegí una fuente activa.')
            options=self.option('source_preferences',{})
            prefs=options.setdefault(key,{})
            if field=='format':
                if not isinstance(fmt,str) or fmt not in src['formats'] or src['formats']==['mp3'] and not value:
                    raise UserError('Ese formato no se puede cambiar en esta fuente.')
                off=set(prefs.get('off',[]))
                if value:
                    off.discard(fmt)
                else:
                    off.add(fmt)
                prefs['off']=sorted(off)
            elif field in ('home','favorite'):
                prefs[field]=value
            else:
                raise UserError('Opción de fuente desconocida.')
            self.set_option('source_preferences',options)

    def remove(self,key):
        with self.store.lock,self.store.db() as db:
            if key not in self.index.active():
                raise UserError('La fuente ya fue eliminada.')
            def save(k,v):
                db.execute('INSERT OR REPLACE INTO library_options VALUES(?,?)',(k,json.dumps(v)))
            removed=self.option('removed_sources',[])
            save('removed_sources',list(dict.fromkeys([*removed,key])))
            save('extra_sources',[k for k in self.option('extra_sources',[]) if k!=key])
            save('muted_search',[k for k in self.option('muted_search',[]) if k!=key])
            preferences=self.option('source_preferences',{})
            preferences.pop(key,None)
            save('source_preferences',preferences)
            db.execute('DELETE FROM library_options WHERE key=?',('page:'+key,))
            db.execute('DELETE FROM source_imports WHERE source=?',(key,))
            db.execute('DELETE FROM source_secrets WHERE name=?',(key,))
            db.execute('DELETE FROM source_secrets WHERE name IN (SELECT id FROM source_index WHERE source=?)',(key,))
            db.execute('DELETE FROM source_index WHERE source=?',(key,))
            db.execute('DELETE FROM source_formats WHERE source=?',(key,))
            if key=='youtube':
                db.execute("DELETE FROM library_options WHERE key IN ('home_html','home_live','related_music')")
                save('youtube_revision',uuid.uuid4().hex)
            elif key=='qobuz':
                db.execute('DELETE FROM qobuz_purchases')
                db.execute("DELETE FROM source_secrets WHERE name LIKE 'purchase:%'")
                save('qobuz_revision',uuid.uuid4().hex)

    def change_session(self, provider, text=None):
        if provider not in self.index.active():
            raise UserError('Agregá primero esa fuente.')
        domains = {provider,'www.'+provider} if provider not in ('youtube','qobuz') else None
        rows = cookie_rows(provider, text, domains) if text is not None else None
        if rows and provider == 'youtube' and not any(r[4] == '__Secure-3PAPISID' for r in rows):
            raise UserError('Ese archivo no incluye la sesión de YouTube Music. Iniciá sesión y exportá las cookies de esa pestaña.')
        with self.store.lock, self.store.db() as db:
            if provider not in self.index.active():
                raise UserError('La fuente se eliminó.')
            if rows:
                db.execute('INSERT OR REPLACE INTO source_secrets VALUES(?,?)', (provider, self.vault.seal(provider, rows)))
            else:
                db.execute('DELETE FROM source_secrets WHERE name=?', (provider,))
            if provider == 'youtube':
                db.execute("DELETE FROM library_options WHERE key='home_live'")
                db.execute("INSERT OR REPLACE INTO library_options VALUES('youtube_revision', ?)", (json.dumps(uuid.uuid4().hex),))
            elif provider == 'qobuz':
                # An uploaded session can belong to another account.
                db.execute('DELETE FROM qobuz_purchases')
                db.execute("DELETE FROM source_secrets WHERE name LIKE 'purchase:%'")
                db.execute("INSERT OR REPLACE INTO library_options VALUES('qobuz_revision', ?)", (json.dumps(uuid.uuid4().hex),))
        return self.settings()

    def refresh(self, link=''):
        if not self.sync_lock.acquire(False):
            raise UserError('Ya se están revisando tus compras.')
        try:
            if 'qobuz' not in self.index.active():
                raise UserError('Agregá primero Qobuz.')
            return self.purchases.refresh(link)
        finally:
            self.sync_lock.release()

    def html(self, content):
        if 'youtube' not in self.index.active():
            raise UserError('Agregá primero YouTube Music.')
        items = import_home(content)
        with self.store.lock:
            if 'youtube' not in self.index.active():
                raise UserError('La fuente se eliminó.')
            self.index.merge_imports('youtube',items)
            self.set_option('home_html', self.index.imported('youtube'))
        return {'imported': len(items)}

    def refresh_home(self, rows, revision):
        try:
            items = live_home(rows, self.store.catalog)
            with self.store.lock:
                if revision == self.option('youtube_revision') and not self.store.stop_event.is_set():
                    self.set_option('home_live', {'time': time.time(), 'items': items})
        except Exception:
            with self.store.lock:
                if revision == self.option('youtube_revision'):
                    cache = self.option('home_live', {})
                    self.set_option('home_live', {**cache, 'time': time.time()-1500,
                        'warning': 'YouTube Music no pudo actualizar tu Inicio. Revisá tus cookies o importá el HTML.'})
        finally:
            self.home_lock.release()

    def home(self, refresh=False, uid=None):
        warning = ''
        with self.store.lock:
            revision = self.option('youtube_revision')
            rows = self.vault.read('youtube')
            cache = self.option('home_live', {})
        if rows and (refresh or time.time() - cache.get('time', 0) > 1800) and self.home_lock.acquire(False):
            if uid is not None:
                threading.Thread(target=self.refresh_home,args=(rows,revision),daemon=True,name='home-session').start()
            else:
                self.refresh_home(rows,revision)
                cache=self.option('home_live', {})
        warning=cache.get('warning','')
        sections = []
        if rows and revision == self.option('youtube_revision') and cache.get('items'):
            sections.append({'title': 'Para vos en YouTube Music', 'items': cache['items']})
        imported = self.index.imported('youtube')
        if imported:
            sections.append({'title': 'De tu página guardada', 'items': imported})
        with self.store.db() as db:
            purchases=[self.purchases.public_track(row[0]) for row in db.execute('SELECT metadata FROM qobuz_purchases ORDER BY rowid DESC LIMIT 45')]
        extras=[{**t,'source':'qobuz'} for t in purchases]
        extras+=self.index.rows()
        if extras:
            sections.append({'title':'De tus fuentes','items':extras})
        if uid is not None:
            from recommendations import for_store
            related, related_checking=for_store(self.store).related(uid,refresh)
        else:
            related, related_checking=self.related(refresh),False
        if related:
            sections.insert(0,{'title':'Por lo que escuchás y descargás','items':related})
        hidden=set(self.option('hidden_home',[]))
        favorites=self.option('favorite_artists',[])
        checking=self.recordings.sections(sections) or related_checking or self.home_lock.locked()
        prefs=self.option('source_preferences',{})
        for section in sections:
            visible=[t for t in section['items'] if prefs.get((t.get('source') or ('qobuz' if t['id'].startswith(('qb:','qa:')) else 'youtube')),{}).get('home',True)]
            section['items']=self.describe([t for t in visible if t['id'] not in hidden])
        return {'sections':[s for s in sections if s['items']], 'warning':warning,'checking':checking,'favorite_artists':favorites}

    def related(self,refresh):
        with self.store.db() as db:
            history=[json.loads(row[0]) for row in db.execute('SELECT metadata FROM files ORDER BY rowid DESC LIMIT 120')]
        from listening_collection import collection_for
        recent=collection_for(self.store).recent_artists()
        counts=Counter(n.split(';')[0].strip() for n in recent+[t['artist'] for t in history if t.get('artist','').strip()])
        favorites=self.option('favorite_artists',[])
        # Rotate the daily recommendation seeds; repeated songs by an artist count once.
        start=(int(time.time()//86400)*2)%max(1,len(favorites))
        rotated=favorites[start:]+favorites[:start]
        latest=[recent[0].split(';')[0].strip()] if recent else []
        seeds=list(dict.fromkeys(latest+[name for name,_ in counts.most_common(2)]))[:2]
        artists=list(dict.fromkeys(rotated[:2]+seeds))
        if not artists:
            return []
        cached=self.option('related_music',{})
        if 'youtube' not in self.index.active() or not self.option('source_preferences',{}).get('youtube',{}).get('home',True):
            rows=[]
        elif (not refresh and cached.get('artists')==artists and time.time()-cached.get('time',0)<cached.get('ttl',21600)) or not self.index.related_lock.acquire(False):
            rows=cached.get('items',[])
        else:
            try:
                rows=[]
                client=self.store.catalog.suggest_factory()
                for artist in artists:
                    for kind in ('songs','albums'):
                        for row in client.search(artist,filter=kind,limit=6)[:6]:
                            item=self.store.catalog.normalize(row)
                            if item and artist.casefold() in (a.strip().casefold() for a in item['artist'].split(';')):
                                thumbs=row.get('thumbnails') or []
                                rows.append({**item,'thumbnail':thumbs[-1].get('url','') if thumbs else '', 'source':'youtube','output_format':'mp3'})
                self.set_option('related_music',{'artists':artists,'time':time.time(),'items':rows})
            except Exception:
                rows=rows or (cached.get('items',[]) if cached.get('artists')==artists else [])
                self.set_option('related_music',{'artists':artists,'time':time.time(),'ttl':300,'items':rows})
            finally:
                session=getattr(locals().get('client'),'_session',None)
                if session and hasattr(session,'close'):
                    session.close()
                self.index.related_lock.release()
        owned={(t.get('artist','').casefold(),t.get('title','').casefold()) for t in history}
        other=self.index.rows()
        for artist in artists:
            other.extend(self.purchases.search(artist))
        return [t for t in rows+other if t.get('artist','').split(';')[0].strip().casefold() in {a.casefold() for a in artists}
                and (t.get('artist','').casefold(),t.get('title','').casefold()) not in owned]


    def selected(self, ids):
        if not 1 <= len(ids) <= 50 or len(set(ids)) != len(ids):
            raise UserError('Elegí de 1 a 50 pistas diferentes.')
        youtube = [ident for ident in ids if not QID.fullmatch(ident) and not EXID.fullmatch(ident)]
        known = {t['id']: t for t in self.store.catalog.selected(youtube)} if youtube else {}
        return [self.index.get(i) if EXID.fullmatch(i) else self.purchases.get(i) if QID.fullmatch(i) else known[i] for i in ids]

    def selection(self, choices, mode):
        planned = self.plan(self.selected([x.id for x in choices]), mode)
        if any(c.expected_format and c.expected_format != t['output_format'] for c, t in zip(choices, planned)):
            raise UserError('Cambió el formato disponible. Volvé a abrir la selección antes de guardar.')
        return planned

    def resolve(self,track,active,prefs,best,mode='auto',match_purchases=True):
        ident=track['id']
        key=track.get('source') or ('qobuz' if ident.startswith(('qa:','qb:')) else 'youtube')
        if key not in active:
            return None
        off=set(prefs.get(key,{}).get('off',[]))
        if track.get('reference') or track.get('type','song')!='song':
            if off and key=='qobuz' and ident.startswith('qa:'):
                album=self.purchases.album_preview(ident=ident)
                if not any(track_formats(t)-off for t in album['tracks']):
                    return None
            elif off and ('mp3' in off or set(CATALOG.get(key,()))<=off and key in CATALOG):
                # An HTML reference is not evidence that a lossless edition exists.
                return None
            return {**track,'source':key}
        offer=None
        if key=='qobuz':
            options=track_formats({**track,'native_format':track.get('native_format','FLAC')})-off
        elif key=='youtube':
            options={'mp3'}-off
            if match_purchases and 'qobuz' in active and 'flac' not in prefs.get('qobuz',{}).get('off',[]):
                offer=self.purchases.match(track)
                if offer and offer.get('native_format','FLAC')=='FLAC':
                    options.add('flac')
        else:
            options=track_formats(track)-off
        fmt=prefer(options,best) if mode in ('auto','original') else mode
        if fmt not in options:
            return None
        return {**track,'source':key,'has_flac':'flac' in options,'formats':[f for f in ORDER if f in options],
                'output_format':fmt,'only_qobuz':key=='qobuz',
                'flac_id':offer['id'] if offer and 'flac' in options else ident if key=='qobuz' and 'flac' in options else None}

    def describe(self,tracks):
        active=set(self.index.active())
        prefs=self.option('source_preferences',{})
        best=self.option('best_quality',True)
        with self.store.db() as db:
            match=bool(db.execute('SELECT 1 FROM qobuz_purchases LIMIT 1').fetchone())
        with self.store.db() as db:
            art=dict(db.execute('SELECT id,cover FROM custom_art'))
        result=[]
        for track in tracks:
            item=self.resolve(track,active,prefs,best,match_purchases=match)
            if item:
                if item['id'] in art:
                    item={**item,'original_cover':item.get('cover',''),'cover':art[item['id']]}
                result.append(item)
        saved=self.store.saved_ids(k for t in result for k in (t['id'],t.get('flac_id')))
        for t in result:
            t['downloaded']=t['id'] in saved or t.get('flac_id') in saved
        return result

    def plan(self,tracks,mode):
        if mode not in (*ORDER,'auto','original'):
            raise UserError('Formato no válido.')
        active=set(self.index.active())
        prefs=self.option('source_preferences',{})
        best=self.option('best_quality',True) or mode=='original'
        result=[]
        for track in tracks:
            item=self.resolve(track,active,prefs,best,mode)
            if not item or not item.get('output_format'):
                raise UserError('La pista no ofrece un formato habilitado para esta fuente.')
            if item['source']=='youtube' and item['output_format']=='flac':
                offer=self.purchases.get(item['flac_id'])
                item={**offer,'source':'qobuz','provider':'Qobuz','output_format':'flac','youtube_id':track['id'],
                      'cover':offer.get('cover') or track.get('cover','')}
            elif item['source'] in ('youtube','qobuz'):
                item['provider']=title_for(item['source'])
            result.append(item)
        return result
