# Music Ingest 0.12.2

Descargas ahora muestra una tarjeta por canción, con el mismo estilo de portadas que Inicio. Los títulos largos y los avisos ya no cambian la altura de las tarjetas.

- Cuadrícula con tamaños uniformes y filas de altura fija en la vista de lista, también en celular.
- Un clic en la portada o el título reproduce el archivo guardado.
- Los tres puntos reúnen **Editar datos y portada**, **Ver letra** y **Guardar como…**. Los avisos y los detalles del trabajo quedan en ese menú.
- El progreso y los intentos fallidos conservan sus opciones de consulta y reintento.

Incluye las mejoras de 0.12.1: HTML acumulativos por fuente, artistas favoritos, mejores portadas, Inicio en cuadrícula y notificaciones abajo a la derecha durante cuatro segundos como máximo.

## Actualizar

Respaldá tus datos. En tu archivo Compose cambiá la imagen a `ghcr.io/lincktendo/music-ingest:0.12.2`, conservando tus puertos y volúmenes. Desde la misma carpeta de instalación ejecutá:

```sh
docker compose pull music-ingest
docker compose up -d music-ingest
```

Usá los mismos archivos `-f` y nombre de proyecto `-p` que en tu instalación, si los especificaste. Conservá `data` y `music`.

Comprobado en navegador a 1440, 390 y 320 píxeles: dimensiones uniformes, ausencia de desbordes, reproducción al pulsar, menú de acciones y lectura de letras.
