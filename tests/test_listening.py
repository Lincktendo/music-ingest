import base64
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from mutagen.id3 import ID3
from core import Catalog, Store
from home_recordings import ATV, recording
from listening import listen, set_artwork

TRACK={'id':'fixture_001','title':'Track','artist':'Artist','type':'song','cover':''}


class ListeningTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root=Path(tmp.name)
        self.store=Store(root/'data',root/'music',Catalog(root/'global'))
        self.store.catalog.remember([TRACK])

    def image(self,color):
        out=io.BytesIO()
        Image.new('RGB',(128,128),color).save(out,'JPEG')
        return base64.b64encode(out.getvalue()).decode()

    def test_album_substitutes_its_own_audio_edition(self):
        from unittest.mock import Mock
        client=Mock()
        client.get_album.return_value={'title':'Same record','audioPlaylistId':'PLexample','tracks':[
            {'title':'Track','videoType':'MUSIC_VIDEO_TYPE_OMV','videoId':'fixture_002'}]}
        client.get_playlist.return_value={'tracks':[{'title':'Track','videoType':ATV,'videoId':TRACK['id']}]}
        self.store.catalog.factory=lambda:client
        tracks=self.store.catalog.preview('MPREb12345678','album')['tracks']
        self.assertEqual([t['id'] for t in tracks],[TRACK['id']])

    def test_music_video_and_rectangular_thumbnail_are_never_official_art(self):
        for kind in ('MUSIC_VIDEO_TYPE_OMV','MUSIC_VIDEO_TYPE_UGC',''):
            self.assertIsNone(recording({**TRACK,'video_type':kind,'thumbnail':'https://lh3.googleusercontent.com/test=w640-h640'}))
        for url in ('https://i.ytimg.com/vi/fixture_001/hqdefault.jpg','https://lh3.googleusercontent.com/test=w640-h360'):
            self.assertIsNone(recording({**TRACK,'video_type':ATV,'thumbnail':url}))
        self.assertIsNotNone(recording({**TRACK,'video_type':ATV,'thumbnail':'https://lh3.googleusercontent.com/test=w640-h640'}))

    @unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg needed')
    def test_temporary_listen_and_cover_before_and_after_download(self):
        def audio(folder,*unused):
            subprocess.run(['ffmpeg','-loglevel','error','-f','lavfi','-i','sine=frequency=230:duration=1',
                            str(folder/'audio.mp3')],check=True)
        store=self.store
        with patch.object(store,'download_youtube',side_effect=audio):
            first=listen(store,TRACK['id'])
            self.assertTrue(first.is_file())
            self.assertEqual(store.library()['items'],[])
            pre=set_artwork(store,TRACK['id'],self.image('blue'))['cover']
            self.assertEqual(store.sources.describe([TRACK])[0]['cover'],pre)
            store.download('example',TRACK,'mp3',lambda _:None)
        file=store.library()['items'][0]
        saved=store.music/file['name']
        old=ID3(saved)
        self.assertEqual(old['TIT2'].text,['Track'])
        self.assertEqual(old.getall('APIC')[0].data,(store.data/'artwork'/(pre.split('/')[-1]+'.jpg')).read_bytes())
        new=set_artwork(store,TRACK['id'],self.image('green'))['cover']
        self.assertNotEqual(new,pre)
        self.assertNotEqual(ID3(saved).getall('APIC')[0].data,old.getall('APIC')[0].data)
        self.assertEqual(ID3(saved)['TIT2'].text,['Track'])
        self.assertEqual(store.library()['items'][0]['cover'],new)
