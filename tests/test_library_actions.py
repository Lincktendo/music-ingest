import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import Catalog, Store, UserError

TRACK = {'id':'BaW_jenozKc','title':'Example','artist':'Artist','album':'Album','track':1,'cover':''}
SECOND = 'new12345678'


def register_file(store, source=TRACK['id'], fmt='mp3', name='song.mp3', lyrics=None):
    path=store.music/name;path.parent.mkdir(exist_ok=True,parents=True);path.write_bytes(b'0123456789'*100)
    metadata={**TRACK,'id':source}
    if lyrics:metadata['lyrics_file']=lyrics
    with store.db() as db:
        db.execute('INSERT INTO files VALUES(?,?,?,?,?)',(source,fmt,name,json.dumps(metadata),'job'+source))
    return path


class LibraryActions(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.catalog=Catalog(self.root/'data');self.store=Store(self.root/'data',self.root/'music',self.catalog)

    def tearDown(self):self.tmp.cleanup()

    def test_delete_owned_audio_and_owned_sidecar_preserves_other_files(self):
        lyric=self.store.publish_lyrics(self.store.music/'song.mp3','[00:01] Example')
        audio=register_file(self.store,lyrics=lyric)
        personal=self.store.music/'personal.mp3';personal.write_bytes(b'personal')
        result=self.store.delete_file(TRACK['id'],'mp3')
        self.assertTrue(result['deleted']);self.assertFalse(audio.exists())
        self.assertFalse((self.store.music/lyric).exists());self.assertEqual(personal.read_bytes(),b'personal')
        self.assertEqual(self.store.library()['total'],0)

    def test_shared_sidecar_is_removed_only_with_last_reference(self):
        lyric=self.store.publish_lyrics(self.store.music/'song.mp3','[00:01] Example')
        register_file(self.store,lyrics=lyric);other=register_file(self.store,SECOND,name='second.mp3',lyrics=lyric)
        self.store.delete_file(TRACK['id'],'mp3')
        self.assertTrue((self.store.music/lyric).is_file());self.assertTrue(other.is_file())
        self.store.delete_file(SECOND,'mp3');self.assertFalse((self.store.music/lyric).exists())

    def test_user_preexisting_lyrics_never_deleted(self):
        lyric=self.store.music/'song.lrc';lyric.write_bytes(b'[00:01] Example\n')
        reused=self.store.publish_lyrics(self.store.music/'song.mp3','[00:01] Example')
        self.assertEqual(reused,'song.lrc');register_file(self.store,lyrics=reused)
        self.store.delete_file(TRACK['id'],'mp3');self.assertEqual(lyric.read_text(encoding='utf8'),'[00:01] Example\n')

    def test_active_download_cannot_be_deleted(self):
        audio=register_file(self.store)
        self.store.enqueue([TRACK],'mp3')
        with self.assertRaises(UserError):self.store.delete_file(TRACK['id'],'mp3')
        self.assertTrue(audio.exists());self.assertEqual(self.store.library()['total'],1)

    def test_unregistered_and_traversal_refused(self):
        personal=self.store.music/'personal.mp3';personal.write_bytes(b'keep')
        with self.assertRaises(UserError):self.store.delete_file(TRACK['id'],'mp3')
        outside=self.root/'private.mp3';outside.write_bytes(b'private')
        with self.store.db() as db:db.execute('INSERT INTO files VALUES(?,?,?,?,?)',(TRACK['id'],'mp3','../private.mp3',json.dumps(TRACK),'job'))
        with self.assertRaises(UserError):self.store.delete_file(TRACK['id'],'mp3')
        self.assertEqual(outside.read_bytes(),b'private');self.assertEqual(personal.read_bytes(),b'keep')

    def test_symlink_audio_refused(self):
        outside=self.root/'private.mp3';outside.write_bytes(b'private')
        try:(self.store.music/'song.mp3').symlink_to(outside)
        except OSError:self.skipTest('symlink permissions unavailable')
        with self.store.db() as db:db.execute('INSERT INTO files VALUES(?,?,?,?,?)',(TRACK['id'],'mp3','song.mp3',json.dumps(TRACK),'job'))
        with self.assertRaises(UserError):self.store.delete_file(TRACK['id'],'mp3')
        self.assertEqual(outside.read_bytes(),b'private')

    def test_library_pagination_does_not_hide_tracks_after_500(self):
        for index in range(503):register_file(self.store,f'v{index:010d}',name=f'{index}.mp3')
        first=self.store.library();second=self.store.library(offset=first['next_offset'])
        self.assertEqual(first['total'],503);self.assertEqual(len(first['items']),500)
        self.assertEqual(len(second['items']),3);self.assertIsNone(second['next_offset'])
        self.assertEqual(len({x['source_id'] for x in first['items']+second['items']}),503)
        self.assertTrue(all(x['format']=='mp3' and x['job_id'] for x in second['items']))

    def test_search_and_artist_remember_trusted_song_selection(self):
        row={'resultType':'song','videoId':TRACK['id'],'title':'Trusted','artists':[{'name':'Artist'}]}
        self.catalog.factory=lambda:SimpleNamespace(search=lambda *a,**k:[row],get_artist=lambda *a:{'name':'Artist','songs':{'results':[row]}})
        self.catalog.search('query','songs');self.assertEqual(self.catalog.selected([TRACK['id']])[0]['title'],'Trusted')
        self.catalog.cache.clear();self.catalog.artist('UC'+'a'*22)
        self.assertEqual(self.catalog.selected([TRACK['id']])[0]['title'],'Trusted')


class LibraryAPI(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        with patch.dict(os.environ,{'DATA_DIR':str(self.root/'data'),'MUSIC_DIR':str(self.root/'music'),'ALLOWED_HOSTS':'localhost'}):
            spec=importlib.util.spec_from_file_location('library_actions_app',Path(__file__).resolve().parents[1]/'app.py')
            self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)
        self.clients=[]
        self.owner,self.friend,self.stranger=[self.client() for _ in range(3)]
        for client,username in [(self.owner,'owner'),(self.friend,'friend'),(self.stranger,'stranger')]:
            result=await client.post('/api/auth/register',json={'username':username,'password':'safe-example-password'})
            self.assertEqual(result.status_code,201)
            if username=='owner':self.lid=result.json()['default_library']
        self.store=self.module.registry.get(self.lid)

    def client(self,**kwargs):
        client=httpx.AsyncClient(transport=httpx.ASGITransport(app=self.module.app),base_url='http://localhost:8511',**kwargs)
        self.clients.append(client);return client

    async def asyncTearDown(self):
        self.module.registry.stop()
        for client in self.clients:await client.aclose()
        self.tmp.cleanup()

    async def test_audio_range_and_owner_only_delete(self):
        audio=register_file(self.store,name='folder/song.mp3')
        page=await self.owner.get('/api/library',params={'limit':1});self.assertEqual(page.status_code,200)
        item=page.json()['items'][0];self.assertEqual(item['source_id'],TRACK['id'])
        playback=await self.owner.get(item['url'],headers={'Range':'bytes=10-19'})
        self.assertEqual(playback.status_code,206);self.assertEqual(playback.content,b'0123456789')
        self.assertEqual(playback.headers['content-range'],'bytes 10-19/1000')
        self.assertTrue(playback.headers['content-type'].startswith('audio/'))
        await self.owner.post(f'/api/libraries/{self.lid}/members',json={'username':'friend'})
        key=await self.owner.post(f'/api/libraries/{self.lid}/keys',json={'name':'Test AI'})
        agent=self.client(headers={'authorization':'Bearer '+key.json()['token']})
        endpoint=f'/api/library/{TRACK["id"]}/mp3'
        for client in (self.friend,self.stranger,agent):
            response=await client.request('DELETE',endpoint,params={'library':self.lid},json={})
            self.assertEqual(response.status_code,403);self.assertTrue(audio.is_file())
        deleted=await self.owner.request('DELETE',endpoint,json={});self.assertEqual(deleted.status_code,200)
        self.assertFalse(audio.exists());self.assertEqual((await self.owner.get(item['url'])).status_code,404)
        self.assertEqual((await self.owner.get('/api/library')).json()['items'],[])

    async def test_library_pagination_bounds(self):
        for query in ({'limit':501},{'limit':0},{'offset':-1}):
            self.assertEqual((await self.owner.get('/api/library',params=query)).status_code,422)
