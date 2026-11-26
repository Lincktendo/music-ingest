from pathlib import Path
import tempfile
import unittest

from artist_favorites import ArtistFavorites
from core import Store, Catalog, UserError

ARTIST='UC'+'a'*22


class ArtistFavoritesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.store=Store(self.root/'data',self.root/'music',Catalog(self.root/'cache'))
        self.service=ArtistFavorites(self.store)

    def test_save_remove_is_private_idempotent_and_never_creates_download(self):
        saved=self.service.save('ana','Nombre artista','youtube',ARTIST)
        self.service.save('ana','Nombre artista','youtube',ARTIST)
        self.assertEqual(len(self.service.listing('ana')['items']),1)
        self.assertEqual(self.service.listing('bob')['items'],[])
        self.service.remove('bob',saved['key'])
        self.assertEqual(len(self.service.listing('ana')['items']),1)
        self.assertEqual(self.store.jobs()['items'],[])
        self.assertIsNone(self.store.sources.option('favorite_artists'))
        with self.store.db() as db:
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='follows'").fetchone())
        self.service.remove('ana',saved['key'])
        self.assertEqual(self.service.listing('ana')['items'],[])

    def test_persists_and_libraries_are_isolated(self):
        self.service.save('ana','Artista','youtube',ARTIST)
        another=Store(self.root/'otherdata',self.root/'othermusic',Catalog(self.root/'othercache'))
        self.assertEqual(ArtistFavorites(another).listing('ana')['items'],[])
        reopened=Store(self.root/'data',self.root/'music',Catalog(self.root/'cache'))
        self.assertEqual(ArtistFavorites(reopened).listing('ana')['items'][0]['id'],ARTIST)

    def test_name_only_can_be_upgraded_to_catalog_id_without_duplicate(self):
        self.service.save('ana','Artista','youtube')
        self.service.save('ana','ARTISTA','youtube',ARTIST)
        items=self.service.listing('ana')['items']
        self.assertEqual(len(items),1);self.assertEqual(items[0]['id'],ARTIST)

    def test_artwork_is_scoped_and_raw_remote_urls_are_not_accepted(self):
        url='https://lh3.googleusercontent.com/artist=w320-h320'
        cover=self.store.catalog.cover([{'url':url}])
        self.service.save('ana','Artista','youtube',ARTIST,cover)
        self.store.catalog.cover_sources.clear()
        public=self.service.listing('ana')['items'][0]
        self.assertEqual(public['cover'],cover)
        self.assertNotIn('art_source',public)
        other=self.service.save('ana','Sin portada','youtube','','https://private.example/token')
        self.assertEqual(other['cover'],'')
        with self.assertRaises(UserError):self.service.save('ana','Artista','youtube','https://example.org/x')
        with self.assertRaises(UserError):self.service.save('ana','Artista','unregistered.example')


if __name__=='__main__':unittest.main()
