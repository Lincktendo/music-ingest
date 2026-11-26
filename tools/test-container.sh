#!/bin/sh
set -eu
mkdir -p /tmp/suite/tests /tmp/test-deps
cp /app/playlist_imports.py /app/recommendations.py /app/rotation.py /app/download_tools.py /app/listening_collection.py /app/listening.py /app/home_recordings.py /app/audio_formats.py /app/extractor_updates.py /app/app.py /app/core.py /app/accounts.py /app/account_routes.py /app/integrations.py /app/automation.py /app/storage.py /app/source_sessions.py /app/qobuz_store.py /app/music_home.py /app/source_catalog.py /app/public_audio_worker.py /app/sources.py /app/source_routes.py /tmp/suite/
cp /tests/test_*.py /tmp/suite/tests/
python -m pip install --quiet --no-cache-dir --no-deps --target /tmp/test-deps httpx==0.28.1 httpcore==1.0.9
export PYTHONPATH=/tmp/test-deps:/tmp/suite
python -m unittest discover -s /tmp/suite/tests -v
