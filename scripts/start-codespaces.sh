#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
bash scripts/setup-codespaces.sh
exec .venv/bin/python -m scripts.run_codespaces
