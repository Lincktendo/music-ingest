#!/bin/sh
set -eu
mkdir -p /tmp/suite/tests /tmp/test-deps
cp /app/app.py /app/core.py /app/accounts.py /app/account_routes.py /app/integrations.py /app/automation.py /app/storage.py /tmp/suite/
cp /tests/test_*.py /tmp/suite/tests/
python -m pip install --quiet --no-cache-dir --no-deps --target /tmp/test-deps httpx==0.28.1 httpcore==1.0.9
export PYTHONPATH=/tmp/test-deps:/tmp/suite
python -m unittest discover -s /tmp/suite/tests -v
