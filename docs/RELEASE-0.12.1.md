# Music Ingest 0.12.1

Esta actualización mejora las portadas, los resultados de búsqueda y la navegación, y conserva las referencias de todas las páginas HTML que importás.

- **HTML acumulativos:** cada página suma referencias a su fuente, sin reemplazar las anteriores ni duplicar canciones. Los datos nuevos completan los que faltaban. El historial permanece después de reiniciar y alimenta las sugerencias de Inicio. Se guardan los datos musicales extraídos, no el HTML completo.
- **Inicio en cuadrícula:** canciones y álbumes vuelven a ocupar varias filas, con portadas cuadradas y texto acotado. Los avisos aparecen abajo a la derecha y desaparecen en un máximo de cuatro segundos.
- **Artistas favoritos:** tocá el nombre de un artista para abrir su perfil y guardalo con el corazón. Aparece en Artistas, ahora con un icono de persona. Guardar un artista no activa descargas automáticas.
- **Portadas más nítidas:** se pide una imagen de mayor resolución cuando la fuente la ofrece y se conserva su referencia para recuperarla después de reiniciar. El distintivo de fuente usa el color de su plataforma.
- **Resultados más cuidados:** se filtran referencias sin verificar, tarjetas sin portada y muestras identificadas por la fuente. También se rechaza una descarga que resulta más corta que la duración anunciada. SoundCloud es una fuente opcional; no se agrega de forma predeterminada.
- **Logo simplificado:** conserva el giro interactivo y el efecto de descargas pendientes, sin las notas flotantes durante la reproducción.

La disponibilidad del audio completo y la resolución de las portadas siguen dependiendo de cada fuente. Los archivos descargados anteriormente se conservan.

## Actualizar

Respaldá tus datos y, en el `compose.yaml` de tu instalación, cambiá la imagen de Music Ingest a `ghcr.io/lincktendo/music-ingest:0.12.1`. Conservá tus puertos, carpetas y volúmenes. Después, desde esa misma carpeta:

```sh
docker compose pull music-ingest
docker compose up -d music-ingest
```

Usá los mismos archivos `-f` y el mismo nombre de proyecto (`-p`, si lo usaste) que elegiste al instalar. Conservá los volúmenes `data` y `music`. La migración incorpora automáticamente las referencias HTML que ya estaban guardadas. Para instalar junto a Navidrome, consultá [la guía de las dos opciones](https://github.com/Lincktendo/music-ingest/blob/main/docs/NAVIDROME-Y-ROTACION.md).

## Comprobaciones

169 pruebas de Python y 12 pruebas del reproductor, además de comprobaciones en navegador de escritorio y celular: cuadrícula, avisos, artistas favoritos e importaciones HTML acumulativas.
