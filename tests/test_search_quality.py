"""Search cards must represent complete recordings, not flat links or previews."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import Catalog, Store
from source_catalog import clean_search_results


SONG={'id':'fixture_A01','type':'song','title':'Una canción','artist':'Artista',
      'cover':'/api/covers/'+'a'*64,'source':'youtube','video_type':'MUSIC_VIDEO_TYPE_ATV'}


class SearchQualityTests(unittest.TestCase):
    def test_rejects_flat_references_missing_art_and_music_videos(self):
        rows=[SONG,{**SONG,'id':'no_art','cover':''},
              {**SONG,'id':'music_video','video_type':'MUSIC_VIDEO_TYPE_OMV'},
              {**SONG,'id':'ref:unknown','reference':True,'source':'soundcloud.com'},
              {**SONG,'id':'unknown','artist':''}]
        self.assertEqual(clean_search_results(rows,'songs'),[SONG])

    def test_filters_previews_without_banning_short_complete_songs(self):
        short={**SONG,'id':'short','duration':'0:29'}
        external={**short,'id':'external','source':'soundcloud.com','full_audio_verified':True}
        rows=[short,external,{**external,'id':'sample','is_preview':True},
              {**external,'id':'locked','availability':'needs_auth'},
              {**external,'id':'old','full_audio_verified':False}]
        self.assertEqual(clean_search_results(rows,'songs'),[short,external])

    def test_result_tab_and_source_identity_are_respected(self):
        album={**SONG,'id':'album','type':'album'}
        artist={**SONG,'id':'artist','type':'artist'}
        self.assertEqual(clean_search_results([SONG,album,artist],'albums'),[album])
        self.assertEqual(clean_search_results([SONG,album,artist],'artists'),[artist])
        other={**SONG,'source':'qobuz'}
        self.assertEqual(clean_search_results([SONG,SONG,other],'songs'),[SONG,other])

    def test_soundcloud_is_opt_in_and_keeps_verified_cover_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)
            store=Store(path/'data',path/'music',Catalog(path/'cache'))
            index=store.sources.index
            self.assertNotIn('soundcloud.com',index.active())
            index.add('soundcloud.com')
            self.assertIn('soundcloud.com',index.active())
            full={'title':'Song','artist':'Artist','url':'https://soundcloud.com/artist/song',
                  'thumbnail':'https://i1.sndcdn.com/artwork-fixture-t500x500.jpg',
                  'duration':245,'full_audio_verified':True,'is_preview':False}
            with patch.object(index,'run',return_value=[full,{**full,'url':full['url']+'-preview','is_preview':True}]):
                result=index.search_soundcloud('Artist')
            self.assertEqual(len(result),1)
            self.assertEqual(result[0]['duration'],245)
            self.assertTrue(result[0]['cover'].startswith('/api/covers/'))
            self.assertTrue(result[0]['full_audio_verified'])


if __name__=='__main__':
    unittest.main()
