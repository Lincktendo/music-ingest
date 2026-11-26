import json
from pathlib import Path
import tempfile
import unittest

from core import Catalog,Store,UserError


class HTMLHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.catalog=Catalog(self.root/'cache')
        self.store=Store(self.root/'data',self.root/'music',self.catalog)
        self.sources=self.store.sources

    def test_youtube_uploads_accumulate_and_duplicates_keep_richer_data(self):
        self.sources.html('<a href="/watch?v=fixture_A01">Primera</a>')
        self.sources.index.merge_imports('youtube',[{'id':'fixture_A01','type':'song','title':'Primera','artist':'Artista guardado','album':'Disco'}])
        self.sources.html('<a href="/watch?v=fixture_B02">Segunda</a><a href="/watch?v=fixture_A01">Primera actualizada</a><script>SECRET_HTML_TEXT</script>')
        rows={r['id']:r for r in self.sources.index.imported('youtube')}
        self.assertEqual(len(rows),2)
        self.assertEqual(rows['fixture_A01']['title'],'Primera actualizada')
        self.assertEqual(rows['fixture_A01']['artist'],'Artista guardado')
        self.assertEqual(rows['fixture_A01']['album'],'Disco')
        self.assertNotIn('SECRET_HTML_TEXT',json.dumps(rows))
        self.assertEqual(self.sources.settings()['html_count'],2)
        with self.assertRaises(UserError):self.sources.html('<html>No music</html>')
        self.assertEqual(self.sources.index.imported_count('youtube'),2)

    def test_every_source_is_cumulative_and_survives_restart(self):
        self.sources.index.add('soundcloud.com')
        for source,base in [('qobuz','https://qobuz.com/us-en/album/'),('soundcloud.com','https://soundcloud.com/artist/')]:
            for n in (1,2,1):
                self.sources.index.import_html(source,f'<a href="{base}{n}">Título {n}</a>')
            self.assertEqual(self.sources.index.imported_count(source),2)
        reloaded=Store(self.root/'data',self.root/'music',self.catalog).sources
        self.assertEqual(reloaded.index.imported_count('qobuz'),2)
        self.assertEqual(reloaded.index.imported_count('soundcloud.com'),2)
        other=Store(self.root/'other',self.root/'other-music',self.catalog).sources
        self.assertEqual(other.index.imported_count('qobuz'),0)
        reloaded.index.clear_imports('qobuz')
        self.assertEqual(reloaded.index.imported_count('qobuz'),0)
        self.assertEqual(reloaded.index.imported_count('soundcloud.com'),2)

    def test_visible_window_does_not_discard_archived_references(self):
        records=[{'id':f'track{i:06d}','title':f'Track {i}','type':'song','artist':'Artista'} for i in range(700)]
        self.sources.index.merge_imports('youtube',records)
        self.assertEqual(self.sources.index.imported_count('youtube'),700)
        visible=self.sources.index.imported('youtube')
        self.assertEqual(len(visible),250)
        self.assertEqual(len({r['id'] for r in visible}),250)
        reloaded=Store(self.root/'data',self.root/'music',self.catalog).sources
        self.assertEqual(reloaded.index.imported_count('youtube'),700)

    def test_upgrades_legacy_saved_page_without_resurrecting_deleted_history(self):
        self.sources.set_option('home_html',[{'id':'fixture_A01','type':'song','title':'Legacy'}])
        with self.store.db() as db:db.execute("DELETE FROM library_options WHERE key='cumulative_html_v1'")
        migrated=Store(self.root/'data',self.root/'music',self.catalog).sources
        self.assertEqual(migrated.index.imported_count('youtube'),1)
        migrated.index.clear_imports('youtube')
        restarted=Store(self.root/'data',self.root/'music',self.catalog).sources
        self.assertEqual(restarted.index.imported_count('youtube'),0)


if __name__=='__main__':unittest.main()
