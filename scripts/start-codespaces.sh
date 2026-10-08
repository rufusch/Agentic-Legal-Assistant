#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -x .venv/bin/python ]]; then
  bash scripts/setup-codespaces.sh
fi
exec .venv/bin/python -m scripts.run_codespaces
