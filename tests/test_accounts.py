import concurrent.futures
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from accounts import AccessError, Accounts, Registry, decide, propose
from core import Catalog, Store

TRACK = {'id': 'BaW_jenozKc', 'title': 'Trusted title', 'artist': 'Artist', 'album': 'Album', 'cover': '', 'track': 1}


class AccountsAPI(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        runtime = Path(__file__).parent / '.runtime'
        runtime.mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=runtime)
        self.root = Path(self.tmp.name)
        with patch.dict(os.environ, {'DATA_DIR': str(self.root / 'data'), 'MUSIC_DIR': str(self.root / 'music'), 'ALLOWED_HOSTS': 'localhost'}):
            spec = importlib.util.spec_from_file_location('account_api_instance', Path(__file__).resolve().parents[1] / 'app.py')
            self.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.module)
        self.clients = []

    def client(self, **kwargs):
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.module.app), base_url='http://localhost:8511', **kwargs)
        self.clients.append(client)
        return client

    async def asyncSetUp(self):
        self.owner, self.friend, self.stranger = self.client(), self.client(), self.client()
        self.owner_info = (await self.register(self.owner, 'owner')).json()
        self.friend_info = (await self.register(self.friend, 'friend')).json()
        self.stranger_info = (await self.register(self.stranger, 'stranger')).json()
        self.lid = self.owner_info['default_library']
        self.module.catalog.remember([TRACK])

    async def register(self, client, name):
        response = await client.post('/api/auth/register', json={'username': name, 'password': 'safe-example-password'})
        self.assertEqual(response.status_code, 201, response.text)
        return response

    async def asyncTearDown(self):
        self.module.registry.stop()
        for client in self.clients:
            await client.aclose()
        self.tmp.cleanup()

    async def add_friend(self):
        response = await self.owner.post(f'/api/libraries/{self.lid}/members', json={'username': 'friend'})
        self.assertEqual(response.status_code, 200, response.text)

    async def key(self, name='Agent'):
        response = await self.owner.post(f'/api/libraries/{self.lid}/keys', json={'name': name})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    async def test_registration_owns_exactly_one_library_and_session_is_hashed(self):
        self.assertEqual(len(self.owner_info['libraries']), 1)
        self.assertEqual(self.owner_info['libraries'][0]['role'], 'owner')
        raw = self.owner.cookies['mi_session']
        with self.module.accounts.db() as db:
            session = db.execute('SELECT hash FROM sessions WHERE user_id=?', (self.owner_info['user']['id'],)).fetchone()[0]
            stored = db.execute('SELECT password FROM users LIMIT 1').fetchone()[0]
        self.assertNotEqual(raw, session)
        self.assertNotIn('safe-example-password', stored)
        response = await self.owner.post('/api/auth/login', json={'username': 'owner', 'password': 'safe-example-password'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('httponly', response.headers['set-cookie'].lower())
        self.assertIn('samesite=strict', response.headers['set-cookie'].lower())
        self.assertNotEqual(raw, self.owner.cookies['mi_session'])
        await self.owner.post('/api/auth/logout', json={})
        self.assertEqual((await self.owner.get('/api/auth/me')).status_code, 401)
        self.assertEqual((await self.client(headers={'cookie': 'mi_session=' + raw}).get('/api/auth/me')).status_code, 401)

    async def test_automation_and_folders_are_owner_only(self):
        await self.add_friend()
        key=await self.key()
        agent=self.client(headers={'authorization':'Bearer '+key['token']})
        for client in (self.friend,self.stranger,agent):
            for path in ('/api/following','/api/folders'):
                self.assertEqual((await client.get(path,params={'library':self.lid})).status_code,403)
            self.assertEqual((await client.patch('/api/following/settings',params={'library':self.lid},json={'seconds':60})).status_code,403)
            self.assertEqual((await client.post('/api/folders',params={'library':self.lid},json={'name':'Forbidden'})).status_code,403)
        self.assertEqual((await self.owner.post('/api/folders',json={'name':'Rock'})).status_code,201)
        self.assertEqual((await self.owner.patch('/api/folders',json={'path':'Rock'})).status_code,200)
        self.assertEqual((await self.owner.patch('/api/folders',json={'path':'../data'})).status_code,400)
        self.assertEqual((await self.owner.patch('/api/following/settings',json={'seconds':60})).status_code,200)
        self.assertEqual((await self.owner.patch('/api/following/settings',json={'seconds':1})).status_code,422)
        result=await self.owner.post('/api/following',json={'kind':'playlist','source':'https://music.youtube.com/playlist?list=PL1234567890abc'})
        self.assertEqual(result.status_code,201,result.text)
        ident=result.json()['id']
        self.assertEqual((await self.friend.request('DELETE','/api/following/'+ident,params={'library':self.lid},json={})).status_code,403)
        self.assertEqual((await self.owner.request('DELETE','/api/following/'+ident,json={})).status_code,200)

    async def test_library_isolation_and_removed_collaborator(self):
        created = await self.owner.post('/api/jobs', json={'tracks': [{'id': TRACK['id']}]})
        self.assertEqual(created.status_code, 201)
        self.assertEqual((await self.stranger.get('/api/jobs', params={'library': self.lid})).status_code, 403)
        self.assertEqual((await self.stranger.get('/api/jobs')).json()['items'], [])
        await self.add_friend()
        self.assertEqual(len((await self.friend.get('/api/jobs', params={'library': self.lid})).json()['items']), 1)
        await self.owner.request('DELETE', f"/api/libraries/{self.lid}/members/{self.friend_info['user']['id']}", json={})
        for path in ('/api/jobs', '/api/library', '/api/proposals', '/api/files/unknown/file.mp3'):
            self.assertEqual((await self.friend.get(path, params={'library': self.lid})).status_code, 403)

    async def test_collaborator_proposes_owner_approves_idempotently(self):
        await self.add_friend()
        body = {'tracks': [{'id': TRACK['id'], 'title': 'INJECTED'}]}
        response = await self.friend.post('/api/jobs', params={'library': self.lid}, json=body)
        self.assertEqual(response.status_code, 201, response.text)
        item = response.json()
        self.assertEqual(item['kind'], 'proposal')
        self.assertEqual(item['status'], 'pending')
        self.assertEqual((await self.owner.get('/api/jobs')).json()['items'], [])
        self.assertEqual((await self.friend.post(f"/api/proposals/{item['id']}/approve", params={'library': self.lid}, json={})).status_code, 403)
        first = await self.owner.post(f"/api/proposals/{item['id']}/approve", json={})
        second = await self.owner.post(f"/api/proposals/{item['id']}/approve", json={})
        self.assertEqual(first.json()['job_id'], second.json()['job_id'])
        jobs = (await self.owner.get('/api/jobs')).json()['items']
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]['title'], TRACK['title'])

    async def test_key_scope_own_proposals_and_immediate_revocation(self):
        key = await self.key()
        agent = self.client(headers={'authorization': 'Bearer ' + key['token']})
        for path in ('/api/jobs', '/api/library', '/api/auth/me', '/api/libraries', f'/api/libraries/{self.lid}/keys', '/api/files/job/secret.mp3'):
            self.assertEqual((await agent.get(path)).status_code, 403, path)
        self.assertEqual((await agent.post('/api/jobs', json={'tracks': [{'id': TRACK['id']}]})).status_code, 403)
        response = await agent.post('/api/proposals', json={'tracks': [{'id': TRACK['id']}]})
        self.assertEqual(response.status_code, 201)
        ident = response.json()['id']
        self.assertEqual((await agent.post(f'/api/proposals/{ident}/approve', json={})).status_code, 403)
        self.assertEqual((await agent.get('/api/proposals', params={'library': self.friend_info['default_library']})).status_code, 403)
        other = await self.key('Second')
        other_agent = self.client(headers={'authorization': 'Bearer ' + other['token']})
        self.assertEqual((await other_agent.get('/api/proposals')).json()['items'], [])
        self.assertEqual((await other_agent.get('/api/proposals/' + ident)).status_code, 404)
        listed = (await self.owner.get(f'/api/libraries/{self.lid}/keys')).text
        self.assertNotIn(key['token'], listed)
        self.assertNotIn('hash', listed)
        await self.owner.request('DELETE', f"/api/libraries/{self.lid}/keys/{key['id']}", json={})
        self.assertEqual((await agent.get('/api/proposals')).status_code, 401)

    async def test_only_owner_can_enable_auto_approval(self):
        await self.add_friend()
        key = await self.key()
        agent = self.client(headers={'authorization': 'Bearer ' + key['token']})
        for client in (self.friend, agent):
            self.assertEqual((await client.patch(f'/api/libraries/{self.lid}', json={'auto_approve': True})).status_code, 403)
        await self.owner.patch(f'/api/libraries/{self.lid}', json={'auto_approve': True})
        result = await agent.post('/api/proposals', json={'tracks': [{'id': TRACK['id']}]})
        self.assertEqual(result.json()['status'], 'approved')
        self.assertTrue(result.json()['job_id'])
        self.assertEqual(len((await self.owner.get('/api/jobs')).json()['items']), 1)

    async def test_file_and_lyrics_urls_keep_scope_and_cannot_cross_libraries(self):
        store = self.module.registry.get(self.lid)
        (store.music / 'sample.mp3').write_bytes(b'audiofixture')
        (store.music / 'sample.lrc').write_text('[00:01] lyrics')
        with store.db() as db:
            db.execute('INSERT INTO files VALUES(?,?,?,?,?)', (TRACK['id'], 'mp3', 'sample.mp3', json.dumps(TRACK | {'lyrics_file': 'sample.lrc'}), 'fixturejob'))
        payload = (await self.owner.get('/api/library')).json()['items'][0]
        self.assertIn('?library=' + self.lid, payload['url'])
        self.assertIn('?library=' + self.lid, payload['lyrics_url'])
        self.assertEqual((await self.owner.get(payload['url'])).status_code, 200)
        self.assertEqual((await self.owner.get(payload['lyrics_url'])).status_code, 200)
        self.assertEqual((await self.stranger.get(payload['url'])).status_code, 403)
        self.assertEqual((await self.stranger.get(payload['lyrics_url'])).status_code, 403)
        key = await self.key()
        agent = self.client(headers={'authorization': 'Bearer ' + key['token']})
        self.assertEqual((await agent.get(payload['lyrics_url'])).status_code, 403)
        wrong_library_url = payload['url'].replace(self.lid, self.stranger_info['default_library'])
        self.assertEqual((await self.stranger.get(wrong_library_url)).status_code, 404)

    async def test_unauthenticated_csrf_and_login_throttling(self):
        anonymous = self.client()
        self.assertEqual((await anonymous.get('/api/jobs')).status_code, 401)
        response = await anonymous.post('/api/auth/login', json={'username': 'owner', 'password': 'safe-example-password'}, headers={'origin': 'http://evil.com'})
        self.assertEqual(response.status_code, 403)
        for _ in range(15):
            response = await anonymous.post('/api/auth/login', json={'username': 'wrong', 'password': 'wrong-password'})
        self.assertEqual(response.status_code, 429)

    async def test_provider_settings_owner_only_and_secrets_never_returned(self):
        await self.add_friend()
        key = await self.key()
        agent = self.client(headers={'authorization': 'Bearer ' + key['token']})
        for client in (self.friend, agent, self.stranger):
            for method, body in (('GET', None), ('PATCH', {'providers': {'lastfm': {'enabled': True, 'api_key': 'a' * 32}}})):
                args = {'json': body} if body is not None else {}
                result = await client.request(method, '/api/integrations', params={'library': self.lid}, **args)
                self.assertEqual(result.status_code, 403, result.text)
        secret = 'a' * 32
        result = await self.owner.patch('/api/integrations', json={'providers': {'lastfm': {'enabled': True, 'api_key': secret}}})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertNotIn(secret, result.text)
        result = await self.owner.get('/api/integrations')
        self.assertEqual(result.status_code, 200)
        self.assertNotIn(secret, result.text)
        self.assertTrue(next(x for x in result.json()['providers'] if x['id'] == 'lastfm')['configured'])
        other = await self.stranger.get('/api/integrations')
        self.assertFalse(next(x for x in other.json()['providers'] if x['id'] == 'lastfm')['configured'])


class DurableApprovals(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.accounts = Accounts(self.root / 'data')
        self.catalog = Catalog(self.root / 'data')
        self.user = self.accounts.register('first', 'safe-example-password')
        self.actor = {'kind': 'user', **self.user}
        self.library = self.accounts.resolve(self.actor)
        self.registry = Registry(self.accounts, self.root / 'music', self.catalog)
        self.store = self.registry.get(self.library['id'])

    def tearDown(self):
        self.registry.stop()
        self.tmp.cleanup()

    def test_legacy_adoption_and_store_initialized_once(self):
        self.assertEqual(self.store.data, self.root / 'data')
        self.assertEqual(self.store.music, self.root / 'music')
        job = self.store.enqueue([TRACK], 'mp3')
        self.assertIs(self.registry.get(self.library['id']), self.store)
        self.assertEqual(self.store.jobs()['items'][0]['status'], 'queued')
        second = self.accounts.register('second', 'safe-example-password')
        secondlib = self.accounts.resolve({'kind': 'user', **second})
        other = self.registry.get(secondlib['id'])
        self.assertNotEqual(other.music, self.store.music)
        self.assertEqual(other.jobs()['items'], [])

    def test_concurrent_approval_and_restart_create_one_job(self):
        pending = propose(self.store, self.library, self.actor, [TRACK], 'mp3')
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: decide(self.store, self.library, pending['id'], True), range(12)))
        self.assertEqual(len({r['job_id'] for r in results}), 1)
        self.assertEqual(len(self.store.jobs()['items']), 1)
        registry2 = Registry(self.accounts, self.root / 'music', self.catalog)
        restarted = registry2.get(self.library['id'])
        result = decide(restarted, self.library, pending['id'], True)
        self.assertEqual(result['job_id'], results[0]['job_id'])
        self.assertEqual(len(restarted.jobs()['items']), 1)
        self.assertEqual(restarted.jobs()['items'][0]['status'], 'interrupted')

    def test_first_signup_preserves_existing_trial_downloads(self):
        root = self.root / 'existing-instance'
        catalog = Catalog(root / 'data')
        old = Store(root / 'data', root / 'music', catalog)
        path = old.music / 'preserved.mp3'
        path.write_bytes(b'existing user audio')
        with old.db() as db:
            db.execute('INSERT INTO files VALUES(?,?,?,?,?)', (TRACK['id'], 'mp3', path.name, json.dumps(TRACK), 'oldjob'))
        accounts = Accounts(root / 'data')
        user = accounts.register('legacyowner', 'safe-example-password')
        registry = Registry(accounts, root / 'music', catalog)
        library = accounts.resolve({'kind': 'user', **user})
        adopted = registry.get(library['id'])
        self.assertEqual(adopted.library()['items'][0]['name'], 'preserved.mp3')
        self.assertEqual(adopted.file_path('oldjob', 'preserved.mp3').read_bytes(), b'existing user audio')

    def test_queue_full_approval_rolls_back_and_rejection_is_final(self):
        pending = propose(self.store, self.library, self.actor, [TRACK], 'mp3')
        for _ in range(10):
            self.store.enqueue([TRACK], 'mp3')
        with self.assertRaises(ValueError):
            decide(self.store, self.library, pending['id'], True)
        with self.store.db() as db:
            row = db.execute('SELECT * FROM proposals WHERE id=?', (pending['id'],)).fetchone()
        self.assertEqual(row['status'], 'pending')
        self.assertIsNone(row['job_id'])
        decide(self.store, self.library, pending['id'], False)
        with self.assertRaises(ValueError):
            decide(self.store, self.library, pending['id'], True)

    def test_registry_worker_lifecycle_and_new_library_hook(self):
        configured = []
        self.registry.configure_all(lambda lid, store: configured.append(lid))
        with patch.object(Store, 'start') as start, patch.object(Store, 'stop') as stop:
            self.registry.start()
            self.registry.start()
            self.assertEqual(start.call_count, 1)
            other = self.accounts.register('second', 'safe-example-password')
            lid = self.accounts.resolve({'kind': 'user', **other})['id']
            self.registry.get(lid)
            self.assertEqual(start.call_count, 2)
            self.assertIn(lid, configured)
            self.registry.stop()
            self.assertEqual(stop.call_count, 2)


if __name__ == '__main__':
    unittest.main()
