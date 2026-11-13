# Componentes y licencias de terceros

El código propio de Music Ingest está bajo **GPL-3.0-or-later**. Las dependencias mantienen sus titulares, licencias y avisos originales. Esta tabla identifica dependencias directas; no reemplaza los textos de sus licencias ni representa un inventario completo de todos los paquetes transitivos de una imagen Docker.

## Dependencias directas de Python

Las versiones corresponden a `requirements.txt`. Los enlaces apuntan al código y licencia oficiales de cada proyecto.

| Componente | Versión | Licencia declarada | Código y avisos |
| --- | --- | --- | --- |
| FastAPI | 0.162.5 | MIT | [FastAPI](https://github.com/fastapi/fastapi), [LICENSE](https://github.com/fastapi/fastapi/blob/master/LICENSE) |
| Uvicorn | 0.54.0 | BSD-3-Clause | [Uvicorn](https://github.com/Kludex/uvicorn), [LICENSE.md](https://github.com/Kludex/uvicorn/blob/main/LICENSE.md) |
| ytmusicapi | 1.12.3 | MIT | [ytmusicapi](https://github.com/sigma67/ytmusicapi), [LICENSE](https://github.com/sigma67/ytmusicapi/blob/main/LICENSE) |
| yt-dlp, extras `default` | 2026.10.26 | Unlicense para el paquete Python; dependencias con licencias propias | [yt-dlp](https://github.com/yt-dlp/yt-dlp), [licencias de distribución](https://github.com/yt-dlp/yt-dlp#licensing) |
| Mutagen | 1.48.1 | GPL-2.0-or-later | [Mutagen](https://github.com/quodlibet/mutagen), [COPYING](https://github.com/quodlibet/mutagen/blob/main/COPYING), [declaración GPL v2 o posterior](https://github.com/quodlibet/mutagen/blob/main/pyproject.toml) |
| Pillow | 13.0.0 | MIT-CMU | [Pillow](https://github.com/python-pillow/Pillow), [LICENSE](https://github.com/python-pillow/Pillow/blob/main/LICENSE) |
| Requests | 2.34.2 | Apache-2.0 | [Requests](https://github.com/psf/requests), [LICENSE](https://github.com/psf/requests/blob/main/LICENSE) |

La instalación con pip conserva los avisos que incluyen los paquetes instalados, normalmente dentro de sus directorios `.dist-info` y `licenses` en `site-packages`. Los extras y sus dependencias también conservan sus licencias; la licencia del proyecto no las sustituye.

## Componentes del contenedor

- **Python**: Python Software Foundation License Version 2 y los avisos de componentes incorporados. [Licencia e historial oficiales](https://docs.python.org/3/license.html), [fuentes de CPython](https://github.com/python/cpython).
- **Deno**: MIT para el proyecto y licencias propias de componentes incorporados. [Repositorio](https://github.com/denoland/deno), [LICENSE.md de la versión 2.9.8](https://github.com/denoland/deno/blob/v2.9.8/LICENSE.md). La compilación conserva `LICENSE.md` y los avisos explícitos de WebGPU, las declaraciones de Node y Undici del mismo tag que informa el ejecutable. No se presenta esa selección como un inventario completo de las dependencias incorporadas al binario: V8, TypeScript y otros componentes conservan sus licencias propias.
- **FFmpeg**: LGPL-2.1-or-later, o GPL cuando la compilación incorpora opciones o componentes GPL. La licencia concreta depende del binario utilizado, no solo del nombre del programa. [Licencias oficiales](https://ffmpeg.org/legal.html), [fuentes](https://ffmpeg.org/download.html#get-sources). Music Ingest lo ejecuta como proceso externo y no modifica su código.
- **Debian y sus bibliotecas**: cada paquete conserva sus términos. Los avisos de los paquetes instalados están en `/usr/share/doc/<paquete>/copyright` y los textos comunes en `/usr/share/common-licenses/`. [Información de licencias de Debian](https://www.debian.org/legal/licenses/), [fuentes de paquetes Debian](https://sources.debian.org/).

El inventario de versiones de Python y Debian, fuentes y hashes está en `/usr/share/music-ingest/third-party.json` dentro de la imagen. Los avisos de Deno descritos arriba están en `/usr/share/licenses/deno/`, conservando sus rutas relativas; el inventario registra para cada uno su URL de origen y SHA-256, además del archivo fuente oficial de la versión. Para redistribuir una imagen modificada, conservá los avisos, identificá las versiones y cumplí las obligaciones de disponibilidad del código fuente que correspondan a sus componentes. Enlaces a proyectos y esta tabla, por sí solos, no reemplazan esas obligaciones.

El ejemplo opcional de Navidrome usa su imagen oficial como servicio separado. [Navidrome](https://github.com/navidrome/navidrome) conserva sus licencias, avisos y código fuente propios; no se incorpora al código ni a la imagen de Music Ingest.

## Servicios y contenido

YouTube Music, LRCLIB, MusicBrainz, Last.fm y DuckDuckGo son servicios externos, no componentes incluidos con credenciales en esta distribución. Sus condiciones y los derechos sobre audio, letras, imágenes y metadatos son independientes de la licencia del programa. La aplicación conserva atribuciones cuando el proveedor las entrega. No se incluyen bibliotecas musicales ni carátulas de demostración.

Los nombres de productos y marcas pertenecen a sus titulares; se usan para identificar compatibilidad, sin indicar afiliación ni respaldo.
