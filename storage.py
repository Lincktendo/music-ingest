"""Library-confined output folders; never expose arbitrary host paths."""
from pathlib import Path
import os
import re
import tempfile


def music_path(root, relative='', *, directory=False):
    root = Path(root)
    if not isinstance(relative, str) or len(relative) > 700 or '\\' in relative:
        raise ValueError('Carpeta no válida.')
    parts = relative.split('/') if relative else []
    if len(parts) > 8 or any(not p or p.startswith('.') or ':' in p or any(ord(c)<32 for c in p) for p in parts):
        raise ValueError('Elegí una carpeta dentro de tu biblioteca.')
    # Account namespaces are not browsable from the legacy owner's root.
    if parts and re.fullmatch(r'[a-f0-9]{32}', parts[0]):
        raise ValueError('Esa carpeta está reservada.')
    if root.is_symlink():
        raise ValueError('No se admiten enlaces simbólicos.')
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
            raise ValueError('No se admiten enlaces simbólicos.')
    if not current.resolve().is_relative_to(root.resolve()):
        raise ValueError('La carpeta queda fuera de tu biblioteca.')
    if directory and not current.is_dir():
        raise ValueError('Esta carpeta ya no está disponible.')
    return current


class Folders:
    def __init__(self, store):
        self.store = store

    def browse(self, relative=''):
        directory = music_path(self.store.music, relative, directory=True)
        entries=[]
        for child in directory.iterdir():
            try:
                rel=child.relative_to(self.store.music).as_posix()
                if music_path(self.store.music, rel).is_dir():
                    entries.append({'name':child.name,'path':rel})
            except (ValueError,OSError):
                continue
        with self.store.db() as db:
            selected=db.execute("SELECT value FROM library_options WHERE key='output_folder'").fetchone()
        return {'path':relative,'selected':selected[0] if selected else '',
                'items':sorted(entries,key=lambda x:x['name'].casefold())[:500],
                'label':'Carpeta de música del servidor'}

    def create(self, parent, name):
        if not isinstance(name,str) or not 1 <= len(name.strip()) <= 80:
            raise ValueError('Poné un nombre de 1 a 80 caracteres.')
        name=name.strip()
        if any(c in name for c in '/\\<>:"|?*') or name.endswith(('.', ' ')) or name.startswith('.'):
            raise ValueError('Usá un nombre sencillo, sin barras ni símbolos especiales.')
        if name.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:
            raise ValueError('Ese nombre está reservado por el sistema.')
        base=music_path(self.store.music,parent,directory=True)
        relative=(base/name).relative_to(self.store.music).as_posix()
        target=music_path(self.store.music,relative)
        target.mkdir(exist_ok=True)
        return self.browse(relative)

    def select(self, relative):
        directory=music_path(self.store.music,relative,directory=True)
        try:
            with tempfile.TemporaryFile(dir=directory) as stream:
                stream.write(b'probe');stream.flush();os.fsync(stream.fileno())
        except OSError:
            raise ValueError('No tenemos permiso para guardar en esta carpeta.') from None
        with self.store.lock,self.store.db() as db:
            db.execute("INSERT OR REPLACE INTO library_options VALUES('output_folder',?)",(relative,))
        return self.browse(relative)
