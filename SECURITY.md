# Seguridad y privacidad

## Alcance

Music Ingest 0.4.0-beta.1 está pensado para una computadora propia o una red privada de confianza. La autenticación y el aislamiento de bibliotecas no convierten esta beta en un servicio listo para Internet abierto. El Compose predeterminado publica el puerto solamente en `127.0.0.1`.

El registro está abierto a quienes puedan acceder a la instancia. Creá tu cuenta antes de compartir acceso y no abras puertos del router directamente hacia la aplicación. No montes el socket de Docker, la raíz del host, carpetas de claves ni archivos de otras aplicaciones dentro del contenedor.

## Qué guarda y qué comparte

- El volumen `data` contiene cuentas, hashes de contraseñas y claves de acceso, sesiones, cola, ajustes e historial de automatizaciones.
- Las claves opcionales de proveedores se almacenan por biblioteca en archivos con permisos `0600` en Linux. **No están cifradas en reposo.** Protegé el volumen y los respaldos.
- Las búsquedas y consultas de metadatos contactan servicios externos. Estos reciben los datos necesarios de la consulta y pueden ver la IP de salida de tu servidor. Consultá [INTEGRATIONS.md](INTEGRATIONS.md).
- El repositorio y la imagen no deben incluir datos de instalaciones, claves, cookies, cuentas ni bibliotecas personales.
- Un colaborador puede escuchar y descargar la biblioteca compartida. Revocarlo no recupera archivos que ya haya descargado.
- Una clave para IA puede proponer canciones; con aprobación automática activa, esas propuestas pueden iniciar descargas. Tratala como una contraseña y revocala cuando deje de ser necesaria.
- Compartir el volumen de música con otra aplicación le da acceso a los archivos montados, independientemente de los permisos de Music Ingest. Montá solo la biblioteca requerida, preferentemente en modo de solo lectura para reproductores.

## Reportar un problema

Para una vulnerabilidad, usá [Report a vulnerability](https://github.com/Lincktendo/music-ingest/security/advisories/new) en GitHub. Si el formulario privado no está disponible, abrí un issue pidiendo un canal privado, sin detalles explotables ni información sensible.

Incluí versión, comportamiento esperado, pasos mínimos con datos ficticios y el impacto. **No adjuntes** `.env`, bases de datos, cookies, tokens, volúmenes, respaldos ni registros completos sin revisarlos. Ocultá nombres, direcciones y claves de las capturas. Para problemas normales de uso, abrí un [issue](https://github.com/Lincktendo/music-ingest/issues).

No se promete un tiempo de respuesta ni ausencia de vulnerabilidades. Las correcciones de esta beta se publicarán en una nueva versión; no hay soporte indefinido de versiones antiguas.
