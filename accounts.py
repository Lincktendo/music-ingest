"""Local accounts, library membership and durable approval transactions."""
from contextlib import contextmanager
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
import uuid

from core import Store, UserError

SESSION_SECONDS = 7 * 86400
COOKIE = 'mi_session'
NAME = re.compile(r'[a-z0-9_-]{3,32}\Z')
IDENT = re.compile(r'[a-f0-9]{32}\Z')


class AccessError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    value = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=32).hex()
    return salt + ':' + value


def password_valid(password, stored):
    try:
        return hmac.compare_digest(password_hash(password, stored.split(':')[0]), stored)
    except (ValueError, TypeError):
        return False


class Accounts:
    def __init__(self, data):
        self.data = Path(data)
        self.data.mkdir(parents=True, exist_ok=True)
        self.path = self.data / 'accounts.sqlite'
        self.lock = threading.RLock()
        self.dummy = password_hash('not-a-real-account-password')
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,username TEXT UNIQUE NOT NULL,display_name TEXT NOT NULL,password TEXT NOT NULL,created_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS libraries(id TEXT PRIMARY KEY,owner_id TEXT UNIQUE NOT NULL,name TEXT NOT NULL,auto_approve INTEGER NOT NULL DEFAULT 0,legacy INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS members(library_id TEXT NOT NULL,user_id TEXT NOT NULL,PRIMARY KEY(library_id,user_id));
            CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS api_keys(id TEXT PRIMARY KEY,library_id TEXT NOT NULL,name TEXT NOT NULL,hash TEXT UNIQUE NOT NULL,prefix TEXT NOT NULL,created_at REAL NOT NULL,last_used_at REAL,revoked_at REAL);
            CREATE TABLE IF NOT EXISTS attempts(bucket TEXT NOT NULL,at REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS attempts_lookup ON attempts(bucket,at);
            ''')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def throttle(self, address, username):
        now = time.time()
        buckets = ['ip:' + digest(address), 'user:' + digest(username.casefold())]
        with self.lock, self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM attempts WHERE at<?', (now - 300,))
            if any(db.execute('SELECT COUNT(*) FROM attempts WHERE bucket=?', (b,)).fetchone()[0] >= 15 for b in buckets):
                raise AccessError(429, 'Demasiados intentos. Esperá cinco minutos.')
            db.executemany('INSERT INTO attempts VALUES(?,?)', [(b, now) for b in buckets])

    def has_users(self):
        with self.db() as db:
            return bool(db.execute('SELECT 1 FROM users LIMIT 1').fetchone())

    def register(self, username, password, display_name=''):
        username = username.strip().lower()
        if not NAME.fullmatch(username):
            raise UserError('El usuario debe tener 3–32 letras minúsculas, números, guion o guion bajo.')
        if not 10 <= len(password) <= 256:
            raise UserError('Usá una contraseña de 10 a 256 caracteres.')
        display_name = (display_name.strip() or username)[:80]
        hashed = password_hash(password)
        uid, lid = uuid.uuid4().hex, uuid.uuid4().hex
        with self.lock, self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            count = db.execute('SELECT COUNT(*) FROM users').fetchone()[0]
            if count >= 100:
                raise UserError('Esta instancia alcanzó su límite de cuentas.')
            if db.execute('SELECT 1 FROM users WHERE username=?', (username,)).fetchone():
                raise UserError('Ese usuario ya existe.')
            db.execute('INSERT INTO users VALUES(?,?,?,?,?)', (uid, username, display_name, hashed, time.time()))
            db.execute('INSERT INTO libraries VALUES(?,?,?,?,?)', (lid, uid, 'Biblioteca de ' + display_name, 0, int(count == 0)))
        return self.user(uid)

    def login(self, username, password):
        with self.db() as db:
            row = db.execute('SELECT * FROM users WHERE username=?', (username.strip().lower(),)).fetchone()
        valid = password_valid(password, row['password'] if row else self.dummy)
        if not row or not valid:
            raise AccessError(401, 'Usuario o contraseña incorrectos.')
        return self.user(row['id'])

    def user(self, uid):
        with self.db() as db:
            row = db.execute('SELECT id,username,display_name FROM users WHERE id=?', (uid,)).fetchone()
        if not row:
            raise AccessError(401, 'Iniciá sesión.')
        return dict(row)

    def new_session(self, uid, previous=None):
        raw = secrets.token_urlsafe(32)
        with self.db() as db:
            db.execute('DELETE FROM sessions WHERE expires<?', (time.time(),))
            if previous:
                db.execute('DELETE FROM sessions WHERE hash=?', (digest(previous),))
            db.execute('INSERT INTO sessions VALUES(?,?,?)', (digest(raw), uid, time.time() + SESSION_SECONDS))
            # Keep a small bounded set per account, allowing several devices.
            db.execute('DELETE FROM sessions WHERE user_id=? AND hash NOT IN (SELECT hash FROM sessions WHERE user_id=? ORDER BY expires DESC LIMIT 20)', (uid, uid))
        return raw

    def logout(self, raw):
        if raw:
            with self.db() as db:
                db.execute('DELETE FROM sessions WHERE hash=?', (digest(raw),))

    def authenticate(self, cookie=None, authorization=None):
        if authorization is not None:
            if not authorization.startswith('Bearer ') or not 20 <= len(authorization) <= 256:
                raise AccessError(401, 'Clave de API no válida.')
            raw = authorization[7:]
            with self.db() as db:
                row = db.execute('SELECT * FROM api_keys WHERE hash=? AND revoked_at IS NULL', (digest(raw),)).fetchone()
                if not row:
                    raise AccessError(401, 'Clave de API no válida o revocada.')
                db.execute('UPDATE api_keys SET last_used_at=? WHERE id=?', (time.time(), row['id']))
            return {'kind': 'key', 'id': row['id'], 'library_id': row['library_id'], 'name': row['name']}
        if not cookie or len(cookie) > 256:
            raise AccessError(401, 'Iniciá sesión.')
        with self.db() as db:
            row = db.execute('SELECT user_id FROM sessions WHERE hash=? AND expires>?', (digest(cookie), time.time())).fetchone()
        if not row:
            raise AccessError(401, 'Tu sesión venció. Iniciá sesión otra vez.')
        return {'kind': 'user', **self.user(row['user_id'])}

    def libraries(self, uid):
        with self.db() as db:
            rows = db.execute('SELECT DISTINCT l.* FROM libraries l LEFT JOIN members m ON m.library_id=l.id WHERE l.owner_id=? OR m.user_id=? ORDER BY l.rowid', (uid, uid)).fetchall()
        return [self.public_library(r, uid) for r in rows]

    @staticmethod
    def public_library(row, uid):
        return {k: row[k] for k in ('id', 'name', 'owner_id')} | {'role': 'owner' if row['owner_id'] == uid else 'collaborator', 'auto_approve': bool(row['auto_approve'])}

    def resolve(self, actor, library=None, owner=False, allow_key=False):
        with self.db() as db:
            if actor['kind'] == 'key':
                if not allow_key:
                    raise AccessError(403, 'Esta clave solo permite consultar catálogo y proponer música.')
                if library and library != actor['library_id']:
                    raise AccessError(403, 'La clave no tiene acceso a esa biblioteca.')
                row = db.execute('SELECT * FROM libraries WHERE id=?', (actor['library_id'],)).fetchone()
                return dict(row) | {'role': 'agent'}
            if library:
                row = db.execute('SELECT * FROM libraries WHERE id=?', (library,)).fetchone()
            else:
                row = db.execute('SELECT * FROM libraries WHERE owner_id=?', (actor['id'],)).fetchone()
            if not row:
                raise AccessError(404, 'Biblioteca no encontrada.')
            is_owner = row['owner_id'] == actor['id']
            member = db.execute('SELECT 1 FROM members WHERE library_id=? AND user_id=?', (row['id'], actor['id'])).fetchone()
            if not is_owner and (owner or not member):
                raise AccessError(403, 'No tenés permiso para esta biblioteca.')
            return dict(row) | {'role': 'owner' if is_owner else 'collaborator'}

    def members(self, lid):
        with self.db() as db:
            rows = db.execute('SELECT DISTINCT u.id,u.username,u.display_name,l.owner_id FROM users u JOIN libraries l ON l.id=? LEFT JOIN members m ON m.library_id=l.id AND m.user_id=u.id WHERE u.id=l.owner_id OR m.user_id IS NOT NULL ORDER BY u.username', (lid,)).fetchall()
        return {'items': [{k: r[k] for k in ('id', 'username', 'display_name')} | {'role': 'owner' if r['id'] == r['owner_id'] else 'collaborator'} for r in rows]}

    def add_member(self, lid, username):
        with self.lock, self.db() as db:
            row = db.execute('SELECT id FROM users WHERE username=?', (username.strip(),)).fetchone()
            if not row:
                raise UserError('Ese usuario no está registrado. Escribí su usuario exacto.')
            owner = db.execute('SELECT owner_id FROM libraries WHERE id=?', (lid,)).fetchone()[0]
            if owner == row['id']:
                raise UserError('Ya sos el dueño de esta biblioteca.')
            db.execute('INSERT OR IGNORE INTO members VALUES(?,?)', (lid, row['id']))
        return {'ok': True}

    def remove_member(self, lid, uid):
        with self.db() as db:
            if db.execute('SELECT owner_id FROM libraries WHERE id=?', (lid,)).fetchone()[0] == uid:
                raise UserError('No se puede quitar al dueño.')
            db.execute('DELETE FROM members WHERE library_id=? AND user_id=?', (lid, uid))
        return {'ok': True}

    def settings(self, lid, auto_approve):
        with self.db() as db:
            db.execute('UPDATE libraries SET auto_approve=? WHERE id=?', (int(auto_approve), lid))

    def keys(self, lid):
        with self.db() as db:
            rows = db.execute('SELECT id,name,prefix,created_at,last_used_at,revoked_at FROM api_keys WHERE library_id=? ORDER BY created_at DESC', (lid,)).fetchall()
        return {'items': [dict(r) for r in rows]}

    def create_key(self, lid, name):
        name = name.strip()
        if not name or len(name) > 80:
            raise UserError('Elegí un nombre de 1–80 caracteres para la clave.')
        token = 'mi_' + secrets.token_urlsafe(32)
        item = {'id': uuid.uuid4().hex, 'name': name, 'prefix': token[:10], 'created_at': time.time()}
        with self.lock, self.db() as db:
            if db.execute('SELECT COUNT(*) FROM api_keys WHERE library_id=? AND revoked_at IS NULL', (lid,)).fetchone()[0] >= 20:
                raise UserError('Revocá una clave anterior antes de crear otra (máximo 20).')
            db.execute('INSERT INTO api_keys VALUES(?,?,?,?,?,?,NULL,NULL)', (item['id'], lid, name, digest(token), item['prefix'], item['created_at']))
        return item | {'token': token}

    def revoke_key(self, lid, ident):
        with self.db() as db:
            db.execute('UPDATE api_keys SET revoked_at=COALESCE(revoked_at,?) WHERE library_id=? AND id=?', (time.time(), lid, ident))
        return {'ok': True}


class Registry:
    def __init__(self, accounts, music, catalog):
        self.accounts, self.music, self.catalog = accounts, Path(music), catalog
        self.lock = threading.RLock()
        self.stores = {}
        self.running = False
        self.configure_store = lambda library_id, store: None

    def get(self, lid):
        if not IDENT.fullmatch(lid or ''):
            raise AccessError(404, 'Biblioteca no encontrada.')
        with self.lock:
            if lid in self.stores:
                return self.stores[lid]
            with self.accounts.db() as db:
                row = db.execute('SELECT * FROM libraries WHERE id=?', (lid,)).fetchone()
            if not row:
                raise AccessError(404, 'Biblioteca no encontrada.')
            data = self.accounts.data if row['legacy'] else self.accounts.data / 'libraries' / lid
            music = self.music if row['legacy'] else self.music / lid
            store = Store(data, music, self.catalog)
            with store.db() as db:
                db.execute('CREATE TABLE IF NOT EXISTS proposals(id TEXT PRIMARY KEY,actor TEXT NOT NULL,actor_name TEXT NOT NULL,status TEXT NOT NULL,payload TEXT NOT NULL,created_at REAL NOT NULL,job_id TEXT UNIQUE)')
            self.configure_store(lid, store)
            self.stores[lid] = store
            if self.running:
                store.start()
            return store

    def configure_all(self, callback):
        with self.lock:
            self.configure_store = callback
            for lid, store in self.stores.items():
                callback(lid, store)

    def start(self):
        with self.lock:
            if self.running:
                return
            with self.accounts.db() as db:
                ids = [r[0] for r in db.execute('SELECT id FROM libraries')]
            for lid in ids:
                self.get(lid)
            self.running = True
            for store in self.stores.values():
                store.stop_event.clear()
                store.start()

    def stop(self):
        with self.lock:
            for store in self.stores.values():
                store.stop()
            self.running = False


def actor_key(actor):
    return actor['kind'] + ':' + actor['id']


def approve_in_transaction(db, row):
    if row['status'] == 'approved':
        return row['job_id']
    if row['status'] != 'pending':
        raise UserError('Esta propuesta ya fue rechazada.')
    if db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0] >= 10:
        raise UserError('La cola está llena. Intentá aprobarla cuando termine una descarga.')
    job = uuid.uuid4().hex
    db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?)', (job, 'queued', row['payload'], 0, '', time.time()))
    db.execute("UPDATE proposals SET status='approved',job_id=? WHERE id=?", (job, row['id']))
    return job


def propose(store, library, actor, tracks, fmt):
    ident = uuid.uuid4().hex
    payload = json.dumps({'tracks': tracks, 'format': fmt}, ensure_ascii=False)
    with store.lock, store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute("SELECT COUNT(*) FROM proposals WHERE status='pending'").fetchone()[0] >= 200:
            raise UserError('Hay demasiadas propuestas pendientes. Esperá una revisión.')
        db.execute('INSERT INTO proposals VALUES(?,?,?,?,?,?,NULL)', (ident, actor_key(actor), actor.get('username') or actor.get('name') or 'Colaborador', 'pending', payload, time.time()))
        row = db.execute('SELECT * FROM proposals WHERE id=?', (ident,)).fetchone()
        job = approve_in_transaction(db, row) if library['auto_approve'] else None
    if job:
        store.event.set()
    return {'id': ident, 'kind': 'proposal', 'status': 'approved' if job else 'pending', 'job_id': job, 'library_id': library['id']}


def decide(store, library, ident, approve):
    with store.lock, store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM proposals WHERE id=?', (ident,)).fetchone()
        if not row:
            raise AccessError(404, 'Propuesta no encontrada.')
        if approve:
            job = approve_in_transaction(db, row)
            status = 'approved'
        else:
            if row['status'] == 'approved':
                raise UserError('Esta propuesta ya fue aprobada.')
            db.execute("UPDATE proposals SET status='rejected' WHERE id=?", (ident,))
            job, status = None, 'rejected'
    if job:
        store.event.set()
    return {'id': ident, 'status': status, 'job_id': job, 'library_id': library['id']}


def proposals(store, library, actor, ident=None):
    sql = 'SELECT p.*,j.status AS job_status,j.progress,j.error FROM proposals p LEFT JOIN jobs j ON j.id=p.job_id WHERE 1=1'
    params = []
    if library['role'] != 'owner':
        sql += ' AND p.actor=?'
        params.append(actor_key(actor))
    if ident:
        sql += ' AND p.id=?'
        params.append(ident)
    sql += ' ORDER BY p.created_at DESC LIMIT 200'
    with store.db() as db:
        rows = db.execute(sql, params).fetchall()
    items = []
    for row in rows:
        payload = json.loads(row['payload'])
        tracks = payload['tracks']
        title = tracks[0]['title'] + (f" + {len(tracks)-1} canciones" if len(tracks) > 1 else '')
        items.append({k: row[k] for k in ('id', 'status', 'created_at', 'actor_name', 'job_id', 'job_status')} | {'title': title, 'tracks': tracks, 'format': payload['format'], 'progress': row['progress'] or 0, 'error': row['error'] or '', 'library_id': library['id']})
    if ident:
        if not items:
            raise AccessError(404, 'Propuesta no encontrada.')
        return items[0]
    return {'items': items}


def scope_urls(value, lid):
    if isinstance(value, list):
        return [scope_urls(x, lid) for x in value]
    if isinstance(value, dict):
        return {k: (v + '?library=' + lid if k in ('url', 'lyrics_url') and isinstance(v, str) and v.startswith('/api/files/') else scope_urls(v, lid)) for k, v in value.items()}
    return value
