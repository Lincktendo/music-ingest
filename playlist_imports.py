"""Personal listening copies of playlists already imported by the library owner."""
import json
import time
from uuid import uuid4

from fastapi import Request
from pydantic import BaseModel, Field

from core import UserError, VIDEO_ID


def setup(store):
    with store.db() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS listening_imports(
            user TEXT NOT NULL, follow_id TEXT NOT NULL, list_id TEXT NOT NULL, cursor INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(user,follow_id))''')


def sync_imports(store, uid):
    """Copy verified discovery metadata, never refetch or enqueue a download."""
    setup(store)
    with store.lock, store.db() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='follows'").fetchone():
            return
        links = db.execute('''SELECT i.list_id,i.cursor,f.id,f.title,f.initialized
            FROM listening_imports i JOIN listening_lists l ON l.id=i.list_id AND l.user=i.user
            JOIN follows f ON f.id=i.follow_id WHERE i.user=?''', (uid,)).fetchall()
        from listening_collection import TRACK_FIELDS
        for link in links:
            rows = db.execute('''SELECT a.track_id,a.payload,t.rowid AS sequence
                FROM follow_tracks t JOIN auto_tracks a ON a.track_id=t.track_id
                WHERE t.follow_id=? AND t.rowid>? ORDER BY t.rowid LIMIT 5000''', (link['id'],link['cursor'])).fetchall()
            for row in rows:
                if not VIDEO_ID.fullmatch(row['track_id']):
                    continue
                raw = json.loads(row['payload'])
                meta = {k:raw[k] for k in TRACK_FIELDS if k in raw}
                meta.update(id=row['track_id'], type='song', source='youtube')
                cover = raw.get('cover','')
                if cover.startswith('/api/covers/'):
                    with store.catalog.lock:
                        art = store.catalog.cover_sources.get(cover.rsplit('/',1)[-1])
                    if art and store.catalog.valid_cover(art):
                        meta['art_source'] = art
                db.execute('INSERT OR IGNORE INTO listening_entries VALUES(?,?,?,?,?)',
                    (uid,link['list_id'],row['track_id'],json.dumps(meta,ensure_ascii=False),float(row['sequence'])))
            if rows:
                db.execute('UPDATE listening_imports SET cursor=? WHERE user=? AND follow_id=?',
                    (rows[-1]['sequence'],uid,link['id']))
            # Replace only our generated placeholder, never a user-chosen name.
            if link['initialized']:
                name = link['title'][:90] + ' · importada'
                exists = db.execute('SELECT 1 FROM listening_lists WHERE user=? AND name=? AND id!=?',
                    (uid,name,link['list_id'])).fetchone()
                if not exists:
                    db.execute("UPDATE listening_lists SET name=? WHERE user=? AND id=? AND name LIKE 'Playlist importada · %'",
                        (name,uid,link['list_id']))


def import_follow(store, uid, follow_id):
    from listening_collection import collection_for
    collection_for(store)
    setup(store)
    with store.lock, store.db() as db:
        source = db.execute("SELECT id FROM follows WHERE id=? AND kind='playlist'",(follow_id,)).fetchone()
        if not source:
            raise UserError('Primero agregá esa playlist desde el formulario de importación.')
        old = db.execute('''SELECT i.list_id FROM listening_imports i JOIN listening_lists l
            ON l.id=i.list_id AND l.user=i.user WHERE i.user=? AND i.follow_id=?''',(uid,follow_id)).fetchone()
        key = old[0] if old else uuid4().hex
        if not old:
            db.execute('INSERT INTO listening_lists VALUES(?,?,?,?)',
                (uid,key,'Playlist importada · '+key[:8],time.time()))
            db.execute('INSERT OR REPLACE INTO listening_imports(user,follow_id,list_id) VALUES(?,?,?)',(uid,follow_id,key))
    sync_imports(store,uid)
    return {'id':key,'pending':not bool(collection_for(store).page(uid,key,0,1)['items'])}


class ImportRequest(BaseModel):
    follow_id: str = Field(min_length=1,max_length=64)


def install_imports(app, access, registry, following):
    @app.post('/api/listening/import',status_code=201)
    def import_playlist(body:ImportRequest,request:Request,library:str|None=None):
        actor,lib = access(request,library,owner=True)
        store = registry.get(lib['id'])
        following.setup(store)
        return import_follow(store,actor['id'],body.follow_id)
