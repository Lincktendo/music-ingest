FROM denoland/deno:bin@sha256:b507583d3c68ba69f3ed2ce5969ae5b8b70f43421c781279c7aea06435263543 AS deno
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
LABEL org.opencontainers.image.source="https://github.com/Lincktendo/music-ingest" \
      org.opencontainers.image.title="Music Ingest" \
      org.opencontainers.image.licenses="GPL-3.0-or-later" \
      org.opencontainers.image.version="0.4.0-beta.1"
COPY --from=deno /deno /usr/local/bin/deno
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 music && useradd --uid 10001 --gid music --no-create-home music \
    && mkdir -p /app /data /music && chown music:music /data /music
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY tools/image_inventory.py /tmp/image_inventory.py
RUN python /tmp/image_inventory.py && rm /tmp/image_inventory.py
COPY app.py core.py accounts.py account_routes.py integrations.py automation.py storage.py /app/
COPY static /app/static
COPY LICENSE THIRD_PARTY_NOTICES.md /app/
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DATA_DIR=/data MUSIC_DIR=/music HOME=/tmp
USER 10001:10001
EXPOSE 8511
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8511/api/health',timeout=3)"
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8511", "--no-access-log"]
