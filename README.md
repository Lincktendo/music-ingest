# Music Ingest

**Vos y tu música.** Una app para buscar canciones, organizar descargas y mantener tu biblioteca al día, desde el navegador de tu computadora o celular.

Versión **0.4.0-beta.1** · [Guía rápida](docs/GUIA-RAPIDA.md) · [Integraciones y acceso para IA](INTEGRATIONS.md)

## Qué podés hacer

- Buscar canciones, álbumes y artistas en YouTube Music, con sugerencias mientras escribís.
- Marcar varias canciones y tocar **Descargar todo**, o elegir pistas de un álbum.
- Importar una playlist una vez o descargar también las canciones que se agreguen después.
- Seguir artistas: solo novedades o también su catálogo actual, con un check.
- Guardar MP3 o el formato original, con portada, letras y géneros cuando haya datos verificables.
- Escuchar lo descargado, buscar en tu biblioteca por artista y álbum y eliminar canciones con confirmación.
- Elegir una carpeta dentro del almacenamiento de música del servidor.
- Invitar colaboradores y aprobar sus propuestas, manual o automáticamente. También podés dar a una IA una clave revocable para proponer música.

No hace falta conectar una cuenta de Google. Music Ingest no es un reproductor de streaming completo: podés usar **Navidrome** para escuchar la biblioteca fuera de esta app. Guardá contenido que tengas permiso de descargar.

## Instalación con Docker

La imagen inicial es para **Linux amd64**. En Windows usá Docker Desktop con contenedores Linux. Esta versión no anuncia soporte ARM64.

1. Descargá este repositorio con **Code → Download ZIP** y descomprimilo, o clonalo con Git.
2. Abrí una terminal en la carpeta que contiene `compose.yaml`.
3. Ejecutá:

```sh
docker compose up -d
```

4. Abrí **http://localhost:8511** y creá tu usuario y contraseña.
5. Buscá una canción y revisá sus datos antes de descargarla.

La imagen se descarga de `ghcr.io/lincktendo/music-ingest:0.4.0-beta.1`. La instalación empieza vacía: no incluye cuentas, contraseñas, claves de proveedores, cookies, música ni datos del autor.

Docker crea dos volúmenes persistentes: `data` para la configuración y `music` para las canciones. Sus nombres efectivos llevan el prefijo del proyecto Compose. No hace falta preparar permisos manualmente para estos volúmenes nuevos. En **Tu espacio → Carpeta de salida** elegís una subcarpeta de ese almacenamiento; no es una carpeta del teléfono.

### Tu biblioteca y Navidrome

Music Ingest escribe archivos de música. Navidrome puede leer esos mismos archivos: no necesitan compartir contraseñas ni claves de API.

**Si todavía no tenés Navidrome**, podés iniciar ambos compartiendo el volumen de música:

```sh
docker compose -f compose.yaml -f compose.navidrome.yaml up -d
```

Abrí Music Ingest en `http://localhost:8511` y Navidrome en `http://localhost:4533`. Creá una cuenta en cada aplicación. Navidrome lee la música en modo de solo lectura y revisa novedades cada minuto. Usá los mismos argumentos `-f` al actualizar o detener este conjunto.

**Si ya tenés Navidrome**, copiá `.env.example` a `.env` y agregá `MUSIC_FOLDER` con la ruta absoluta de la carpeta de música que ya utiliza. Luego ejecutá:

```sh
docker compose -f compose.yaml -f compose.bind.yaml up -d
```

Esa carpeta debe existir y permitir escritura al usuario `10001:10001` del contenedor en Linux. Este ejemplo no cambia la instalación existente de Navidrome. Si la carpeta está en otro equipo, primero montala en el servidor de Docker. No combines ambos ejemplos: elegí volumen compartido o carpeta existente. Más detalles en la [guía rápida](docs/GUIA-RAPIDA.md).

Con varias cuentas, compartir la raíz de `/music` con un reproductor externo puede mostrar las bibliotecas de todas ellas. Compartí solamente la subcarpeta de la biblioteca que querés exponer. Los permisos internos de Music Ingest no se trasladan a Navidrome.

### Acceso desde otro equipo

El ejemplo escucha únicamente en `127.0.0.1`. Para una red privada, copiá `.env.example` a `.env` y configurá `BIND_ADDRESS` con la dirección de escucha de tu servidor y `ALLOWED_HOSTS` con los nombres o direcciones que usarás para abrirlo. `PORT` cambia el puerto publicado.

Creá tu cuenta antes de compartir acceso. El registro está abierto a quienes puedan llegar a la instancia. No uses `*` en los hosts permitidos ni abras directamente este servicio a Internet. Si necesitás acceso remoto, mantenelo detrás de una red privada y protegé el transporte. Más detalles en [SECURITY.md](SECURITY.md).

## Uso diario

| Sección | Qué hacer |
| --- | --- |
| **Buscar** | Cambiá entre canciones, álbumes y artistas; la búsqueda se actualiza sola. Marcá canciones para descargarlas juntas. |
| **Playlists** | Pegá una lista pública o no listada y elegí una importación única o mantenerla actualizada. |
| **Artistas** | Administrá seguimientos. Desde la ficha del artista podés incluir también su catálogo actual. |
| **Descargas** | Revisá progreso y errores, reintentá trabajos y escuchá archivos terminados. |
| **Biblioteca** | Abrí un artista y un álbum, escuchá y, si sos el dueño, eliminá canciones. |
| **Tu espacio** | Elegí carpeta, agregá colaboradores, configurá proveedores y creá claves para IA. |

Cada cuenta tiene su propia biblioteca. Para colaborar, la otra persona primero crea su usuario; después la invitás usando ese nombre. La aprobación manual es el valor inicial. Activar la aprobación automática afecta propuestas nuevas y puede iniciar descargas sin otra confirmación.

Las claves para IA solo permiten buscar, revisar música y proponer canciones en la biblioteca asignada. No permiten leer archivos, aprobar propuestas ni administrar cuentas. Se muestran una vez y se pueden revocar.

LRCLIB y MusicBrainz funcionan inicialmente sin claves. Last.fm es opcional y necesita una clave creada por vos. No se incluyen credenciales de ningún proveedor. La [guía de integraciones](INTEGRATIONS.md) explica qué se envía a cada servicio y cómo configurar tus propias claves.

## Límites de esta beta

- Hasta **50 canciones por envío**, **30 seguimientos por biblioteca** y **5.000 pistas por fuente**. Las importaciones grandes van por turnos.
- Revisión automática diaria por defecto; ajustable desde cada minuto hasta una semana. El servidor debe estar encendido.
- No importa playlists privadas ni mixes personales. La disponibilidad depende de los proveedores; una fuente puede bloquear o dejar de ofrecer una canción.
- Cambiar carpeta afecta futuras descargas; no mueve archivos existentes. Eliminar canciones borra sus archivos y no tiene Deshacer.
- MP3 no mejora la calidad de la fuente. **Original** conserva el formato obtenido, que puede ser con pérdida y no reproducirse en todos los navegadores.
- No incluye recuperación automática de contraseñas ni un despliegue preparado para Internet abierto.

La base de esta versión pasó **78 pruebas de backend en Linux**. Se revisaron los flujos en Chromium de escritorio y tamaño móvil, incluida reproducción MP3. La reproducción en teléfonos físicos no se validó; WebKit en Windows no permitió comprobar decodificación de audio.

## Actualizar y respaldar

Revisá las notas de la nueva versión y hacé un respaldo antes de cambiar la etiqueta de imagen en `compose.yaml`.

```sh
docker compose pull
docker compose up -d
```

Para respaldar en carpetas locales nuevas, con el servicio detenido:

```sh
docker compose stop
docker compose cp music-ingest:/data ./backup-data
docker compose cp music-ingest:/music ./backup-music
docker compose start
```

Los respaldos incluyen cuentas, sesiones, claves configuradas y música: guardalos en privado. `docker compose down` conserva los volúmenes; **`docker compose down -v` los elimina**.

Si usás alguno de los ejemplos adicionales, repetí sus argumentos `-f` en esos comandos. Con Navidrome incluido, respaldá también su directorio `/data` con `docker compose -f compose.yaml -f compose.navidrome.yaml cp navidrome:/data ./backup-navidrome`, mientras está detenido.

## Desarrollo y licencia

El [Dockerfile](Dockerfile) permite construir la imagen desde el código. Consultá [CONTRIBUTING.md](CONTRIBUTING.md) para ejecutar pruebas y enviar cambios.

Copyright (C) 2026 Lincktendo y colaboradores. El código de Music Ingest se distribuye bajo **GPL-3.0-or-later**, sin garantía; texto completo en [LICENSE](LICENSE). Las dependencias conservan sus propias licencias y avisos, descritos en [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Music Ingest no está afiliado a YouTube, Google, Navidrome ni a los proveedores de metadatos.
