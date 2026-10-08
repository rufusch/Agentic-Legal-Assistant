#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements.lock.txt
fi
export BACKEND_DEMO=1
export BACKEND_STORAGE="$PWD/.data-demo"
export LEXIMIND_MODEL_NUM_THREADS="${LEXIMIND_MODEL_NUM_THREADS:-2}"
exec .venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
