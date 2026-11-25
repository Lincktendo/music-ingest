"""Short-lived yt-dlp process for an untrusted public media URL. No web-app state."""
import ipaddress
import json
from pathlib import Path
import resource
import socket
import sys


def public_connection(event, args):
    if event in ('subprocess.Popen', 'os.system', 'os.posix_spawn'):
        raise PermissionError('Native downloader only')
    if event == 'socket.connect':
        sock, address = args
        if sock.family not in (socket.AF_INET, socket.AF_INET6) or address[1] not in (80, 443):
            raise PermissionError('Public web endpoints only')
        ip = ipaddress.ip_address(address[0])
        if ip.version == 6 and (ip.ipv4_mapped or ip.sixtofour or ip.teredo or ip not in ipaddress.ip_network('2000::/3')):
            raise PermissionError('Public endpoints only')
        if not ip.is_global or ip.is_multicast or ip.is_reserved:
            raise PermissionError('Public endpoints only')


def lossless(f):
    codec = str(f.get('acodec') or '').lower()
    ext = str(f.get('ext') or '').lower()
    if codec.startswith(('flac','alac','pcm_')):
        return 'WAV/PCM' if codec.startswith('pcm_') else codec.upper()
    if codec in ('','unknown') and ext in ('flac','wav'):
        return ext.upper()
    return ''


sys.path.insert(0, str(Path(__file__).resolve().parent))
from audio_formats import native_audio, LOSSLESS

def select_audio(ctx, requested=None):
    formats = [f for f in ctx['formats'] if f.get('protocol') in ('https','http','m3u8_native')
               and not f.get('has_drm') and f.get('acodec') != 'none']
    if requested and requested!='mp3':
        wanted=LOSSLESS if requested=='flac' else {requested}
        matching=[f for f in formats if native_audio(f.get('acodec'),f.get('ext')) in wanted]
        # A previously inspected direct file can lack extractor metadata. ffprobe
        # validates the actual codec again before the selected output is published.
        formats=matching or [f for f in formats if not native_audio(f.get('acodec'),f.get('ext'))]
    if formats:
        # yt-dlp supplies formats in ascending preference. Prefer lossless, then audio-only.
        yield max(reversed(formats), key=lambda f: (bool(lossless(f)), f.get('vcodec') == 'none'))


def run():
    args = json.load(sys.stdin)
    if args['engine']:
        sys.path.insert(0,args['engine'])
    from yt_dlp import YoutubeDL
    from yt_dlp.plugins import plugin_dirs
    plugin_dirs.value = []
    resource.setrlimit(resource.RLIMIT_FSIZE, (160_000_000,160_000_000))
    resource.setrlimit(resource.RLIMIT_AS, (480*1024**2,480*1024**2))
    sys.addaudithook(public_connection)
    result_file = args.get('output')
    options = dict(quiet=True, no_warnings=True, noprogress=True, cachedir=False, proxy='',
                   noplaylist=True, playlistend=6 if args.get('search') else 1, extract_flat='in_playlist', js_runtimes={},
                   socket_timeout=6, retries=1, fragment_retries=1, hls_prefer_native=True,
                   max_filesize=150_000_000, format=lambda ctx: select_audio(ctx, args.get('format')), fixup='never',
                   cookiefile=args.get('cookies'), outtmpl=result_file or '-', overwrites=False)
    with YoutubeDL(options) as ydl:
        handlers=ydl._request_director.handlers
        for name in list(handlers):
            if name != 'Urllib':
                del handlers[name]
        if args.get('search'):
            result=ydl.extract_info('scsearch6:'+args['search'][:200],download=False)
            entries=[]
            for t in result.get('entries') or []:
                address=t.get('permalink_url') or t.get('webpage_url') or t.get('url') or ''
                if address.startswith(('https://soundcloud.com/','https://www.soundcloud.com/')) and t.get('title'):
                    entries.append({'title':str(t['title'])[:200],'artist':str(t.get('uploader') or t.get('artist') or '')[:160],'url':address})
            print(json.dumps(entries))
            return
        item=ydl.extract_info(args['url'],download=False)
        if not item or item.get('_type') in ('playlist','multi_video') or item.get('is_live') or (item.get('duration') or 0)>3600:
            raise ValueError('Single audio only')
        if result_file:
            ydl.process_info(item)
            if not Path(result_file).is_file():
                raise ValueError('No file')
        print(json.dumps({k:str(item.get(k) or '')[:300] for k in ('title','artist','uploader','album','duration','ext','acodec','thumbnail')}
                         | {'native_lossless':lossless(item), 'offered_formats':sorted({fmt for f in item.get('formats') or [item]
                            if not f.get('has_drm') and f.get('protocol') in ('http','https','m3u8_native')
                            and (fmt:=native_audio(f.get('acodec'), f.get('ext')))})}))


if __name__=='__main__':
    try:
        run()
    except Exception:
        sys.exit(1)
