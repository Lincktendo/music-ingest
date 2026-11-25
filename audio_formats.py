"""Audio outputs supported by the library and verified source formats."""
from typing import Literal

AudioFormat = Literal['mp3', 'flac', 'wav', 'alac', 'aac', 'opus', 'ogg', 'aiff', 'original']
DownloadMode = Literal['auto', 'mp3', 'flac', 'wav', 'alac', 'aac', 'opus', 'ogg', 'aiff', 'original']
ORDER = ('flac', 'wav', 'aiff', 'alac', 'mp3', 'aac', 'opus', 'ogg')
LOSSLESS = {'flac', 'wav', 'alac', 'aiff'}
EXTENSIONS = {'alac': 'm4a', 'aac': 'm4a'}
# Output capabilities of our integrations. A particular track must still offer the format.
CATALOG = {
    'youtube': ('mp3',), 'qobuz': ('mp3','flac'),
    'bandcamp.com': ORDER, 'soundcloud.com': ORDER, 'archive.org': ORDER,
    'dailymotion.com': ('mp3',), 'vimeo.com': ('mp3',), 'mixcloud.com': ('mp3',),
}

def native_audio(codec, container=''):
    codec = (codec or '').lower()
    container = (container or '').lower()
    if codec.startswith('pcm_') or codec in ('wav/pcm', 'wav', 'pcm'):
        return 'aiff' if 'aif' in container else 'wav'
    if codec.startswith(('mp4a', 'aac')):
        return 'aac'
    if 'vorbis' in codec or codec == 'ogg':
        return 'ogg'
    if codec in ORDER:
        return codec
    if codec in ('', 'none', 'unknown'):
        return {'aif':'aiff', 'aiff':'aiff', 'wav':'wav', 'flac':'flac', 'mp3':'mp3',
                'aac':'aac', 'opus':'opus'}.get(container, '')
    return ''

def track_formats(track):
    native = {native_audio(track.get('native_format'))}
    native.update(f for f in track.get('offered_formats', []) if f in ORDER)
    options = {'mp3'} | (native & set(ORDER))
    if native & LOSSLESS or track.get('native_lossless'):
        options.add('flac')
    return options

def prefer(formats, best):
    order = ORDER if best else ('mp3', *ORDER)
    return next((f for f in order if f in formats), None)
