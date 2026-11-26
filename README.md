# Music Ingest

**Vos y tu música.** Un reproductor para escuchar, descubrir música y mantener tu biblioteca al día. Con yt-dlp como motor de descargas, desde el navegador de tu computadora o celular.

Versión **0.12.2** · [Guía rápida](docs/GUIA-RAPIDA.md) · [Integraciones y acceso para IA](INTEGRATIONS.md) · [Instalar solo o con Navidrome y activar la rotación](docs/NAVIDROME-Y-ROTACION.md)

## Qué podés hacer

- Buscar desde la barra superior en cualquier pantalla o pegar un enlace de audio o video. YouTube Music (Google) viene activo. En Ajustes elegís qué fuentes participan en los resultados.
- Marcar varias canciones y tocar **Descargar todo**, o elegir pistas de un álbum.
- Importar una playlist una vez o descargar las novedades automáticamente; podés agregarla también a tus playlists locales para escucharla.
- Seguir artistas: solo novedades o también su catálogo actual, con un check.
- Ver el formato antes de descargar. La preferencia inicial elige FLAC cuando la pista está disponible sin pérdida. YouTube Music se guarda en MP3. En los enlaces adicionales se inspecciona el audio antes de ofrecer un formato de salida.
- Descubrir canciones de los artistas que escuchaste o descargaste. Cada fuente acepta su HTML y sus cookies. Podés mezclar o agrupar recomendaciones y sumar otras plataformas en **+ Agregar fuente**.
- Escuchar en Stream mientras navegás, guardar favoritas y armar playlists. La cola se despliega sobre el player; podés reordenarla y Auto DJ prepara la próxima rola.
- Explorar Inicio con canciones y álbumes separados. Tus búsquedas, escuchas y favoritas alimentan recomendaciones; si conectás Navidrome, aparecen sus géneros.
- Descargar desde los tres puntos o el player en segundo plano. Ver descargas en lista o cuadrícula y corregir metadatos ahí mismo.
- Programar tandas de hasta veinte canciones. La rotación opcional se conecta con Navidrome y conserva sus favoritas al renovar los lotes automáticos.
- Escuchar lo descargado, buscar en tu biblioteca por artista y álbum y eliminar canciones con confirmación.
- Elegir una carpeta dentro del almacenamiento de música del servidor.
- Invitar colaboradores y aprobar sus propuestas, manual o automáticamente. También podés dar a una IA una clave revocable para proponer música.

Music Ingest permite escuchar en Stream, guardar favoritas, crear playlists y continuar con Auto DJ. También podés usar **Navidrome** para escuchar los archivos de tu biblioteca desde otros reproductores. Guardá contenido que tengas permiso de descargar.

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

La imagen se descarga de `ghcr.io/lincktendo/music-ingest:0.12.2`. La instalación empieza vacía: no incluye cuentas, contraseñas, claves de proveedores, cookies, música ni datos del autor.

Docker crea dos volúmenes persistentes: `data` para la configuración y `music` para las canciones. Sus nombres efectivos llevan el prefijo del proyecto Compose. No hace falta preparar permisos manualmente para estos volúmenes nuevos. En **Ajustes → Carpeta de salida** elegís una subcarpeta de ese almacenamiento; no es una carpeta del teléfono.

### Tu biblioteca y Navidrome

Music Ingest escribe archivos de música y Navidrome lee esa carpeta compartida. Para la rotación automática que conserva tus favoritas, conectá tu cuenta de Navidrome desde **Ajustes → Rotación de música**. La [guía de instalación y rotación](docs/NAVIDROME-Y-ROTACION.md) explica cómo instalar esta versión sola o junto con Navidrome.

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
| **Barra superior** | Cambiá entre canciones, álbumes y artistas; la búsqueda se actualiza sola. Marcá canciones para descargarlas juntas. |
| **Playlists** | Pegá una lista pública o no listada y elegí una importación única o mantenerla actualizada. |
| **Artistas** | Guardá artistas con su corazón. Administrá por separado las descargas automáticas de sus novedades o catálogo actual. |
| **Descargas** | Revisá progreso y errores, reintentá trabajos y escuchá archivos terminados. |
| **Biblioteca** | Abrí un artista y un álbum, escuchá y, si sos el dueño, eliminá canciones. |
| **Ajustes** | Elegí tu carpeta e invitá colaboradores. En **Usuarios avanzados** ves el motor de descargas, Docker y las conexiones opcionales con IA. |

Cada cuenta tiene su propia biblioteca. Para colaborar, la otra persona primero crea su usuario; después la invitás usando ese nombre. La aprobación manual es el valor inicial. Activar la aprobación automática afecta propuestas nuevas y puede iniciar descargas sin otra confirmación.

El servidor comprueba cada 24 horas si existe una versión estable nueva de yt-dlp. La instala en su volumen de datos después de verificar la firma oficial, el archivo y la versión ejecutable. En **Ajustes → Usuarios avanzados** ves la versión en uso y cuándo se revisó.

Las claves para IA solo permiten buscar, revisar música y proponer canciones en la biblioteca asignada. No permiten leer archivos, aprobar propuestas ni administrar cuentas. Se muestran una vez y se pueden revocar.

LRCLIB y MusicBrainz funcionan inicialmente sin claves. Last.fm es opcional y necesita una clave creada por vos. No se incluyen credenciales de ningún proveedor. La [guía de integraciones](INTEGRATIONS.md) explica qué se envía a cada servicio y cómo configurar tus propias claves.

## Límites de esta beta

- Hasta **50 canciones por envío**, **30 seguimientos por biblioteca** y **5.000 pistas por fuente**. Las importaciones grandes van por turnos.
- Revisión automática diaria por defecto; ajustable desde cada minuto hasta una semana. El servidor debe estar encendido.
- No importa playlists privadas ni mixes personales. La disponibilidad depende de los proveedores; una fuente puede bloquear o dejar de ofrecer una canción.
- Cambiar carpeta afecta futuras descargas; no mueve archivos existentes. Eliminar canciones borra sus archivos y no tiene Deshacer.
- MP3 no mejora la calidad de la fuente. FLAC se ofrece cuando se verifica audio sin pérdida; convertir un MP3 no recupera información. Qobuz depende de las descargas que tu cuenta tenga habilitadas, no basta con tener una suscripción.
- Auto DJ depende del catálogo y de la disponibilidad del proveedor; la precarga reduce la espera, pero una fuente puede fallar o limitar solicitudes. La rotación solo gestiona sus propios lotes y se activa desde Ajustes.
- No incluye recuperación automática de contraseñas ni un despliegue preparado para Internet abierto.

La suite de Linux cubre la selección de formato, archivos FLAC y MP3, aislamiento de bibliotecas, importación de Inicio, rotación y la actualización del motor de descargas. El reproductor cuenta con pruebas de Auto DJ, prioridad de cola y precarga. La conservación de favoritas se verificó además con un Navidrome real y audio sintético. Se revisaron las pantallas en Chromium con tamaños de escritorio y celular. La validación de compras Qobuz usa respuestas de prueba y un archivo de audio generado.

## Actualizar y respaldar

Revisá las notas de la nueva versión y hacé un respaldo antes de cambiar la etiqueta de imagen en `compose.yaml`. Conservá la misma carpeta o el mismo nombre de proyecto Compose (`-p`) de tu instalación; si lo cambiás, Docker puede crear volúmenes nuevos y parecerá que la biblioteca está vacía.

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
