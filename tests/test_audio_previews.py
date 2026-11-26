import json
from pathlib import Path
from subprocess import CompletedProcess
import tempfile
import unittest
from unittest.mock import patch

from core import Catalog,Store,UserError
from public_audio_worker import PreviewOnlyError,audio_metadata,is_preview_format,select_audio


FORMAT={'url':'https://media.example.test/song.mp3','protocol':'https','acodec':'mp3','vcodec':'none','ext':'mp3','format_id':'http_mp3'}


class PreviewTests(unittest.TestCase):
    def test_provider_preview_flags_and_stream_paths_are_rejected(self):
        previews=[{**FORMAT,'format_id':'hls_mp3_128_preview'},
                  {**FORMAT,'url':'https://media.example.test/playlist/0/30/token'},
                  {**FORMAT,'snipped':True},{**FORMAT,'format_note':'Preview'}]
        for sample in previews:
            self.assertTrue(is_preview_format(sample))
            with self.assertRaises(PreviewOnlyError):
                list(select_audio({'formats':[sample]}))
        self.assertEqual(list(select_audio({'formats':[FORMAT,*previews]})),[FORMAT])

    def test_short_complete_song_is_valid_and_keeps_metadata(self):
        info={'title':'Short interlude','duration':29,'formats':[FORMAT],**FORMAT,
              'artists':['Artist A','Artist B'],
              'thumbnails':[{'url':'https://i1.sndcdn.com/a-large.jpg','width':100},
                            {'url':'https://i1.sndcdn.com/a-original.jpg','preference':10}]}
        result=audio_metadata(info)
        self.assertTrue(result['full_audio_verified'])
        self.assertFalse(result['is_preview'])
        self.assertEqual(result['duration'],'29')
        self.assertEqual(result['artist'],'Artist A; Artist B')
        self.assertTrue(result['thumbnail'].endswith('-original.jpg'))
        with self.assertRaises(PreviewOnlyError):audio_metadata({**info,'availability':'needs_auth'})

    def test_download_length_mismatch_never_reaches_final_encode(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)
            store=Store(path/'data',path/'music',Catalog(path/'cache'))
            service=store.sources.index
            probe=CompletedProcess([],0,json.dumps({'streams':[{'codec_name':'mp3'}],'format':{'format_name':'mp3','duration':'29.75'}}))
            with patch.object(service.sources.vault,'read',return_value='https://example.org/track'), \
                 patch.object(service,'run',return_value={'duration':'250','full_audio_verified':True}), \
                 patch('source_catalog.subprocess.run',return_value=probe) as native:
                with self.assertRaisesRegex(UserError,'incompleto'):
                    service.download({'id':'ex:'+'a'*32},path,'mp3')
                self.assertEqual(native.call_count,1)


if __name__=='__main__':unittest.main()
