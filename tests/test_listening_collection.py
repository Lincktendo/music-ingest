"""Regression tests for private listening lists, Home seeds and upcoming metadata."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import Catalog, Store, UserError
from listening_collection import collection_for
from music_home import ATV


class ListeningCollectionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.store = Store(root / 'a', root / 'music', Catalog(root / 'cache'))
        self.service = collection_for(self.store)
        self.tracks = [{
            'id': f'fixture{i:04d}', 'type': 'song', 'title': f'Track {i}',
            'artist': 'Artista A' if i < 12 else 'Artista B', 'album': 'Álbum',
            'cover': '', 'duration': '3:05', 'ignored': 'private-test-field',
        } for i in range(20)]
        self.store.catalog.remember(self.tracks)

    def test_lists_and_favorites_are_personal_idempotent_and_persistent(self):
        s = self.service
        key = s.create('ana', '  Mi   lista  ')['id']
        self.assertEqual(s.create('ana', 'mi lista')['id'], key)
        self.assertNotEqual(s.create('luis', 'Mi lista')['id'], key)
        with self.assertRaises(UserError):
            s.set_entry('luis', key, self.tracks[0]['id'], True)
        for track in self.tracks[:13]:
            for _ in range(2):
                s.set_entry('ana', key, track['id'], True)
        s.set_entry('ana', 'favorites', self.tracks[1]['id'], True)
        self.assertEqual(s.lists('ana')['playlists'][0]['count'], 13)
        self.assertEqual(s.lists('luis')['favorites'], [])
        first = s.page('ana', key, 0, 10)
        self.assertEqual([t['title'] for t in first['items']], [t['title'] for t in self.tracks[:10]])
        self.assertEqual(first['next_offset'], 10)
        tail = s.page('ana', key, 0, 10, after=self.tracks[9]['id'])
        self.assertEqual([t['id'] for t in tail['items']], [t['id'] for t in self.tracks[10:13]])
        self.assertIsNone(tail['next_offset'])
        self.assertNotIn('private-test-field', json.dumps(tail))
        with self.assertRaises(UserError):
            s.page('luis', key, 0)
        s.remove_list('ana', key)
        reopen = Store(self.store.data, self.store.music, self.store.catalog)
        self.assertEqual(collection_for(reopen).lists('ana'), {'favorites':[self.tracks[1]['id']],'playlists':[]})
        with self.assertRaises(UserError):
            s.remove_list('ana', 'favorites')

    def test_local_upgrade_preserves_list_identity_and_never_deletes_the_file(self):
        s = self.service
        yt = self.tracks[0]['id']
        s.set_entry('ana', 'favorites', yt, True)
        file = self.store.music / 'cancion.flac'
        file.write_bytes(b'fixture')
        meta = {**self.tracks[0], 'id':'qb:999', 'youtube_id':yt, 'source':'qobuz'}
        with self.store.db() as db:
            db.execute('INSERT INTO files VALUES(?,?,?,?,?)', ('qb:999', 'flac', file.name, json.dumps(meta), 'example'))
        saved = s.page('ana', 'favorites', 0)['items'][0]
        self.assertEqual((saved['id'], saved['source_id'], saved['format']), (yt,'qb:999','flac'))
        self.assertTrue(saved['url'].startswith('/api/files/'))
        s.set_entry('ana', 'favorites', saved['id'], False)
        self.assertEqual(s.page('ana', 'favorites', 0)['items'], [])
        self.assertTrue(file.exists())

    def test_real_plays_seed_home_without_downloads(self):
        s = self.service
        s.played('guest', self.tracks[14]['id'], False)
        self.assertEqual(s.recent_artists(), [])
        s.played('owner', self.tracks[2]['id'], True)
        s.played('owner', self.tracks[2]['id'], True)
        self.assertEqual(s.recent_artists(), ['Artista A'])
        with patch.object(self.store.catalog, 'suggest_factory') as factory:
            factory.return_value.search.side_effect = lambda artist,filter,limit: [
                {'videoId':'another0001', 'resultType':'song','title':'Nueva', 'artists':[{'name':artist}]}
            ] if filter=='songs' else []
            result = self.store.sources.related(False)
            self.assertEqual([(t['artist'],t['title']) for t in result], [('Artista A','Nueva')])
            self.assertEqual(factory.return_value.search.call_count, 2)

    def test_radio_returns_up_to_ten_unique_unheard_songs_and_reuses_seed(self):
        ids = [t['id'] for t in self.tracks]
        art = [{'url':'https://lh3.googleusercontent.com/test=w240-h240'}]
        raw = [{'videoId':t['id'],'videoType':ATV,'title':t['title'],'artists':[{'name':t['artist']}],
                'thumbnail':art} for t in self.tracks]
        raw[-1]['videoType'] = 'MUSIC_VIDEO_TYPE_OMV'
        with patch.object(self.store.catalog, 'suggest_factory') as factory:
            factory.return_value.get_watch_playlist.return_value = {'tracks':raw}
            picks = self.service.next_tracks('ana', ids[0], [ids[1],ids[2]], 10)
            self.assertEqual(len({t['id'] for t in picks}),10)
            self.assertTrue(all(t['id'] not in {ids[0],ids[1],ids[2],ids[-1]} for t in picks))
            next_one = self.service.next_tracks('ana', ids[0], [t['id'] for t in picks], 1)
            self.assertEqual(len(next_one),1)
            factory.return_value.get_watch_playlist.assert_called_once()

    def test_reroll_in_a_playlist_never_draws_from_another_list(self):
        key = self.service.create('ana','Las mías')['id']
        for row in self.tracks[:14]:
            self.service.set_entry('ana',key,row['id'],True)
        skip = {t['id'] for t in self.tracks[:5]}
        rows = self.service.page('ana',key,0,10,shuffle=True,exclude=skip)['items']
        self.assertEqual({t['id'] for t in rows}, {t['id'] for t in self.tracks[5:14]})

    def test_auto_dj_criteria_are_confined_to_eligible_favorites_or_existing_files(self):
        ids = [t['id'] for t in self.tracks]
        self.service.set_entry('ana','favorites',ids[1],True)
        self.service.set_entry('luis','favorites',ids[2],True)
        for i in (3,4):
            filename = f'{i}.mp3'
            with self.store.db() as db:
                db.execute('INSERT INTO files VALUES(?,?,?,?,?)',
                           (ids[i],'mp3',filename,json.dumps(self.tracks[i]),'job'))
            if i==3:
                (self.store.music / filename).write_bytes(b'test-file')
        with patch.object(self.service,'station',side_effect=AssertionError('no online fallback')):
            favorites=self.service.next_tracks('ana',ids[0],[],10,criterion='favorites')
            self.assertEqual([t['id'] for t in favorites],[ids[1]])
            library=self.service.next_tracks('ana',ids[0],[],10,criterion='library')
            self.assertEqual([(t['id'],bool(t['url'])) for t in library],[(ids[3],True)])

    def test_auto_dj_strict_similarity_does_not_pad_with_unrelated_tracks(self):
        for i in (1,12):
            self.service.set_entry('ana','favorites',self.tracks[i]['id'],True)
        with patch.object(self.service,'station',return_value=[self.tracks[15]]):
            result=self.service.next_tracks('ana',self.tracks[0]['id'],[],10,criterion='similar',strict=True)
            self.assertEqual({t['id'] for t in result},{self.tracks[1]['id'],self.tracks[15]['id']})
            result=self.service.next_tracks('ana',self.tracks[0]['id'],[],10,criterion='favorites',strict=True)
            self.assertEqual([t['id'] for t in result],[self.tracks[1]['id']])

    def test_auto_dj_album_mode_continues_order_without_leaving_the_favorite_scope(self):
        season=[{**self.tracks[i],'track':i+1,'album_id':'same','album':'Primero'} for i in range(7)]
        self.store.catalog.remember(season)
        for i in (4,5,0,2,6,1):
            self.service.set_entry('ana','favorites',season[i]['id'],True)
        a=self.service.next_tracks('ana',self.tracks[-1]['id'],[],3,criterion='favorites',group='albums')
        self.assertEqual([t['track'] for t in a],[1,2,3])
        b=self.service.next_tracks('ana',a[0]['id'],[t['id'] for t in a],3,
                                   criterion='favorites',group='albums',tail=a[-1]['id'])
        self.assertEqual([t['track'] for t in b],[5,6,7])
