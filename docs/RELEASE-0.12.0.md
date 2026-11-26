# Music Ingest 0.12.0

Music Ingest reúne reproducción, descubrimiento y descargas en una sola app. Esta versión separa Inicio, Favoritas y Fuentes, simplifica las portadas y deja la cola junto al reproductor.

- **Escuchá y seguí navegando:** cola desplegable sobre el reproductor, orden por arrastre y Auto DJ con estado visible. Favoritas carga la lista completa, empezando por la rola elegida y siguiendo de la más reciente a la más antigua.
- **Menos espera:** ruta de reproducción directa para audio compatible de YouTube, preparación anticipada de la próxima pista y caché. La disponibilidad y el tiempo de arranque dependen también de la fuente y de tu conexión.
- **Portadas limpias:** los tres puntos y el clic derecho permiten descargar en segundo plano, guardar favoritas, agregar a una playlist, abrir el álbum y ordenar qué se escucha después.
- **Inicio personal:** canciones y álbumes en secciones, historial de búsquedas de texto y géneros de la biblioteca conectada a Navidrome. Las búsquedas, reproducciones y favoritas ayudan a ordenar las sugerencias.
- **Playlists para escuchar:** al importar una playlist podés agregarla también a tus listas locales. Las nuevas pistas descubiertas se incorporan al abrir la colección.
- **Descargas organizadas:** lista o cuadrícula, progreso, reintentos y edición de metadatos. Los nombres de varios artistas conservan la separación por punto y coma.
- **Un logo vivo:** arrastralo desde cualquier sección. Se anima al reproducir y toma un acabado metálico mientras hay descargas pendientes.

Siguen disponibles las descargas MP3 y FLAC cuando la fuente ofrece audio sin pérdida, letras y portadas, seguimiento de artistas y playlists, rotación programada y conexión con Navidrome.

## Actualizar

Respaldá tus datos y, en el `compose.yaml` de tu instalación, cambiá la imagen de Music Ingest a `ghcr.io/lincktendo/music-ingest:0.12.0`. Conservá tus puertos, carpetas y volúmenes. Después, desde esa misma carpeta:

```sh
docker compose pull
docker compose up -d
```

Usá los mismos archivos `-f` y el mismo nombre de proyecto (`-p`, si lo usaste) que elegiste al instalar. Conservá los volúmenes `data` y `music`. Para instalar junto a Navidrome, consultá [la guía de las dos opciones](https://github.com/Lincktendo/music-ingest/blob/main/docs/NAVIDROME-Y-ROTACION.md).

## Texto breve para el video

«Music Ingest ya es tu reproductor: escuchás, armás playlists y descubrís música con Auto DJ. Descargá en MP3 o FLAC cuando la fuente lo ofrezca, con portada y metadatos. Y automatizá artistas y playlists para mantener tu biblioteca al día. Todo desde tu propio servidor.»
