# Colaborar

Gracias por ayudar a que Music Ingest sea más fácil de usar. Abrí un issue para cambios grandes; para correcciones pequeñas, enviá un pull request con el problema, el cambio y cómo lo comprobaste.

## Ejecutar pruebas

Usá Python 3.12 en un entorno virtual. Los tests usan datos temporales; no los apuntes a una instalación con música o cuentas reales.

```sh
python -m venv .venv
```

Activá el entorno virtual según tu sistema y ejecutá:

```sh
python -m pip install -r requirements.txt
python -m pip install httpx
python -m unittest discover -s tests -v
```

Para construir una imagen local:

```sh
docker build -t music-ingest:dev .
```

Probá cambios visuales con escritorio y pantalla angosta. Revisá navegación por teclado, los nombres de los botones y el aislamiento entre cuentas. Evitá cambios que añadan acceso al host o devuelvan secretos al navegador.

## Antes de enviar

- Incluí pruebas cuando el comportamiento o la seguridad lo necesiten.
- Usá datos y audios sintéticos o con permiso. No adjuntes música comercial ni portadas como material de prueba.
- No incluyás `.env`, claves, cookies, bases de datos, cuentas, registros de producción, direcciones privadas ni respaldos.
- No pegues tokens en comandos de ejemplo ni capturas.
- Conservá las licencias y atribuciones del código de terceros.

Las contribuciones al código del proyecto se reciben bajo GPL-3.0-or-later. Reportá vulnerabilidades por el canal de [SECURITY.md](SECURITY.md), no en un issue público con detalles sensibles.
