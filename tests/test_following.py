import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Catalog, Store, UserError
from automation import Following, playlist_id
from storage import Folders, music_path

URL='https://music.youtube.com/playlist?list=PL1234567890abcd'
ARTIST='UC'+'a'*22

class FollowingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.catalog=Catalog(self.root/'data')
        self.store=Store(self.root/'data',self.root/'music',self.catalog)
        self.follow=Following(None)
        self.follow.setup(self.store)
        self.rows=[{'videoId':f'v{i:010d}','title':f'Song {i}','artists':[{'name':'Artist'}]} for i in range(65)]
        self.api=SimpleNamespace(get_playlist=lambda *a,**kw: {'title':'Example','tracks':self.rows})
        self.catalog.factory=lambda:self.api

    def tearDown(self): self.tmp.cleanup()

    def source(self,kind='playlist',follow_updates=True,include_existing=False):
        ident=self.follow.add(self.store,kind,URL if kind=='playlist' else ARTIST,follow_updates,include_existing)['id']
        return next(r for r in self.follow.listing(self.store)['items'] if r['id']==ident)

    def scan(self,row):
        with self.store.db() as db:db.execute('UPDATE follows SET next_check=0 WHERE id=?',(row['id'],))
        self.follow.scan(self.store,row)

    def count(self,table):
        with self.store.db() as db:return db.execute('SELECT count(*) FROM '+table).fetchone()[0]

    def test_large_playlist_queue_restart_and_dedup(self):
        row=self.source();self.scan(row);self.follow.drain(self.store)
        self.assertEqual(self.count('auto_tracks'),65)
        self.assertEqual(self.count('jobs'),10)
        self.follow.drain(self.store);self.assertEqual(self.count('jobs'),10)
        self.store=Store(self.root/'data',self.root/'music',self.catalog)
        self.follow=Following(None);self.follow.setup(self.store)
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM jobs WHERE status='queued'").fetchone()[0],10)
        for _ in range(7):
            with self.store.db() as db:db.execute("UPDATE jobs SET status='done'")
            self.follow.drain(self.store)
        self.assertEqual(self.count('jobs'),65)
        self.rows.reverse();self.scan(row);self.follow.drain(self.store)
        self.assertEqual(self.count('jobs'),65)
        self.rows.append({'videoId':'new12345678','title':'New'})
        self.scan(row);self.follow.drain(self.store)
        self.assertEqual(self.count('jobs'),66)
        self.rows=[];self.scan(row)
        self.assertEqual(self.count('jobs'),66)

    def test_pause_remove_leave_files_and_stop_backlog(self):
        row=self.source();self.scan(row)
        keep=self.store.music/'personal.mp3';keep.write_bytes(b'original')
        self.follow.update(self.store,row['id'],enabled=False)
        self.follow.drain(self.store);self.assertEqual(self.count('jobs'),0)
        self.follow.update(self.store,row['id'],remove=True)
        self.follow.drain(self.store);self.assertEqual(self.count('jobs'),0)
        self.assertEqual(keep.read_bytes(),b'original')

    def test_one_time_import_drains_all_tracks_but_never_rescans(self):
        row=self.source(follow_updates=False);self.scan(row);self.follow.drain(self.store)
        item=self.follow.listing(self.store)['items'][0]
        self.assertEqual(item['state'],'importing')
        self.assertEqual(item['track_count'],65)
        self.assertEqual(item['pending_tracks'],55)
        self.assertEqual(item['active_tracks'],10)
        self.assertFalse(item['follow_updates'])
        self.assertIsNone(item['next_check'])
        self.api.get_playlist=lambda *a,**k:self.fail('A completed snapshot was fetched again')
        self.follow.set_interval(self.store,60);self.scan(row)
        self.follow.update(self.store,row['id'],enabled=False)
        self.follow.update(self.store,row['id'],enabled=True)
        self.scan(row)
        with self.assertRaises(UserError):self.follow.update(self.store,row['id'],check=True)
        for _ in range(7):
            with self.store.db() as db:db.execute("UPDATE jobs SET status='completed'")
            self.follow.drain(self.store)
        self.assertEqual(self.count('jobs'),65)
        self.assertEqual(self.follow.listing(self.store)['items'][0]['state'],'imported')
        self.store=Store(self.root/'data',self.root/'music',self.catalog)
        self.follow=Following(None);self.follow.setup(self.store)
        self.scan(row)
        self.assertEqual(self.count('jobs'),65)
        self.assertFalse(self.follow.listing(self.store)['items'][0]['follow_updates'])

    def test_one_time_failed_snapshot_retries_before_initialization(self):
        original=self.api.get_playlist
        self.api.get_playlist=lambda *a,**k:(_ for _ in ()).throw(RuntimeError('temporary provider failure'))
        row=self.source(follow_updates=False);self.scan(row)
        item=self.follow.listing(self.store)['items'][0]
        self.assertEqual(item['state'],'error');self.assertFalse(item['initialized'])
        self.api.get_playlist=original;self.scan(row);self.follow.drain(self.store)
        self.assertEqual(self.count('auto_tracks'),65)
        self.assertEqual(self.follow.listing(self.store)['items'][0]['state'],'importing')

    def test_existing_playlists_migrate_to_following(self):
        old_store=Store(self.root/'old-data',self.root/'old-music',self.catalog)
        with old_store.db() as db:
            db.execute("CREATE TABLE follows(id TEXT PRIMARY KEY,kind TEXT NOT NULL,source_id TEXT NOT NULL,title TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1,initialized INTEGER NOT NULL DEFAULT 0,last_check REAL,next_check REAL NOT NULL DEFAULT 0,error TEXT NOT NULL DEFAULT '',UNIQUE(kind,source_id))")
            db.execute("INSERT INTO follows(id,kind,source_id,title,initialized) VALUES('legacy','playlist','PL1234567890abcd','My playlist',1)")
        manager=Following(None);item=manager.listing(old_store)['items'][0]
        self.assertTrue(item['follow_updates']);self.assertEqual(item['title'],'My playlist')
        self.assertEqual(item['state'],'following')
        second=Following(None);second.setup(old_store)
        self.assertEqual(len(second.listing(old_store)['items']),1)

    def test_duplicate_add_preserves_original_mode_and_failed_jobs_visible(self):
        self.rows=self.rows[:1]
        row=self.source(follow_updates=False)
        duplicate=self.follow.add(self.store,'playlist',URL,True)
        self.assertTrue(duplicate['already_following']);self.assertFalse(duplicate['follow_updates'])
        self.scan(row);self.follow.drain(self.store)
        with self.store.db() as db:db.execute("UPDATE jobs SET status='failed'")
        item=self.follow.listing(self.store)['items'][0]
        self.assertEqual(item['state'],'needs_retry');self.assertEqual(item['failed_tracks'],1)
        with self.assertRaises(UserError):self.follow.add(self.store,'artist',ARTIST,False)

    def test_artist_baseline_then_new_release_with_failed_retry(self):
        albums=[{'browseId':'MPREb_old123'}]
        self.api.get_artist=lambda *a:{'name':'Artist','albums':{'results':albums}}
        self.api.get_album=lambda *a:{'title':'New album','tracks':self.rows[:2]}
        row=self.source('artist');self.scan(row)
        self.assertEqual(self.count('auto_tracks'),0)
        albums.append({'browseId':'MPREb_new123'})
        good=self.api.get_album
        self.api.get_album=lambda *a:(_ for _ in ()).throw(RuntimeError('provider down'))
        self.scan(row)
        self.assertEqual(self.count('releases'),1)
        self.assertTrue(self.follow.listing(self.store)['items'][0]['error'])
        self.api.get_album=good;self.scan(row);self.follow.drain(self.store)
        self.assertEqual(self.count('releases'),2)
        self.assertEqual(self.count('jobs'),2)
        self.scan(row);self.follow.drain(self.store);self.assertEqual(self.count('jobs'),2)

    def artist_catalog(self):
        albums=[{'browseId':'MPREb_album1'},{'browseId':'MPREb_album2'}]
        self.api.get_artist=lambda *a:{'name':'Artist','albums':{'results':albums}}
        self.api.get_album=lambda ident:{'title':ident,'tracks':self.rows[:2] if ident=='MPREb_album1' else self.rows[1:3]}
        return albums

    def test_artist_include_current_catalogue_once_then_only_new_releases(self):
        albums=self.artist_catalog()
        row=self.source('artist',include_existing=True);self.scan(row);self.follow.drain(self.store)
        self.assertEqual(self.count('auto_tracks'),3)  # shared song across two albums deduplicated
        self.assertEqual(self.count('jobs'),3)
        item=self.follow.listing(self.store)['items'][0]
        self.assertTrue(item['include_existing']);self.assertTrue(item['existing_imported'])
        self.api.get_album=lambda *a:self.fail('Current catalogue was imported twice')
        self.scan(row);self.follow.drain(self.store);self.assertEqual(self.count('jobs'),3)
        albums.append({'browseId':'MPREb_album3'})
        self.api.get_album=lambda ident:{'title':'New','tracks':self.rows[3:4]}
        self.scan(row);self.follow.drain(self.store);self.assertEqual(self.count('jobs'),4)

    def test_existing_artist_upgrades_without_losing_history_or_redownloading(self):
        self.artist_catalog()
        row=self.source('artist');self.scan(row)
        self.assertEqual(self.count('releases'),2);self.assertEqual(self.count('auto_tracks'),0)
        upgraded=self.follow.add(self.store,'artist',ARTIST,True,True)
        self.assertTrue(upgraded['already_following']);self.assertTrue(upgraded['catalogue_queued'])
        self.assertEqual(upgraded['id'],row['id']);self.assertEqual(self.count('releases'),2)
        self.assertEqual(self.follow.listing(self.store)['items'][0]['state'],'pending')
        self.scan(row);self.follow.drain(self.store)
        self.assertEqual(self.count('jobs'),3)
        duplicate=self.follow.add(self.store,'artist',ARTIST,True,True)
        self.assertFalse(duplicate['catalogue_queued']);self.assertTrue(duplicate['existing_imported'])
        self.api.get_album=lambda *a:self.fail('Duplicate request fetched old albums')
        self.scan(row);self.assertEqual(self.count('jobs'),3)
        self.assertTrue(self.follow.add(self.store,'artist',ARTIST,True,False)['include_existing'])

    def test_catalogue_failure_does_not_mark_it_imported(self):
        self.artist_catalog();good=self.api.get_album
        row=self.source('artist',include_existing=True)
        self.api.get_album=lambda *a:(_ for _ in ()).throw(RuntimeError('provider down'))
        self.scan(row)
        item=self.follow.listing(self.store)['items'][0]
        self.assertFalse(item['existing_imported']);self.assertEqual(item['state'],'error')
        self.assertEqual(self.count('releases'),0);self.assertEqual(self.count('auto_tracks'),0)
        self.api.get_album=good;self.scan(row)
        self.assertTrue(self.follow.listing(self.store)['items'][0]['existing_imported'])
        self.assertEqual(self.count('auto_tracks'),3)

    def test_catalogue_upgrade_during_inflight_baseline_is_not_lost(self):
        self.artist_catalog();row=self.source('artist');fetch=self.follow.fetch
        def upgrade_during_fetch(store,source):
            result=fetch(store,source)
            self.follow.add(store,'artist',ARTIST,True,True)
            return result
        self.follow.fetch=upgrade_during_fetch;self.scan(row)
        item=self.follow.listing(self.store)['items'][0]
        self.assertTrue(item['include_existing']);self.assertFalse(item['existing_imported'])
        self.follow.fetch=fetch;self.scan(row);self.assertEqual(self.count('auto_tracks'),3)

    def test_catalogue_limit_is_explicit_and_commits_no_partial_library(self):
        self.artist_catalog();self.rows=[{'videoId':f'v{i:010d}','title':f'Song {i}'} for i in range(5001)]
        self.api.get_album=lambda *a:{'title':'Large','tracks':self.rows}
        row=self.source('artist',include_existing=True);self.scan(row)
        self.assertEqual(self.count('auto_tracks'),0);self.assertEqual(self.count('releases'),0)
        item=self.follow.listing(self.store)['items'][0]
        self.assertIn('5.000',item['error']);self.assertFalse(item['existing_imported'])
        with self.assertRaises(UserError):self.follow.add(self.store,'playlist',URL,True,True)

    def test_interval_default_minimum_and_manual_cooldown(self):
        row=self.source();self.assertEqual(self.follow.interval(self.store),86400)
        self.follow.set_interval(self.store,60);self.assertEqual(self.follow.interval(self.store),60)
        with self.assertRaises(UserError):self.follow.set_interval(self.store,1)
        self.scan(row)
        with self.assertRaises(UserError):self.follow.update(self.store,row['id'],check=True)
        self.assertTrue(self.follow.add(self.store,'playlist',URL)['already_following'])

    def test_private_and_arbitrary_urls_rejected(self):
        self.assertEqual(playlist_id(URL),'PL1234567890abcd')
        for url in ('http://music.youtube.com/playlist?list=PL1234567890abcd','https://127.0.0.1/playlist?list=PL1234567890abcd','https://evil@youtube.com/playlist?list=PL1234567890abcd','https://music.youtube.com/playlist?list=LM','https://youtube.com:8510/playlist?list=PL1234567890abcd'):
            with self.subTest(url=url),self.assertRaises(UserError):playlist_id(url)

    def test_oversize_playlist_reports_error_without_partial_commit(self):
        self.api.get_playlist=lambda *a,**k:{'title':'Too big','trackCount':5001,'tracks':self.rows}
        row=self.source();self.scan(row)
        self.assertEqual(self.count('auto_tracks'),0)
        self.assertIn('5.000',self.follow.listing(self.store)['items'][0]['error'])

    def test_folder_selection_is_confined_and_persisted(self):
        folders=Folders(self.store)
        folders.create('','Mi música');folders.create('Mi música','Rock')
        self.assertEqual(folders.select('Mi música/Rock')['selected'],'Mi música/Rock')
        for path in ('../data','/tmp','C:/Windows','a\\b','a'*32,'Mi música/../../data'):
            with self.subTest(path=path),self.assertRaises(ValueError):music_path(self.store.music,path)
        with self.assertRaises(ValueError):folders.create('','CON')
        self.assertEqual(Folders(self.store).browse()['selected'],'Mi música/Rock')

    def test_folder_symlink_denied(self):
        outside=self.root/'private';outside.mkdir()
        try:(self.store.music/'escape').symlink_to(outside,target_is_directory=True)
        except OSError:self.skipTest('symlink permission unavailable')
        with self.assertRaises(ValueError):Folders(self.store).select('escape')
        self.assertNotIn('escape',[r['name'] for r in Folders(self.store).browse()['items']])
