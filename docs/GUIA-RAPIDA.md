# Music Ingest: guía rápida

**Buscás → descargás → escuchás.** Music Ingest guarda archivos en tu servidor; Navidrome puede leer esa misma carpeta para ofrecerlos como streaming.

## Empezá por acá

1. Instalá con [Docker Compose](../README.md#instalación-con-docker) y abrí `http://localhost:8511`.
2. Creá tu cuenta. No hay usuario, contraseña ni claves incluidos.
3. En **Tu espacio → Carpeta de salida**, elegí dónde guardar dentro del almacenamiento conectado al servidor. Ese cambio aplica a las próximas descargas.
4. Buscá una canción y descargala. Cuando termine, tocá **Escuchar** en Descargas o Biblioteca.

## Lo que podés automatizar

| Quiero… | Dónde y cómo |
| --- | --- |
| Varias canciones juntas | En **Buscar**, marcá sus checks y tocá **Descargar todo**. Hasta 50 por envío. **Deseleccionar** limpia la selección. |
| Un álbum | Abrilo, marcá sus pistas y confirmá la descarga. |
| Una playlist | En **Playlists**, pegá el enlace y elegí solo lo que tiene ahora o también sus futuras incorporaciones. |
| Seguir a un artista | Buscalo en **Artistas**, abrí su ficha y tocá **Mantener su música al día**. Marcá **Incluir también toda su música actual** si querés el catálogo disponible, además de las novedades. |
| Cambiar cada cuánto revisa | En **Playlists → Revisiones automáticas**. Por defecto es diario; el servidor tiene que estar encendido. |
| Ordenar y revisar lo guardado | **Biblioteca** agrupa por artista y álbum; buscá, escuchá o guardá un archivo. **Eliminar** borra la canción del servidor tras confirmarlo. |
| Agregar familia o amigos | Primero crean su cuenta. En **Tu espacio**, invitalos por su usuario. Sus propuestas necesitan tu aprobación, salvo que actives el modo automático. |
| Pedirle música a una IA | Creá una clave en **Tu espacio → Tu IA**, copiala una vez y compartila solo con tu herramienta. Puede proponer canciones; no leer tu biblioteca ni administrarla. |

## Usar lo descargado con Navidrome

Las dos aplicaciones necesitan ver los **mismos archivos**. La carpeta que aparece dentro de Docker como `/music` puede ser un volumen administrado por Docker o una carpeta de tu computadora. Elegir una subcarpeta en Music Ingest no conecta automáticamente un disco nuevo: primero tiene que estar montado en el contenedor.

**Opción A: empezar con las dos aplicaciones.** Desde la carpeta del proyecto ejecutá:

```sh
docker compose -f compose.yaml -f compose.navidrome.yaml up -d
```

Abrí `http://localhost:8511` para Music Ingest y `http://localhost:4533` para Navidrome. Creá una cuenta en cada una. Este ejemplo comparte el volumen de música; Navidrome lo lee en modo de **solo lectura** y lo revisa cada minuto.

**Opción B: usar la carpeta de tu Navidrome existente.** Copiá `.env.example` a `.env`, agregá `MUSIC_FOLDER` con la ruta absoluta de esa carpeta en el servidor de Docker y ejecutá:

```sh
docker compose -f compose.yaml -f compose.bind.yaml up -d
```

La carpeta debe existir y ser escribible para `10001:10001` en Linux. Music Ingest guardará allí; en tu Navidrome ejecutá un escaneo para ver las canciones nuevas. No se modifica su configuración ni se necesita su contraseña. Elegí **A o B**, sin combinar los dos archivos adicionales.

**Si hay varias cuentas:** no compartas la raíz de `/music` indiscriminadamente. Esa raíz puede contener bibliotecas de distintas personas. Montá únicamente la subcarpeta correspondiente a quien va a escucharla; el acceso de Navidrome es independiente de los permisos de Music Ingest.

## Dos detalles para evitar sorpresas

- Cada instalación empieza vacía. Letras y géneros dependen de que los proveedores tengan una coincidencia; las claves opcionales las crea y configura cada usuario. [Cómo configurar integraciones](../INTEGRATIONS.md).
- Dejar de seguir una playlist o artista no borra lo descargado. Cambiar carpeta no mueve canciones anteriores. Respaldá configuración y música antes de actualizar o reorganizar archivos.
