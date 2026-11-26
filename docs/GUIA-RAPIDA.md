# Music Ingest: guía rápida

## Inicio, Fuentes y calidad de audio

Usá la barra de arriba desde cualquier pantalla para buscar por nombre o pegar un enlace de canción, artista, álbum o playlist de YouTube Music. Para extraer el audio de un video, pegá su enlace directamente. Por defecto busca en YouTube Music (Google). Al agregar otras fuentes también podés buscar entre sus títulos importados y los enlaces que ya revisaste. En **Ajustes → Fuentes de búsqueda** elegís cuáles aparecen en los resultados.

La tuerca de arriba a la izquierda abre **Ajustes**. Ahí elegís la biblioteca activa y administrás tu cuenta. **Fuentes** tiene su propia sección en el menú: las conexiones ya no están al final de Inicio.

En **Inicio** aparecen rolas con portada según tus páginas guardadas y los artistas que escuchaste o descargaste. Elegí **Todo**, **Separar por fuentes** o una plataforma. Desde la tarjeta podés abrir el artista o el álbum y ver el formato que se guardará.

Los **HTML son acumulativos en todas las fuentes**: cada archivo suma referencias nuevas y actualiza las repetidas sin duplicarlas. Se conservan los datos musicales extraídos, no la página completa. Inicio muestra una selección de esa base y va rotando por las referencias anteriores. **Borrar referencias HTML** elimina explícitamente el historial importado de esa fuente.

| Fuente | Cómo usarla |
| --- | --- |
| **YouTube Music · MP3** | Buscá directamente. Para traer sugerencias personales, cargá tus cookies de YouTube o guardá la página de Inicio desde tu navegador y tocá **Subir HTML** en la tarjeta. |
| **Qobuz · FLAC / MP3** | Subí el HTML para descubrir títulos o conectá tu cuenta de la tienda para encontrar las descargas de tus compras. El formato disponible depende de la edición que entregan el artista o la disquera y de los archivos disponibles en tu cuenta. |
| **+ Agregar fuente** | Elegí una plataforma o ingresá su dominio. Podés pegar enlaces de audio o video en la barra. La app revisa qué audio ofrece ese enlace. [Sitios que reconoce yt-dlp](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md). |

**Descargar siempre el audio de mayor calidad** viene encendido. Las fuentes que entregan audio sin pérdida pueden guardarse en FLAC, incluso si el original viene en WAV/PCM. La app puede conservar otros formatos cuando el enlace los ofrece y están habilitados. Apagá el interruptor para preferir MP3 entre los formatos permitidos.

En los **tres puntos** de cada fuente elegís qué formatos aceptar, si participa en Inicio y si es favorita. Favorito da prioridad a sus recomendaciones. Los formatos encendidos aparecen a color. Para una fuente personalizada, los formatos se incorporan después de verificar el audio de sus descargas. La ayuda de HTML y de cookies también está en ese menú. Eliminar una fuente pide dos confirmaciones y conserva las rolas guardadas.

Music Ingest también guarda archivos en tu servidor. Navidrome puede leer esa misma carpeta para reproducirlos desde otros dispositivos.

## Escuchar y elegir

En **Stream**, tocá una portada para escuchar mientras navegás. Los **tres puntos → Agregar a Favoritas** guardan la rola en **Favoritas**, accesible desde el corazón del menú. También podés abrir tus listas desde Playlists o Biblioteca. El botón **Agregar a playlist** del reproductor te permite armar tus listas. Para ver qué va a sonar después, tocá **Ver próximas rolas**: la lista se despliega sobre el reproductor, sin bloquear la pantalla. Desde Favoritas se carga la colección completa: la elegida primero y el resto desde la más reciente. Auto DJ muestra hasta diez sugerencias y repone la cola mientras escuchás.

En modo **Descargar**, tocar la portada abre la ficha de la rola. También podés abrirla desde el ícono de descarga del reproductor. Revisá los datos y usá el lápiz para encuadrar la portada. **Descargar** muestra el porcentaje y te deja escuchar el archivo al terminar. **Mandar a cola** sigue en segundo plano y te avisa al finalizar. La pestañita verde indica que la rola ya está en Biblioteca. Podés volver a editar los datos y la portada desde ahí.

El nombre del artista abre su ficha y el del disco abre el álbum. Tocá el **corazón del artista** para guardarlo en **Artistas**, identificado con una persona en el menú. Guardarlo no activa descargas automáticas. Para elegir varias rolas, abrí los tres puntos de una portada y tocá **Seleccionar**. En el celular, mantené presionada la primera portada. Luego tocá otras para sumarlas. Podés descargar la selección, ocultarla de Inicio o guardar a sus artistas.

Al entrar por primera vez aparece un recorrido. Tocá **No volver a mostrar** para omitirlo en ese navegador. Podés repetirlo desde **Ajustes → Ver recorrido**.

## Empezá por acá

1. Instalá con [Docker Compose](../README.md#instalación-con-docker) y abrí `http://localhost:8511`.
2. Creá tu cuenta. No hay usuario, contraseña ni claves incluidos.
3. En **Ajustes → Carpeta de salida**, elegí dónde guardar dentro del almacenamiento conectado al servidor. Ese cambio aplica a las próximas descargas.
4. Buscá una canción y descargala. Cuando termine, tocá **Escuchar** en Descargas o Biblioteca.

## Lo que podés automatizar

| Quiero… | Dónde y cómo |
| --- | --- |
| Varias canciones juntas | Marcá sus casillas en los resultados y tocá **Descargar**. Hasta 50 por envío. **Deseleccionar** limpia la selección. |
| Un álbum | Abrilo, marcá sus pistas y confirmá la descarga. |
| Una playlist | En **Playlists**, pegá el enlace y elegí solo lo que tiene ahora o también sus futuras incorporaciones. |
| Seguir a un artista | Buscalo en **Artistas**, abrí su ficha y tocá **Mantener su música al día**. Marcá **Incluir también toda su música actual** si querés el catálogo disponible, además de las novedades. |
| Cambiar cada cuánto revisa | En **Playlists → Revisiones automáticas**. Por defecto es diario; el servidor tiene que estar encendido. |
| Ordenar y revisar lo guardado | **Biblioteca** agrupa por artista y álbum; buscá, escuchá o guardá un archivo. **Eliminar** borra la canción del servidor tras confirmarlo. |
| Agregar familia o amigos | Primero crean su cuenta. En **Ajustes**, invitalos por su usuario. Sus propuestas necesitan tu aprobación, salvo que actives el modo automático. |
| Pedirle música a una IA | Creá una clave en **Ajustes → Usuarios avanzados → Tu IA**, copiala una vez y compartila solo con tu herramienta. Puede proponer canciones; no leer tu biblioteca ni administrarla. |

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

En **Fuentes**, los **tres puntos → Ayuda** de cada fuente dan acceso a tres pasos con una demostración del mouse. Podés avanzar a tu ritmo o elegir la imagen fija. La ayuda de Qobuz incluye el enlace opcional de su tienda. Music Ingest es gratis.

En **Ajustes → Usuarios avanzados** podés consultar el estado de yt-dlp, las carpetas de Docker y las conexiones de IA. El servidor revisa yt-dlp una vez al día por su cuenta.

## Auto DJ y próximas rolas

En el reproductor, **Seguir** decide si avanzar a la próxima rola o detenerse al terminar la actual. Con clic derecho en una canción, elegí **Reproducir a continuación**. En la cola podés arrastrar las filas para cambiar el orden.

**Auto DJ** abre la selección de canciones o álbumes, criterio, cantidad, momento para recargar la cola y repetidas. Music Ingest prepara la próxima pista para reducir la espera. Una fuente lenta o que falle puede requerir otro intento.

## Rotación y Navidrome

En **Ajustes → Rotación de música**, activá tandas de hasta veinte canciones y elegí cada cuánto descargarlas. **Renovar la tanda anterior** conserva las favoritas de la cuenta de Navidrome conectada y retira las demás canciones de tandas automáticas anteriores, después de completar una tanda nueva.

La [guía de instalación y conexión](NAVIDROME-Y-ROTACION.md) incluye Music Ingest solo y el proyecto conjunto con Navidrome.

El logo de la barra lateral se puede arrastrar desde cualquier sección para hacerlo girar. Un clic le da impulso y abre Inicio. Los iconos de fuente sobre las portadas usan el color de su plataforma. SoundCloud es opcional y se agrega desde **Fuentes → Agregar fuente**.

## Novedades del reproductor

El icono de descarga del miniplayer manda la rola a segundo plano; un segundo toque abre sus datos. Los tres puntos de cada tarjeta ofrecen descarga, favorita, reproducir a continuación, agregar a cola, abrir álbum y agregar a playlist. El distintivo verde indica que ya existe en tu biblioteca.

En **Descargas** elegís lista o cuadrícula y editás los metadatos de archivos terminados. Para varios artistas escribí `Artista uno; Artista dos`.

Al importar una playlist podés marcar **También agregar a mis playlists locales**. Su contenido aparecerá al terminar la revisión y se incorpora al abrir las listas.

La barra de búsqueda muestra las consultas de texto recientes con opción de borrarlas; los enlaces no entran al historial. Inicio separa canciones y álbumes. Los géneros usan tu conexión configurada con Navidrome, si está disponible.

En **Ajustes → Usuarios avanzados → Recomendaciones** podés personalizar los pesos del algoritmo mediante JSON. Vacío conserva el comportamiento predeterminado. Ese campo no ejecuta código.
