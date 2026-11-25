import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mutagen import File
from mutagen.id3 import USLT

from core import Catalog, Store, UserError
from download_tools import Tags, edit_tags


@unittest.skipUnless(shutil.which('ffmpeg'), 'Audio fixture needs FFmpeg')
class FileTagEdits(unittest.TestCase):
    def test_edit_mp3_and_flac_keep_other_tags_and_reject_stale_edits(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = Store(root/'data', root/'music', Catalog(root/'data'))
            for fmt in ('mp3', 'flac'):
                with self.subTest(fmt=fmt):
                    path = store.music/('fixture.'+fmt)
                    subprocess.run(['ffmpeg','-loglevel','error','-f','lavfi','-i','anullsrc',
                                    '-t','0.2',str(path)], check=True)
                    audio = File(path)
                    if fmt == 'flac':
                        audio['lyrics'] = ['letra']
                    else:
                        if audio.tags is None:
                            audio.add_tags()
                        audio.tags.add(USLT(encoding=3,lang='spa',desc='Test',text='letra'))
                    audio.save()
                    metadata = {'id':'qb:12345','title':'Before','youtube_id':'BaW_jenozKc'}
                    with store.db() as db:
                        db.execute('INSERT INTO files VALUES(?,?,?,?,?)',
                                   (metadata['id'],fmt,path.name,json.dumps(metadata),'job'))
                    changes = Tags(title='Nuevo',artist='Mi artista',album='Mi disco',track=2)
                    saved = edit_tags(store,metadata['id'],fmt,changes)
                    self.assertEqual(saved['tag_revision'],1)
                    self.assertEqual(saved['artist'],'Mi artista')
                    reread = File(path)
                    self.assertEqual(str(reread['TIT2']) if fmt=='mp3' else reread['title'][0],'Nuevo')
                    self.assertEqual(reread.tags.getall('USLT')[0].text if fmt=='mp3' else reread['lyrics'][0],'letra')
                    self.assertEqual(store.saved_ids(['BaW_jenozKc']),{'qb:12345','BaW_jenozKc'})
                    with self.assertRaises(UserError):
                        edit_tags(store,metadata['id'],fmt,changes)
                    original = path.read_bytes()
                    with patch('download_tools.write_tags',side_effect=UserError('falló')):
                        with self.assertRaises(UserError):
                            edit_tags(store,metadata['id'],fmt,changes.model_copy(update={'revision':1}))
                    self.assertEqual(path.read_bytes(),original)
                    self.assertFalse(list(store.music.glob('.ingest-tags-*')))
