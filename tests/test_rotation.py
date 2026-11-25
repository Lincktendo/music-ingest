import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core import Catalog, Store, UserError
from rotation import Rotation, RotationSettings, Navidrome

TRACK={'id':'BaW_jenozKc','title':'Song','artist':'Example','album':'Album','output_format':'mp3'}

class RotationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.store=Store(self.root/'data',self.root/'music',Catalog(self.root/'catalog'))
        self.rotation=Rotation(SimpleNamespace(music=self.root/'music'))
        self.rotation.setup(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def song(self, path, **extra):
        stat=path.stat()
        return {'id':'song','path':'virtual/album/song.mp3','size':stat.st_size,
                'verified_file':True,'local_stamp':(stat.st_size,stat.st_mtime_ns,stat.st_ino),**extra}

    def connect(self,cleanup=False):
        return self.rotation.update(self.store,RotationSettings(enabled=True,cleanup=cleanup,
            navidrome_url='http://navidrome:4533',username='listener',password='fake-private-password'))

    def completed(self,ident,created,track=TRACK):
        path=self.store.music/(ident+'.mp3')
        path.write_bytes(b'owned test file')
        with self.store.db() as db:
            payload=json.dumps({'format':'auto','tracks':[track]})
            db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?)',(ident,'completed',payload,100,'',created))
            db.execute('INSERT INTO rotation_batches VALUES(?,?,?)',(ident,ident,created))
            db.execute('INSERT INTO rotation_tracks VALUES(?,?,?,?,?,?)',(ident,track['id'],'mp3',ident,'pending',''))
            db.execute('INSERT INTO files VALUES(?,?,?,?,?)',(track['id'],'mp3',path.name,json.dumps(track),ident))
        self.rotation.reconcile(self.store)
        return path

    def test_password_is_replaced_by_scoped_token_and_nulls_do_not_corrupt_config(self):
        status=self.connect()
        self.assertTrue(status['credential_set'])
        self.assertNotIn('password',status)
        self.assertNotIn('token',status)
        self.assertNotIn('fake-private-password',(self.store.data/'navidrome-session.json').read_text())
        result=self.rotation.update(self.store,RotationSettings(interval_seconds=None,username=None))
        self.assertEqual(result['interval_seconds'],86400)
        self.assertEqual(result['username'],'listener')
        self.rotation.update(self.store,RotationSettings(navidrome_url='http://other:4533'))
        self.assertFalse(self.rotation.status(self.store)['credential_set'])

    def test_schedule_is_idempotent_and_preserves_existing_or_manual_inflight(self):
        config=self.connect()
        with patch.object(self.rotation,'candidates',return_value=[TRACK]):
            self.rotation.schedule(self.store,config)
            self.rotation.schedule(self.store,self.rotation.config(self.store))
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*) FROM rotation_tracks').fetchone()[0],1)
        new={**TRACK,'id':'other123456','youtube_id':'linked12345'}
        with self.store.db() as db:
            db.execute('INSERT INTO files VALUES(?,?,?,?,?)',('qb:3','flac','existing.flac',json.dumps({'youtube_id':'linked12345'}),'manual'))
        with patch.object(self.rotation,'candidates',return_value=[new]):
            self.rotation.schedule(self.store,self.rotation.config(self.store))
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM jobs').fetchone()[0],1)

    def test_cleanup_keeps_starred_and_unmatched_and_existing_files(self):
        config=self.connect(True)
        old=self.completed('old',10)
        newer=self.completed('new',20,{**TRACK,'id':'other123456'})
        personal=self.store.music/'personal.mp3'
        personal.write_bytes(b'personal')
        stars={'song':set(),'album':set(),'artist':set()}
        with patch.object(Navidrome,'snapshot',return_value=stars),patch.object(Navidrome,'exact_song',return_value=None):
            self.rotation.cleanup(self.store,config)
        self.assertTrue(old.is_file())
        with patch.object(Navidrome,'snapshot',return_value=stars),patch.object(Navidrome,'exact_song',return_value=self.song(old,starred='today')):
            self.rotation.cleanup(self.store,config)
        self.assertTrue(old.is_file())
        self.assertTrue(newer.is_file())
        self.assertTrue(personal.is_file())
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT state FROM rotation_tracks WHERE batch='old'").fetchone()[0],'kept')

    def test_cleanup_deletes_only_exact_owned_unstarred_file_after_new_batch(self):
        config=self.connect(True)
        old=self.completed('old',10)
        self.completed('new',20,{**TRACK,'id':'other123456'})
        stars={'song':set(),'album':set(),'artist':set()}
        with patch.object(Navidrome,'snapshot',return_value=stars),patch.object(Navidrome,'exact_song',return_value=self.song(old)):
            self.rotation.cleanup(self.store,config)
        self.assertFalse(old.exists())
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT state FROM rotation_tracks WHERE batch='old'").fetchone()[0],'removed')
            self.assertEqual(db.execute('SELECT count(*) FROM files').fetchone()[0],1)

    def test_network_or_credential_change_leaves_files(self):
        config=self.connect(True)
        old=self.completed('old',10)
        self.completed('new',20,{**TRACK,'id':'other123456'})
        with patch.object(Navidrome,'snapshot',side_effect=UserError('offline')):
            with self.assertRaises(UserError):
                self.rotation.cleanup(self.store,config)
        self.assertTrue(old.is_file())
        def change_config(*args):
            self.rotation.update(self.store,RotationSettings(cleanup=False))
            return self.song(old)
        with patch.object(Navidrome,'snapshot',return_value={'song':set(),'album':set(),'artist':set()}),patch.object(Navidrome,'exact_song',side_effect=change_config):
            self.rotation.cleanup(self.store,config)
        self.assertTrue(old.is_file())


    def test_virtual_path_match_requires_original_bytes_and_rejects_duplicates(self):
        from contextlib import nullcontext
        config=self.connect(True)
        local=self.store.music/'actual-name.mp3'
        local.write_bytes(b'original-track')
        song={**TRACK,'id':'navidrome-id','path':'Artist/Album/Virtual.mp3','size':local.stat().st_size}
        client=Navidrome(config,self.rotation.credentials(self.store))
        def reply(method,**kwargs):
            return {'searchResult3':{'song':[song]}} if method=='search3' else {'song':song}
        response=SimpleNamespace(status_code=200,iter_content=lambda count:iter([b'original-track']))
        with patch.object(client,'call',side_effect=reply),patch('rotation.requests.get',return_value=nullcontext(response)):
            found=client.exact_song(TRACK,'actual-name.mp3',local)
        self.assertTrue(found['verified_file'])
        wrong=SimpleNamespace(status_code=200,iter_content=lambda count:iter([b'different-song']))
        with patch.object(client,'call',side_effect=reply),patch('rotation.requests.get',return_value=nullcontext(wrong)):
            self.assertIsNone(client.exact_song(TRACK,'actual-name.mp3',local))
        duplicates={'searchResult3':{'song':[song,{**song,'id':'copy-id'}]}}
        with patch.object(client,'call',return_value=duplicates),patch('rotation.requests.get') as request:
            self.assertIsNone(client.exact_song(TRACK,'actual-name.mp3',local))
            request.assert_not_called()
