# Integraciones y acceso para IA

Esta guía explica cómo usa Music Ingest los proveedores de letras y géneros y qué puede hacer una herramienta con una clave de IA. Los ejemplos usan valores ficticios.

## Configuración por biblioteca

Solo el propietario puede abrir y cambiar los proveedores de su biblioteca en Ajustes → Usuarios avanzados. Las demás bibliotecas tienen ajustes independientes. Los campos de contraseña aparecen vacíos aunque ya exista una clave: dejarlos vacíos conserva la clave guardada; marcar «Eliminar la clave guardada» la borra.

La configuración indica si guardaste una clave. Music Ingest guarda las claves de los proveedores en archivos privados de cada biblioteca dentro del volumen persistente `data`, con permisos `0600` en Linux y sin cifrado en reposo. Si querés conectar una fuente con tus cookies, subí vos el archivo desde su tarjeta en Inicio.

Cuando una integración está activa, se envían al proveedor los datos necesarios de la canción, como título, artista, álbum y duración. No se envían las cuentas de Music Ingest ni los archivos de audio. Las respuestas se guardan temporalmente en memoria para reducir consultas.

## LRCLIB: letras

Está activado inicialmente y funciona sin registro. Consulta letras normales y sincronizadas; verifica título, artista y duración antes de añadirlas. Si no hay coincidencia suficiente, informa que falta la letra. La disponibilidad de letras sincronizadas depende del catálogo.

Para una clave opcional:

1. Abrí el [portal de desarrolladores de LRCLIB](https://lrclib.net/developers).
2. Registrá una aplicación de servidor siguiendo sus instrucciones.
3. Si obtenés una API key de servidor, pegala en **Ajustes → Usuarios avanzados → Letras y géneros** y guardá.

La aplicación usa el encabezado de clave del servidor cuando está configurado. También identifica la aplicación con User-Agent y respeta las respuestas de espera del proveedor. Consultá la [documentación oficial](https://lrclib.net/docs) para sus requisitos vigentes.

## MusicBrainz: géneros

Está activado inicialmente y no necesita cuenta ni clave. Busca una grabación por artista, título y duración. Si no hay géneros de la grabación, puede usar los de un artista con nombre coincidente y no ambiguo; esa diferencia aparece como «Géneros del artista».

No convierte etiquetas arbitrarias en géneros ni elige entre varios artistas homónimos. Las consultas se serializan y separan por más de un segundo en esta instancia, según la [política de solicitudes](https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting). La [API oficial](https://musicbrainz.org/doc/MusicBrainz_API) documenta los datos disponibles.

## Last.fm: fuente adicional de géneros

Está desactivado inicialmente. Necesita una API key propia; no necesita Shared Secret, contraseña de Last.fm ni una sesión de escucha.

1. Iniciá sesión o creá una cuenta en Last.fm.
2. Abrí [Crear una API key](https://www.last.fm/api/account/create) y completá el registro de tu aplicación.
3. Copiá únicamente el campo **API key**, de 32 caracteres hexadecimales. Podés revisar tus aplicaciones en [API accounts](https://www.last.fm/api/accounts).
4. En **Ajustes → Usuarios avanzados → Letras y géneros**, pegá la clave, activá Last.fm y guardá.

Se consulta [track.getTopTags](https://www.last.fm/api/show/track.getTopTags). Se verifica la identidad de la pista y se conserva solo una lista limitada de etiquetas reconocidas como géneros, descartando categorías como favoritos o «seen live». Esto reduce ruido, pero puede omitir géneros poco comunes; no garantiza cobertura completa.

## DuckDuckGo: experimental

Está desactivado inicialmente y no necesita clave. Conserva una integración opcional con Instant Answers, cuya [documentación oficial está archivada](https://github.com/duckduckgo/duckduckgo-publisher/blob/master/share/site/duckduckgo/api.tx).

Solo acepta el campo estructurado Genre/Genres cuando el nombre del artista coincide y existe una fuente de Wikipedia validada. No extrae géneros de párrafos, no hace una búsqueda web completa y no promete resultados. La interfaz conserva la atribución a DuckDuckGo y a la fuente original. Si el servicio no responde o la coincidencia no es clara, no añade datos y el audio se conserva.

## Qué ocurre si falla un proveedor

Las peticiones usan destinos fijos, conexión HTTPS, tiempos de espera, límites de respuesta y no siguen redirecciones. Las respuestas de límite de uso activan una espera; no hay un bucle de reintentos inmediatos. Un error no expone claves ni mensajes crudos del proveedor en la interfaz y no impide guardar el audio.

La biblioteca indica si la letra es sincronizada, normal, instrumental, no encontrada o no verificable. Cuando se obtuvo una letra sincronizada, el archivo `.lrc` se puede descargar aparte. Los metadatos son resultados de terceros, no una garantía de exactitud absoluta.

## Clave de Music Ingest para una IA

Esta clave es distinta de las claves de LRCLIB o Last.fm. Se crea en Ajustes → Usuarios avanzados → Tu IA, se muestra una sola vez y queda vinculada a una biblioteca. Al revocarla deja de permitir nuevas peticiones. No la entregues a una herramienta que no quieras autorizar.

| Acción con clave de IA | Permitida |
| --- | --- |
| Buscar canciones, álbumes y artistas; previsualizar pistas | Sí |
| Enviar propuestas y consultar sus propias propuestas | Sí |
| Aprobar o rechazar propuestas | No |
| Descargar archivos o consultar el contenido de la biblioteca | No |
| Administrar miembros, cuentas, claves o proveedores | No |

El propietario puede activar aprobación automática para las propuestas nuevas de esa biblioteca. Con ella activa, una propuesta válida de la IA puede iniciar una descarga; el permiso no da acceso a los archivos resultantes.

### Ejemplos HTTP

Reemplazá `BASE_URL` por la dirección de tu instancia privada y `YOUR_MUSIC_INGEST_KEY` por una clave creada para la herramienta. Los identificadores se obtienen de la búsqueda y la previsualización; no se aceptan URLs de portada ni metadatos arbitrarios enviados por el cliente.

```http
GET BASE_URL/api/search?q=ARTIST_OR_SONG&kind=songs
Authorization: Bearer YOUR_MUSIC_INGEST_KEY
```

`kind` acepta `songs`, `albums` y `artists`. Para revisar una pista o un álbum:

```http
POST BASE_URL/api/preview
Authorization: Bearer YOUR_MUSIC_INGEST_KEY
Content-Type: application/json

{"id":"RESULT_ID","type":"song"}
```

Para un álbum usá `"type":"album"`. Elegí los identificadores de pista verificados que devuelve esa previsualización:

```http
POST BASE_URL/api/proposals
Authorization: Bearer YOUR_MUSIC_INGEST_KEY
Content-Type: application/json

{"tracks":[{"id":"TRACK_ID_11"}],"format":"auto"}
```

Reemplazá `TRACK_ID_11` por el identificador exacto que devolvió la previsualización. YouTube usa IDs de 11 caracteres, Qobuz usa el prefijo `qb:` y las pistas de otras fuentes pueden llevar `ex:`. Cada propuesta admite entre 1 y 50 pistas distintas. La respuesta indica `pending` o `approved`, según la configuración de la biblioteca.

Usá `"format":"auto"` u omití `format` para aplicar la preferencia de calidad de la biblioteca. Si necesitás un formato concreto, elegí uno que la previsualización ofrezca para **todas** las pistas del envío. Los valores posibles son `mp3`, `flac`, `wav`, `alac`, `aac`, `opus`, `ogg` y `aiff`. El valor heredado `original` pide el mejor formato habilitado. Para comprobar que una selección conserva el formato que se mostró al usuario, podés enviar `expected_format` en cada pista junto con su `id`.

```http
GET BASE_URL/api/proposals
Authorization: Bearer YOUR_MUSIC_INGEST_KEY

GET BASE_URL/api/proposals/PROPOSAL_ID
Authorization: Bearer YOUR_MUSIC_INGEST_KEY
```

La clave ya determina la biblioteca: no necesitás un parámetro `library`. Una clave no puede elegir otra biblioteca ni consultar las propuestas de otras claves. Las rutas de configuración de proveedores requieren la sesión del propietario y rechazan claves de IA.
