"""Private discovery preferences and bounded, background-refreshed Home suggestions.

Navidrome genres use its public OpenSubsonic getGenres API, never its database.
The advanced algorithm is a small JSON weight map, not Python/JavaScript code.
"""
import hashlib
import json
import math
import random
import re
import threading
import time
from collections import Counter

from fastapi import Request
from pydantic import BaseModel, Field

from core import UserError
from listening_collection import collection_for
from music_home import album_art

DEFAULT_WEIGHTS = {'search': 3, 'plays': 4, 'likes': 8, 'downloads': 2, 'genres': 3}
WINDOW = 6 * 3600
WORKERS = threading.BoundedSemaphore(2)
LINK = re.compile(r'(?i)(?:https?://|www\.|^[a-z][a-z0-9+.-]*:|^/watch\?|(?:^|\s)(?:[a-z0-9-]+\.)+[a-z]{2,63}(?:/|\?|$))')


def text_query(value):
    if not isinstance(value, str):
        return ''
    value = ' '.join(value.split())
    return value if 2 <= len(value) <= 200 and not LINK.search(value) and not any(ord(c) < 32 for c in value) else ''


def algorithm(value):
    if not isinstance(value, str) or len(value) > 2000:
        raise UserError('Usá un objeto JSON de pesos o dejá el campo vacío.')
    if not value.strip():
        return '', dict(DEFAULT_WEIGHTS)
    try:
        data = json.loads(value)
    except (ValueError, RecursionError):
        raise UserError('El algoritmo debe ser JSON válido; no se ejecuta código.') from None
    if not isinstance(data, dict) or not data or set(data) - set(DEFAULT_WEIGHTS):
        raise UserError('Pesos permitidos: search, plays, likes, downloads y genres.')
    if any(type(n) not in (int, float) or not math.isfinite(n) or not 0 <= n <= 20 for n in data.values()):
        raise UserError('Cada peso debe ser un número entre 0 y 20.')
    weights = {**DEFAULT_WEIGHTS, **data}
    if not any(weights.values()):
        raise UserError('Dejá al menos un peso mayor que cero.')
    return json.dumps(data, ensure_ascii=False, indent=2), weights


def for_store(store, rotation=None):
    with store.lock:
        if not hasattr(store, 'recommendations'):
            store.recommendations = Recommendations(store)
        if rotation is not None:
            store.recommendations.rotation = rotation
        return store.recommendations


def record_search(store, uid, query):
    """Call for a real signed-in user's text search, never for a pasted URL/API key."""
    return for_store(store).search(uid, query)


class Recommendations:
    def __init__(self, store):
        self.store = store
        self.rotation = None
        self.lock = threading.RLock()
        self.flights = set()
        self.genre_flight = False
        self.epochs = Counter()
        self.retry_at = {}
        collection_for(store)
        with store.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS discovery_searches(
                    user TEXT NOT NULL, id TEXT NOT NULL, query TEXT NOT NULL,
                    recent REAL NOT NULL, count INTEGER NOT NULL, PRIMARY KEY(user,id));
                CREATE TABLE IF NOT EXISTS discovery_settings(user TEXT PRIMARY KEY, algorithm TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS discovery_genres(
                    user TEXT NOT NULL, genre TEXT NOT NULL, count INTEGER NOT NULL, recent REAL NOT NULL,
                    PRIMARY KEY(user,genre));
                CREATE TABLE IF NOT EXISTS discovery_cache(user TEXT PRIMARY KEY, signature TEXT NOT NULL,
                    refreshed REAL NOT NULL, payload TEXT NOT NULL);
            ''')

    def search(self, uid, query):
        query = text_query(query)
        if not uid or not query:
            return False
        ident = hashlib.sha256(query.casefold().encode()).hexdigest()[:24]
        with self.store.lock, self.store.db() as db:
            # Tab changes / double submits do not artificially amplify a preference.
            db.execute('''INSERT INTO discovery_searches VALUES(?,?,?,?,1) ON CONFLICT(user,id)
                DO UPDATE SET query=excluded.query,recent=excluded.recent,
                count=min(discovery_searches.count+1,100)
                WHERE discovery_searches.recent<excluded.recent-10''', (uid, ident, query, time.time()))
            db.execute('''DELETE FROM discovery_searches WHERE user=? AND id NOT IN
                (SELECT id FROM discovery_searches WHERE user=? ORDER BY recent DESC LIMIT 100)''', (uid, uid))
        return True

    def history(self, uid):
        with self.store.db() as db:
            return {'items': [dict(r) for r in db.execute(
                'SELECT id,query FROM discovery_searches WHERE user=? ORDER BY recent DESC LIMIT 12', (uid,))]}

    def forget(self, uid, ident=None):
        with self.store.lock, self.lock, self.store.db() as db:
            if ident:
                db.execute('DELETE FROM discovery_searches WHERE user=? AND id=?', (uid, ident))
            else:
                db.execute('DELETE FROM discovery_searches WHERE user=?', (uid,))
            db.execute('DELETE FROM discovery_cache WHERE user=?', (uid,))
            self.epochs[uid] += 1
        return self.history(uid)

    def settings(self, uid):
        with self.store.db() as db:
            row = db.execute('SELECT algorithm FROM discovery_settings WHERE user=?', (uid,)).fetchone()
        value, weights = algorithm(row[0] if row else '')
        return {'algorithm': value, 'weights': weights, 'defaults': DEFAULT_WEIGHTS}

    def configure(self, uid, value):
        value, _ = algorithm(value)
        with self.store.lock, self.lock, self.store.db() as db:
            db.execute('INSERT OR REPLACE INTO discovery_settings VALUES(?,?)', (uid, value))
            db.execute('DELETE FROM discovery_cache WHERE user=?', (uid,))
            self.epochs[uid] += 1
        return self.settings(uid)

    def signals(self, uid):
        weights = self.settings(uid)['weights']
        names, scores = {}, Counter()
        now = time.time()
        def add(name, weight):
            name = text_query(name)
            if name and weight > 0:
                key = name.casefold()
                names[key] = name
                scores[key] += weight
        with self.store.db() as db:
            searches = db.execute('SELECT query,recent,count FROM discovery_searches WHERE user=?', (uid,)).fetchall()
            plays = db.execute('SELECT artist,last_played FROM listening_history WHERE user=? AND contribute=1 ORDER BY last_played DESC LIMIT 80', (uid,)).fetchall()
            liked = db.execute("SELECT metadata FROM listening_entries WHERE user=? AND list_id='favorites' ORDER BY added DESC LIMIT 120", (uid,)).fetchall()
            files = db.execute('SELECT metadata FROM files ORDER BY rowid DESC LIMIT 120').fetchall()
            genres = db.execute('SELECT genre,count,recent FROM discovery_genres WHERE user=?', (uid,)).fetchall()
        for q, recent, count in searches:
            add(q, weights['search'] * (1 + math.log1p(count)) * 0.5 ** (max(0, now-recent)/(30*86400)))
        for artist, recent in plays:
            add(artist.split(';')[0].strip(), weights['plays'] * 0.5 ** (max(0, now-recent)/(14*86400)))
        # An artist gets one like bonus, regardless of how many of their songs were liked.
        for name in {json.loads(r[0]).get('artist', '').split(';')[0].strip() for r in liked}:
            add(name, weights['likes'])
        for name in self.store.sources.option('favorite_artists', []):
            add(name, weights['likes'])
        for row in files:
            add(json.loads(row[0]).get('artist', '').split(';')[0].strip(), weights['downloads'])
        for genre, count, _ in genres:
            add(genre, weights['genres'] * (1 + math.log1p(count)))
        # Keep the two strongest seeds, then rotate two others every six hours.
        ordered = scores.most_common(40)
        rotating = ordered[2:]
        random.Random(uid + ':' + str(int(now // WINDOW))).shuffle(rotating)
        return [(names[k], round(weight, 3)) for k, weight in ordered[:2]+rotating[:2]]

    def signature(self, uid, seeds):
        src = self.store.sources
        value = [[name for name, _ in seeds], self.settings(uid)['algorithm'], int(time.time()//WINDOW),
                 src.index.active(), src.option('source_preferences', {}), src.option('youtube_revision'),
                 self.epochs[uid]]
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    def related(self, uid, refresh=False):
        seeds = self.signals(uid)
        signature = self.signature(uid, seeds)
        with self.store.db() as db:
            row = db.execute('SELECT * FROM discovery_cache WHERE user=?', (uid,)).fetchone()
        cache = json.loads(row['payload']) if row else []
        allowed = ('youtube' in self.store.sources.index.active() and
                   self.store.sources.option('source_preferences', {}).get('youtube', {}).get('home', True))
        if not seeds or not allowed:
            return [], False
        stale = not row or row['signature'] != signature or time.time()-row['refreshed'] > WINDOW
        # Clicking refresh during a provider outage must not hammer it every six seconds.
        retry = time.time() >= self.retry_at.get(uid, 0) and (not row or time.time()-row['refreshed'] > 60)
        with self.lock:
            if (stale or refresh) and retry and uid not in self.flights and WORKERS.acquire(False):
                self.flights.add(uid)
                thread = threading.Thread(target=self.refresh, args=(uid, seeds, signature), daemon=True,
                                          name='home-recommendations')
                thread.start()
            checking = uid in self.flights
        return cache, checking

    def refresh(self, uid, seeds, signature):
        client = None
        try:
            client = self.store.catalog.suggest_factory()
            items, seen = [], set()
            for query, _ in seeds:
                if self.store.stop_event.is_set():
                    return
                for kind in ('songs', 'albums'):
                    for raw in client.search(query, filter=kind, limit=8)[:8]:
                        item = self.store.catalog.normalize({**raw, 'resultType': 'song' if kind=='songs' else 'album'})
                        if not item or item['id'] in seen:
                            continue
                        thumbs = raw.get('thumbnails') or raw.get('thumbnail') or []
                        art = next((album_art(t.get('url', '')) for t in reversed(thumbs)
                                    if isinstance(t, dict) and album_art(t.get('url', ''))), '')
                        if not art:
                            continue
                        seen.add(item['id'])
                        items.append({**item, 'thumbnail': art, 'source': 'youtube', 'output_format': 'mp3'})
            with self.store.lock, self.lock:
                if not self.store.stop_event.is_set() and self.signature(uid, self.signals(uid)) == signature:
                    with self.store.db() as db:
                        db.execute('INSERT OR REPLACE INTO discovery_cache VALUES(?,?,?,?)',
                                   (uid, signature, time.time(), json.dumps(items, ensure_ascii=False)))
                    self.retry_at.pop(uid, None)
        except Exception:
            # Keep a previous shelf visible. Never persist provider errors/cookies into Home.
            with self.store.lock, self.lock, self.store.db() as db:
                self.retry_at[uid] = time.time() + 300
                if self.signature(uid, self.signals(uid)) == signature:
                    db.execute('''INSERT INTO discovery_cache VALUES(?,?,?,?) ON CONFLICT(user)
                        DO UPDATE SET refreshed=excluded.refreshed''', (uid, signature, time.time()-WINDOW+300, '[]'))
        finally:
            session = getattr(client, '_session', None)
            if session and hasattr(session, 'close'):
                session.close()
            with self.lock:
                self.flights.discard(uid)
            WORKERS.release()

    def genre_config(self):
        if not self.rotation:
            return None, ''
        from rotation import Navidrome
        with self.store.lock:
            config, creds = self.rotation.config(self.store), self.rotation.credentials(self.store)
        try:
            client = Navidrome(config, creds)
        except UserError:
            return None, ''
        # Signature only, never put URL, username or credentials in a response.
        stamp = hashlib.sha256(json.dumps([config['navidrome_url'], config['username'],
                                         creds.get('token')]).encode()).hexdigest()
        return client, stamp

    def genres(self, uid):
        client, signature = self.genre_config()
        if not client:
            return {'items': [], 'connected': False, 'checking': False, 'warning': ''}
        cache = self.store.sources.option('discovery_navidrome_genres', {})
        valid = cache.get('signature') == signature
        stale = not valid or time.time()-cache.get('time', 0) > cache.get('ttl', WINDOW)
        with self.lock:
            if stale and not self.genre_flight:
                self.genre_flight = True
                threading.Thread(target=self.refresh_genres, args=(client, signature), daemon=True,
                                 name='home-genres').start()
            checking = self.genre_flight
        items = cache.get('items', []) if valid else []
        with self.store.db() as db:
            clicks = dict(db.execute('SELECT genre,count FROM discovery_genres WHERE user=?', (uid,)))
        # Deterministic weighted shuffle: no reordering while the user is browsing.
        rng = random.Random(uid + ':' + str(int(time.time()//WINDOW)))
        ranked = [(rng.random() ** (1/(1+3*math.log1p(clicks.get(name, 0)))), name) for name in items]
        ranked.sort(reverse=True)
        return {'items': [name for _, name in ranked[:12]], 'connected': True, 'checking': checking,
                'warning': cache.get('warning', '') if valid else ''}

    def refresh_genres(self, client, signature):
        try:
            result = client.call('getGenres').get('genres', {}).get('genre', [])
            names = sorted({text_query(row.get('value')) for row in result[:2000] if isinstance(row, dict)} - {''})
            cache = {'items': names, 'time': time.time(), 'signature': signature, 'ttl': WINDOW}
        except Exception:
            old = self.store.sources.option('discovery_navidrome_genres', {})
            cache = {'items': old.get('items', []) if old.get('signature')==signature else [],
                     'time': time.time(), 'signature': signature, 'ttl': 300,
                     'warning': 'No pude actualizar los géneros de Navidrome. Reintento en unos minutos.'}
        try:
            with self.store.lock:
                if not self.store.stop_event.is_set() and self.genre_config()[1] == signature:
                    self.store.sources.set_option('discovery_navidrome_genres', cache)
        finally:
            with self.lock:
                self.genre_flight = False

    def click_genre(self, uid, name):
        _, signature = self.genre_config()
        cache = self.store.sources.option('discovery_navidrome_genres', {})
        if not signature or cache.get('signature') != signature or name not in cache.get('items', []):
            raise UserError('Ese género ya no está disponible. Actualizá Inicio.')
        with self.store.lock, self.store.db() as db:
            db.execute('''INSERT INTO discovery_genres VALUES(?,?,1,?) ON CONFLICT(user,genre)
                DO UPDATE SET count=min(discovery_genres.count+1,100),recent=excluded.recent
                WHERE discovery_genres.recent<excluded.recent-2''', (uid, name, time.time()))
        return {'ok': True}


class AlgorithmSetting(BaseModel):
    algorithm: str = Field(default='', max_length=2000)


class GenreClick(BaseModel):
    genre: str = Field(min_length=2, max_length=200)


def install_recommendations(app, access, registry, rotation):
    def personal(request, library, owner=False):
        actor, lib = access(request, library, owner=owner)
        return for_store(registry.get(lib['id']), rotation), actor['id']

    @app.get('/api/recommendations/home')
    def home(request: Request, library: str | None = None, refresh: bool = False):
        service, uid = personal(request, library, owner=True)
        return {**service.store.sources.home(refresh, uid=uid), 'genres': service.genres(uid)}

    @app.get('/api/recommendations/history')
    def history(request: Request, library: str | None = None):
        service, uid = personal(request, library)
        return service.history(uid)

    @app.delete('/api/recommendations/history')
    def clear(request: Request, library: str | None = None):
        service, uid = personal(request, library)
        return service.forget(uid)

    @app.delete('/api/recommendations/history/{ident}')
    def remove(ident: str, request: Request, library: str | None = None):
        service, uid = personal(request, library)
        return service.forget(uid, ident)

    @app.get('/api/recommendations/settings')
    def settings(request: Request, library: str | None = None):
        service, uid = personal(request, library)
        return service.settings(uid)

    @app.patch('/api/recommendations/settings')
    def settings_update(body: AlgorithmSetting, request: Request, library: str | None = None):
        service, uid = personal(request, library)
        return service.configure(uid, body.algorithm)

    @app.post('/api/recommendations/genre')
    def genre(body: GenreClick, request: Request, library: str | None = None):
        service, uid = personal(request, library, owner=True)
        return service.click_genre(uid, body.genre)

    return {'record_search': record_search}
