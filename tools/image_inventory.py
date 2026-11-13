"""Public dependency inventory. Never reads application state or environment secrets."""
import importlib.metadata as metadata
import hashlib
import json
from pathlib import Path
import platform
import re
import subprocess
from urllib.parse import quote
from urllib.request import urlopen

target=Path('/usr/share/music-ingest')
target.mkdir(parents=True,exist_ok=True)
packages=[]
for dist in sorted(metadata.distributions(),key=lambda d:d.metadata['Name'].lower()):
    name,version=dist.metadata['Name'],dist.version
    with urlopen('https://pypi.org/pypi/'+quote(name,safe='')+'/'+quote(version,safe='')+'/json',timeout=30) as response:
        release=json.load(response)
    sources=[{'url':f['url'],'sha256':f['digests']['sha256']} for f in release['urls'] if f['packagetype']=='sdist']
    packages.append({'name':name,'version':version,'source_archives':sources,
                     'metadata_page':'https://pypi.org/project/'+quote(name,safe='')+'/'+quote(version,safe='')+'/',
                     'installed_notices':[str(f) for f in dist.files or [] if 'license' in str(f).lower() or 'copying' in str(f).lower()]})
debian=[]
text=subprocess.check_output(['dpkg-query','-W','-f=${Package}\t${Version}\t${source:Package}\t${source:Version}\n'],text=True)
for line in text.splitlines():
    name,version,source,source_version=line.split('\t')
    source=source or name;source_version=source_version or version
    debian.append({'name':name,'version':version,'source_package':source,'source_version':source_version,
                   'source':'https://sources.debian.org/src/'+quote(source,safe='')+'/'+quote(source_version,safe='')+'/',
                   'source_archive_index':'https://snapshot.debian.org/package/'+quote(source,safe='')+'/'+quote(source_version,safe='')+'/',
                   'copyright_file':'/usr/share/doc/'+name+'/copyright'})
deno=subprocess.check_output(['deno','--version'],text=True).splitlines()[0].split()[1]
if not re.fullmatch(r'\d+\.\d+\.\d+',deno):
    raise ValueError('Expected an official stable Deno version')
# Deno has no `license` command or `--license` flag. Preserve the actual
# notices from the exact upstream source tag, without claiming that these
# four files cover all statically linked third-party dependencies.
license_dir=Path('/usr/share/licenses/deno')
license_dir.mkdir(parents=True,exist_ok=True)
deno_notices=[]
for source_path in ('LICENSE.md','ext/webgpu/LICENSE.md','cli/tsc/dts/node/LICENSE','cli/tsc/dts/node/undici/LICENSE'):
    source_url='https://raw.githubusercontent.com/denoland/deno/v'+deno+'/'+source_path
    with urlopen(source_url,timeout=30) as response:
        notice=response.read()
    if b'Permission is hereby granted' not in notice or b'Copyright' not in notice:
        raise ValueError('Unexpected upstream Deno notice: '+source_path)
    destination=license_dir/source_path
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_bytes(notice)
    deno_notices.append({'file':str(destination),'source':source_url,'sha256':hashlib.sha256(notice).hexdigest()})
version=platform.python_version()
inventory={'python':{'version':version,'source':'https://www.python.org/ftp/python/'+version+'/Python-'+version+'.tar.xz'},
           'deno':{'version':deno,'source':'https://github.com/denoland/deno/releases/tag/v'+deno,'source_archive':'https://github.com/denoland/deno/releases/download/v'+deno+'/deno_src.tar.gz','notices':deno_notices,'notices_scope':'Explicit notices from the Deno source tree; not a complete inventory of bundled transitive dependencies.'},
           'python_packages':packages,'debian_packages':debian}
(target/'third-party.json').write_text(json.dumps(inventory,indent=2)+'\n')
