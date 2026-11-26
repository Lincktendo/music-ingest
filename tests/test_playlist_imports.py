import json
import tempfile
import unittest
from pathlib import Path

from automation import Following
from core import Catalog, Store, UserError
from listening_collection import collection_for
from playlist_imports import import_follow


class PlaylistImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p=Path(self.tmp.name)
        self.store=Store(p/'data',p/'music',Catalog(p/'cache'))
        self.following=Following(None)
        self.follow=self.following.add(self.store,'playlist',
            'https://music.youtube.com/playlist?list=PLabcdefghijk1234',False)['id']
        self.collection=collection_for(self.store)

    def discover(self,ident,title):
        track={'id':ident,'title':title,'artist':'Uno; Dos','album':'Disco','cover':''}
        with self.store.db() as db:
            db.execute('INSERT INTO auto_tracks VALUES(?,?,NULL,1)',(ident,json.dumps(track)))
            db.execute('INSERT INTO follow_tracks VALUES(?,?)',(self.follow,ident))
            db.execute('UPDATE follows SET title=?,initialized=1 WHERE id=?',('Mi lista',self.follow))

    def test_waits_for_discovery_and_preserves_order_without_download(self):
        result=import_follow(self.store,'ana',self.follow)
        self.assertTrue(result['pending'])
        self.discover('fixture0001','Primera')
        self.discover('fixture0002','Segunda')
        page=self.collection.page('ana',result['id'],0)
        self.assertEqual([x['title'] for x in page['items']],['Primera','Segunda'])
        self.assertEqual(page['items'][0]['artist'],'Uno; Dos')
        self.assertEqual(import_follow(self.store,'ana',self.follow)['id'],result['id'])
        self.assertEqual(self.collection.lists('ana')['playlists'][0]['name'],'Mi lista · importada')
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0],0)

    def test_private_lists_deletion_and_incremental_updates(self):
        self.discover('fixture0001','Primera')
        first=import_follow(self.store,'ana',self.follow)['id']
        other=import_follow(self.store,'luis',self.follow)['id']
        self.assertNotEqual(first,other)
        with self.assertRaises(UserError):self.collection.page('luis',first,0)
        self.collection.set_entry('ana',first,'fixture0001',False)
        self.assertEqual(self.collection.page('ana',first,0)['items'],[])
        self.discover('fixture0002','Segunda')
        self.assertEqual([t['title'] for t in self.collection.page('ana',first,0)['items']],['Segunda'])
        self.collection.remove_list('ana',first)
        self.assertEqual(self.collection.lists('ana')['playlists'],[])

    def test_rejects_unknown_follow(self):
        with self.assertRaises(UserError):import_follow(self.store,'ana','missing')
