import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core import Catalog, Store, UserError
from home_recordings import recording
from music_home import ATV
from recommendations import algorithm, for_store, record_search, text_query

ART='https://lh3.googleusercontent.com/fixture=w544-h544'
SONG={'id':'fixture_A01','type':'song','title':'Amanecer','artist':'Artista Uno','album':'Disco',
      'cover':'','video_type':ATV,'thumbnail':ART}


class RecommendationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        root=Path(self.tmp.name)
        self.store=Store(root/'data',root/'music',Catalog(root/'cache'))
        self.service=for_store(self.store)

    def tearDown(self):
        self.store.stop_event.set()
        self.wait(lambda:not self.service.flights and not self.service.genre_flight)
        self.tmp.cleanup()

    def wait(self,condition):
        until=time.monotonic()+3
        while not condition():
            if time.monotonic()>until:self.fail('background task did not finish')
            time.sleep(.01)

    def test_search_history_is_private_deduplicated_and_never_records_links(self):
        record_search(self.store,'ana','  Jazz  de noche ')
        record_search(self.store,'ana','JAZZ de noche')
        record_search(self.store,'bob','Rock')
        for link in ('https://qobuz.com/album/123','music.youtube.com/watch?v=abc','/watch?v=123','spotify:track:123','www.soundcloud.com/x'):
            self.assertFalse(record_search(self.store,'ana',link))
        self.assertEqual([r['query'] for r in self.service.history('ana')['items']],['Jazz de noche'])
        ident=self.service.history('ana')['items'][0]['id']
        self.service.forget('bob',ident)
        self.assertEqual(len(self.service.history('ana')['items']),1)
        self.service.forget('ana',ident)
        self.assertEqual(self.service.history('ana'),{'items':[]})
        self.assertEqual(self.service.history('bob')['items'][0]['query'],'Rock')

    def test_algorithm_is_validated_data_not_code(self):
        self.assertEqual(algorithm('')[1]['likes'],8)
        self.assertEqual(algorithm('{"likes":15}')[1]['search'],3)
        for raw in ('[]','null','{}','{"exec":"evil()"}','{"search":true}','{"search":-1}',
                    '{"search":NaN}','{"likes":21}','lambda: 7',json.dumps(dict.fromkeys(('search','plays','likes','downloads','genres'),0))):
            with self.assertRaises(UserError):algorithm(raw)
        self.service.configure('ana','{"plays":7}')
        self.assertEqual(self.service.settings('bob')['algorithm'],'')

    def test_only_own_listens_and_likes_seed_home(self):
        with self.store.db() as db:
            db.execute('INSERT INTO listening_history VALUES(?,?,?,?,?)',('ana','fixture_A01','Ana Artist',time.time(),1))
            db.execute('INSERT INTO listening_history VALUES(?,?,?,?,?)',('bob','fixture_B02','Private Bob Artist',time.time(),1))
            for ident in ('fixture_B02','fixture_C03'):
                db.execute('INSERT INTO listening_entries VALUES(?,?,?,?,?)',('ana','favorites',ident,json.dumps({'artist':'Liked Artist'}),time.time()))
        seeds=dict(self.service.signals('ana'))
        self.assertNotIn('Private Bob Artist',seeds)
        self.assertEqual(seeds['Liked Artist'],8)
        self.assertIn('Ana Artist',seeds)

    def test_home_is_nonblocking_and_deleted_search_cannot_resurrect_cache(self):
        self.service.search('ana','Jazz')
        entered,release=threading.Event(),threading.Event()
        def search(query,filter,limit):
            entered.set();release.wait(2)
            return [{'videoId':'fixture_A01','videoType':ATV,'title':'Amanecer','artists':[{'name':'Jazz'}],
                     'thumbnails':[{'url':ART}]}] if filter=='songs' else []
        with patch.object(self.store.catalog,'suggest_factory') as factory:
            factory.return_value.search.side_effect=search
            began=time.monotonic();items,checking=self.service.related('ana')
            self.assertLess(time.monotonic()-began,.5)
            self.assertTrue(checking);self.assertEqual(items,[]);self.assertTrue(entered.wait(1))
            self.service.forget('ana')
            release.set();self.wait(lambda:not self.service.flights)
            with self.store.db() as db:
                self.assertIsNone(db.execute('SELECT * FROM discovery_cache WHERE user=?',('ana',)).fetchone())

    def test_actual_album_art_survives_but_video_thumbnail_does_not(self):
        album={'id':'MPREb123456','type':'album','thumbnail':ART,'title':'Álbum'}
        self.assertIsNotNone(recording(album))
        self.assertIsNone(recording({**album,'id':'playlist123'}))
        self.assertIsNone(recording({**album,'thumbnail':'https://i.ytimg.com/vi/a/hqdefault.jpg'}))
        self.assertIsNone(recording({**SONG,'video_type':'MUSIC_VIDEO_TYPE_OMV'}))
        sections=[{'items':[album,SONG]}]
        self.store.sources.recordings.sections(sections)
        self.assertEqual([x['type'] for x in sections[0]['items']],['album','song'])

    def test_genres_use_configured_api_cache_and_persist_clicks(self):
        config={'navidrome_url':'http://navidrome:4533','username':'test'}
        creds={'url':config['navidrome_url'],'username':'test','token':'test-token','salt':'test-salt'}
        self.service.rotation=SimpleNamespace(config=lambda store:config,credentials=lambda store:creds)
        entered,release=threading.Event(),threading.Event()
        def get(method):
            self.assertEqual(method,'getGenres');entered.set();release.wait(2)
            return {'genres':{'genre':[{'value':'Jazz','songCount':9},{'value':'Rock','songCount':5}]}}
        with patch('rotation.Navidrome.call',side_effect=get) as call:
            began=time.monotonic();first=self.service.genres('ana')
            self.assertLess(time.monotonic()-began,.5);self.assertTrue(first['checking'])
            self.assertTrue(entered.wait(1));release.set();self.wait(lambda:not self.service.genre_flight)
            self.assertEqual(set(self.service.genres('ana')['items']),{'Jazz','Rock'})
            self.service.click_genre('ana','Jazz')
            self.assertEqual(call.call_count,1)
            self.assertIn('Jazz',dict(self.service.signals('ana')))
            self.assertNotIn('Jazz',dict(self.service.signals('bob')))
            with self.assertRaises(UserError):self.service.click_genre('ana','Unknown')
        creds['token']='changed'
        with patch.object(self.service,'refresh_genres'):
            self.assertEqual(self.service.genres('ana')['items'],[])
            self.service.genre_flight=False


if __name__=='__main__':unittest.main()
