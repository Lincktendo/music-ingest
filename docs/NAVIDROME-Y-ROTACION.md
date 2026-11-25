# Music Ingest con Navidrome y rotación

Hay dos maneras de instalar este proyecto. La primera sirve para descargar y escuchar en Music Ingest o conectar un Navidrome que ya tenés. La segunda levanta Music Ingest y Navidrome en un mismo proyecto de Docker.

Desde la carpeta de la versión **0.11.0** que contiene `compose.yaml`, Docker Compose descarga la imagen publicada de Music Ingest. Estos ejemplos funcionan con Docker para Linux amd64 o Docker Desktop en Windows con contenedores Linux.

## Music Ingest solo

```sh
docker compose up -d
```

Abrí http://localhost:8511 y creá tu usuario.

Para usar tu carpeta actual de música, copiá `.env.example` a `.env`, configurá `MUSIC_FOLDER` con su ruta absoluta y ejecutá la variante con carpeta compartida.

```sh
docker compose -f compose.yaml -f compose.bind.yaml up -d
```

Navidrome tiene que leer esa misma carpeta del equipo. En su contenedor, montala como `/music:ro`. Music Ingest guarda sus cuentas y preferencias en su volumen `data`; Navidrome guarda las suyas en su propia carpeta de datos.

## Music Ingest con Navidrome

```sh
docker compose -f compose.yaml -f compose.navidrome.yaml up -d
```

Abrí Music Ingest en http://localhost:8511 y Navidrome en http://localhost:4533. Creá una cuenta en cada programa. Los servicios comparten el volumen de canciones y Navidrome revisa la música cada minuto. Los puertos se pueden ajustar con `PORT` y `NAVIDROME_PORT` en `.env`.

En Ajustes de Music Ingest, abrí **Rotación de música**. Para conectar el Navidrome de este mismo proyecto usá `http://navidrome:4533`, junto al usuario y contraseña que creaste en Navidrome.

La opción conjunta funciona con el volumen `music`. La opción `compose.bind.yaml` está destinada al montaje independiente y su conexión con un Navidrome existente.

## Construir Music Ingest desde el código

Si modificaste el proyecto o querés probar una copia del código, agregá `compose.build.yaml` y pedí la compilación. Para Music Ingest solo, ejecutá:

```sh
docker compose -f compose.yaml -f compose.build.yaml up -d --build
```

Para compilarlo junto con Navidrome, ejecutá:

```sh
docker compose -f compose.yaml -f compose.build.yaml -f compose.navidrome.yaml up -d --build
```

Para usar la compilación con una carpeta de música existente, sustituí `compose.navidrome.yaml` por `compose.bind.yaml` y configurá `MUSIC_FOLDER`.

## Conectar un Navidrome que ya está funcionando

1. En Ajustes, guardá su dirección, usuario y contraseña. Si está instalado directamente en la misma PC con Docker Desktop, la dirección habitual desde el contenedor es `http://host.docker.internal:4533`. En Linux podés usar una dirección alcanzable desde Docker o el nombre del servicio dentro de una red compartida.
2. Dejá la subcarpeta sugerida. La app también reconoce las rutas virtuales de Navidrome y comprueba que el archivo original sea idéntico al guardado en Music Ingest.
3. Guardá y tocá **Guardar conexión y probar**. Usá la misma cuenta de Navidrome con la que marcás tus favoritos.

Las bibliotecas adicionales de Music Ingest tienen su propia subcarpeta. El campo sugerido tiene en cuenta esa ubicación.

## Descubrir veinte canciones

Activá la descarga automática y elegí la frecuencia. Cada ciclo busca hasta veinte canciones nuevas según las fuentes habilitadas, tu Inicio, tus artistas y tu actividad. Aplica tus preferencias de formato, manda un lote a Descargas y registra su progreso.

Si todavía hay pocas recomendaciones, puede traer menos de veinte. Si no encuentra ninguna nueva, lo indica y vuelve a revisar. Podés alimentar las sugerencias escuchando canciones, marcando artistas favoritos o importando tu Inicio.

El reloj funciona mientras el contenedor está encendido. La frecuencia admite desde un minuto hasta treinta días. Al reiniciar, los lotes interrumpidos retoman sus pistas pendientes.

## Rotar y conservar los favoritos

La opción **Renovar la tanda anterior** está desactivada al principio. Al activarla, después de completar un lote nuevo Music Ingest revisa los lotes anteriores de esta automatización y conserva las canciones marcadas como favoritas con la cuenta conectada. También conserva pistas de álbumes o artistas marcados como favoritos.

Una favorita comprobada pasa a la biblioteca permanente. Quitarle el corazón más adelante no la devuelve a la rotación.

La limpieza busca una coincidencia única por ruta o por título, artista, álbum, número de pista y tamaño. Después compara el contenido completo del archivo original de Navidrome con el archivo local mediante SHA-256. Esta verificación lee el audio desde Navidrome sin guardar otra copia. Cuando una pista sigue pendiente del escaneo, la conexión falla o hay varias coincidencias, permanece guardada y aparece un aviso. Los archivos descargados manualmente y la biblioteca que ya existía quedan fuera de los lotes gestionados.

Después de activar esta función, marcá tus favoritas en esa cuenta de Navidrome antes del siguiente ciclo. Las estrellas de otras cuentas tienen sus propias preferencias.

## Datos de conexión

Music Ingest utiliza la API Subsonic de Navidrome. Guarda en su volumen de datos un token de autenticación y su salt, con permisos privados en Linux. Ese token permite autenticarse y debe tratarse como un secreto. La contraseña original se usa para generar el token y la respuesta de Ajustes solo indica si hay credenciales guardadas.

Cambiar la dirección o el usuario requiere volver a introducir la contraseña. Los ejemplos del repositorio contienen valores de demostración.

La conexión consulta el estado del escaneo, los favoritos y la información del archivo. Documentación oficial de [Navidrome](https://www.navidrome.org/docs/developers/subsonic-api/), [favoritos](https://opensubsonic.github.io/docs/endpoints/getstarred2/), [escaneo](https://opensubsonic.github.io/docs/endpoints/getscanstatus/) y [datos de cada canción](https://opensubsonic.github.io/docs/endpoints/getsong/).
