"""Artwork keeps actual source detail and survives a server restart without private URLs."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from PIL import Image
from core import Catalog, UserError
from music_home import album_art


def picture(width, height=None):
    image=Image.new('RGB',(width,height or width),'#47517d')
    # High-frequency detail makes this a real large image, not a resized thumbnail.
    for x in range(0,width,11):
        image.paste('#d7e4f5',(x,0,min(x+3,width),height or width))
    out=io.BytesIO();image.save(out,'PNG');return out.getvalue()


def dimensions(path):
    with Image.open(path) as image:return image.size


class Reply:
    def __init__(self, body=b'', status=200, size=None):
        self.status_code=status
        self.headers={'Content-Length':str(len(body) if size is None else size)}
        self.body=body
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def iter_content(self,size):
        for pos in range(0,len(self.body),size):yield self.body[pos:pos+size]


class Origin:
    def __init__(self,resolver):
        self.resolver=resolver;self.calls=[];self.trust_env=True;self.cookies=type('Jar',(),{'clear':lambda self:None})()
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def get(self,url,**kwargs):
        self.calls.append((url,kwargs));return self.resolver(url)


class CoverQuality(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.catalog=Catalog(self.root)
    def tearDown(self):self.tmp.cleanup()
    def ident(self,thumbs):return self.catalog.cover(thumbs).rsplit('/',1)[-1]

    def test_tiny_music_search_thumbnail_fetches_real_large_album_art(self):
        tiny='https://lh3.googleusercontent.com/album=w60-h60-l90-rj'
        ident=self.ident([{'url':tiny,'width':60,'height':60}])
        origin=Origin(lambda url:Reply(picture(1200)) if '=w1200-h1200' in url else Reply(picture(60)))
        with patch('core.requests.Session',return_value=origin):path=self.catalog.cover_file(ident)
        self.assertEqual(dimensions(path),(1200,1200))
        self.assertIn('=w1200-h1200-l90-rj',origin.calls[0][0])
        self.assertFalse(origin.trust_env)
        self.assertFalse(origin.calls[0][1]['allow_redirects'])
        self.assertNotIn('headers',origin.calls[0][1])
        self.assertEqual(len(origin.calls),1)
        self.assertIsInstance(self.catalog.cover_sources[ident],str)
        self.assertTrue(Catalog.valid_cover(self.catalog.cover_sources[ident]))
        self.assertEqual(ident,self.ident([{'url':tiny.replace('60-h60','120-h120'),'width':'120'}]))
        self.assertIn('w1200-h1200',album_art(tiny))

    def test_old_low_resolution_cache_is_upgraded_without_changing_legacy_url(self):
        url='https://lh3.googleusercontent.com/album=w120-h120'
        legacy=hashlib.sha256(url.encode()).hexdigest()
        target=self.catalog.covers/(legacy+'.jpg');target.write_bytes(picture(120))
        custom=self.root/'artwork'/'custom.jpg';custom.parent.mkdir();custom.write_bytes(picture(64))
        custom_before=custom.read_bytes()
        self.ident([{'url':url}])
        with patch('core.requests.Session',return_value=Origin(lambda _:Reply(picture(1200)))):
            self.assertEqual(self.catalog.cover_file(legacy),target)
        self.assertEqual(dimensions(target),(1200,1200));self.assertEqual(custom.read_bytes(),custom_before)

    def test_restart_can_load_not_yet_fetched_covers_without_persisting_query_secrets(self):
        ident=self.ident([{'url':'https://lh3.googleusercontent.com/album=w60-h60?token=PRIVATE-COVER-TOKEN#secret'}])
        other=Catalog(self.root)
        with other.cover_db() as db:
            all_urls=' '.join(row[0] for row in db.execute('SELECT urls FROM cover_origins'))
        self.assertNotIn('PRIVATE-COVER-TOKEN',all_urls);self.assertNotIn('?',all_urls)
        self.assertNotIn('PRIVATE-COVER-TOKEN',str(self.catalog.cover_sources))
        with patch('core.requests.Session',return_value=Origin(lambda _:Reply(picture(900)))):
            self.assertEqual(dimensions(other.cover_file(ident)),(900,900))

    def test_unavailable_large_variant_falls_back_without_upsampling_or_repeated_fetches(self):
        url='https://lh3.googleusercontent.com/album=w120-h120'
        ident=self.ident([{'url':url}])
        origin=Origin(lambda candidate:Reply(picture(120)) if candidate==url else Reply(status=404))
        with patch('core.requests.Session',return_value=origin):
            path=self.catalog.cover_file(ident);self.assertEqual(dimensions(path),(120,120))
            count=len(origin.calls);self.catalog.cover_file(ident);self.assertEqual(len(origin.calls),count)
        self.assertEqual(count,2)

    def test_soundcloud_uses_original_then_500_with_real_dimensions(self):
        for host in ('i1.sndcdn.com','a1.sndcdn.com'):
            with self.subTest(host=host):
                ident=self.ident([{'url':'https://'+host+'/artworks-fixture-large.jpg'}])
                origin=Origin(lambda url:Reply(status=404) if '-original.' in url else Reply(picture(500 if '-t500x500.' in url else 100)))
                with patch('core.requests.Session',return_value=origin):path=self.catalog.cover_file(ident)
                self.assertEqual(dimensions(path),(500,500));self.assertIn('-original.',origin.calls[0][0])
        ident=self.ident([{'url':'https://i1.sndcdn.com/artworks-real-small-large.jpg'}])
        origin=Origin(lambda _:Reply(picture(300)))
        with patch('core.requests.Session',return_value=origin):path=self.catalog.cover_file(ident)
        self.assertEqual(dimensions(path),(300,300));self.assertEqual(len(origin.calls),1)

    def test_bad_size_fields_dont_break_selection_and_google_avatar_ratio_is_preserved(self):
        ident=self.ident([{'url':'https://lh3.googleusercontent.com/low=s60-c','width':'invalid'},
                          {'url':'https://lh3.googleusercontent.com/portrait=w300-h600','width':300,'height':600}])
        with self.catalog.cover_db() as db:urls=json.loads(db.execute('SELECT urls FROM cover_origins WHERE ident=?',(ident,)).fetchone()[0])
        self.assertIn('=w600-h1200',urls[0])

    def test_redirects_invalid_images_oversize_and_stored_untrusted_url_never_expand_allowlist(self):
        for url in ('http://lh3.googleusercontent.com/a','https://lh3.googleusercontent.com.evil/a',
                    'https://name@i1.sndcdn.com/a','https://i1.sndcdn.com:444/a','https://127.0.0.1/a','https://lh3.googleusercontent.com/a\r\nx:1'):
            self.assertEqual(self.catalog.cover([{'url':url}]),'')
        url='https://lh3.googleusercontent.com/fixture=w60-h60';ident=self.ident([{'url':url}])
        for reply in (Reply(status=302),Reply(b'not-an-image'),Reply(size=6_000_000)):
            origin=Origin(lambda _:reply)
            with patch('core.requests.Session',return_value=origin),self.assertRaises(UserError):self.catalog.cover_file(ident)
            self.assertTrue(all(not args['allow_redirects'] for _,args in origin.calls))
        bad='a'*64
        with self.catalog.cover_db() as db:db.execute('INSERT INTO cover_origins(ident,urls) VALUES(?,?)',(bad,'["http://127.0.0.1/private"]'))
        with patch('core.requests.Session') as upstream,self.assertRaises(UserError):self.catalog.cover_file(bad)
        upstream.assert_not_called();self.assertFalse(list(self.catalog.covers.glob('*.tmp')))

    def test_simultaneous_cards_share_one_fetch(self):
        ident=self.ident([{'url':'https://lh3.googleusercontent.com/concurrent=w60-h60'}])
        entered,release=threading.Event(),threading.Event()
        def resolve(_):entered.set();release.wait(2);return Reply(picture(900))
        origin=Origin(resolve)
        with patch('core.requests.Session',return_value=origin),ThreadPoolExecutor(max_workers=4) as pool:
            first=pool.submit(self.catalog.cover_file,ident);self.assertTrue(entered.wait(1))
            others=[pool.submit(self.catalog.cover_file,ident) for _ in range(3)];release.set()
            results=[f.result(3) for f in [first,*others]]
        self.assertEqual(len(set(results)),1);self.assertEqual(len(origin.calls),1)

    def test_failed_upgrade_preserves_existing_cover_bytes(self):
        url='https://lh3.googleusercontent.com/offline=w120-h120';ident=self.ident([{'url':url}])
        target=self.catalog.covers/(ident+'.jpg');target.write_bytes(picture(120));before=target.read_bytes()
        with patch('core.requests.Session',return_value=Origin(lambda _:Reply(status=503))):self.catalog.cover_file(ident)
        self.assertEqual(target.read_bytes(),before)


if __name__=='__main__':unittest.main()
