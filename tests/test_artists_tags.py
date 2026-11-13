from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock
import subprocess
import shutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import Catalog, UserError, tag_file


class ArtistCatalog(unittest.TestCase):
    def test_artist_search_and_detail_reuse_song_album_previews(self):
        with tempfile.TemporaryDirectory() as folder:
            provider = Mock()
            provider.search.return_value = [{'resultType': 'artist', 'artist': 'Daft Punk', 'browseId': 'UCRr1xG_2WIDs18a6cIiCxeA'}]
            provider.get_artist.return_value = {'name': 'Daft Punk', 'description': 'Description', 'songs': {'results': [{'videoId': 'BaW_jenozKc', 'title': 'Example'}]}, 'albums': {'results': [{'browseId': 'MPREb123456789', 'title': 'Album'}]}, 'singles': {'results': [{'browseId': 'MPREb123456789', 'title': 'Duplicate'}]}}
            catalog = Catalog(folder, factory=lambda: provider)
            result = catalog.search('daft', 'artists')['items'][0]
            self.assertEqual(result['type'], 'artist')
            self.assertEqual(result['title'], 'Daft Punk')
            detail = catalog.artist(result['id'])
            self.assertEqual(detail['songs'][0]['type'], 'song')
            self.assertEqual(detail['songs'][0]['artist'], 'Daft Punk')
            self.assertEqual(len(detail['albums']), 1)
            with self.assertRaises(UserError):
                catalog.artist('https://evil.example')
            self.assertEqual(provider.get_artist.call_count, 1)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg not installed')
    def test_lyrics_and_genres_survive_all_output_formats(self):
        from mutagen import File
        metadata = {'id': 'BaW_jenozKc', 'title': 'Test', 'artist': 'Artist', 'album': 'Album', 'genres': ['Rock'], 'lyrics': 'Una prueba\nOtra línea', 'synced_lyrics': '[00:01.250]Una prueba\n[00:02.50]Otra línea'}
        with tempfile.TemporaryDirectory() as folder:
            for extension, codec in [('mp3', 'libmp3lame'), ('m4a', 'aac'), ('opus', 'libopus')]:
                with self.subTest(extension=extension):
                    path = Path(folder) / ('test.' + extension)
                    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1', '-c:a', codec, str(path)], check=True)
                    tag_file(path, metadata, None)
                    saved = File(path)
                    if extension == 'mp3':
                        self.assertEqual(str(saved.tags['TCON']), 'Rock')
                        self.assertEqual(saved.tags.getall('USLT')[0].text, metadata['lyrics'])
                        self.assertEqual(saved.tags.getall('SYLT')[0].text[0], ('Una prueba', 1250))
                    elif extension == 'm4a':
                        self.assertEqual(saved.tags['\xa9gen'], ['Rock'])
                        self.assertEqual(saved.tags['\xa9lyr'], [metadata['lyrics']])
                    else:
                        self.assertEqual(saved.tags['genre'], ['Rock'])
                        self.assertEqual(saved.tags['lyrics'], [metadata['lyrics']])
                        self.assertEqual(saved.tags['syncedlyrics'], [metadata['synced_lyrics']])


if __name__ == '__main__':
    unittest.main()
