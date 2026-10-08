#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 - <<'PY'
import platform
import sys
if sys.version_info[:2] != (3, 12) or platform.libc_ver()[0] != 'glibc':
    sys.exit('CaseLens Codespaces requires Python 3.12 on Debian/glibc. '
             'Run Codespaces: Rebuild Container to use .devcontainer/devcontainer.json. '
             'Alpine/musl cannot install the pinned ONNX Runtime wheel.')
PY
if command -v apt-get >/dev/null 2>&1; then
  missing=0
  for package in libglib2.0-0 libgl1 fonts-dejavu-core antiword; do
    dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q 'install ok installed' || missing=1
  done
  if [[ "$missing" == 1 ]]; then
    # The base image may contain unrelated third-party repositories (e.g. Yarn)
    # with expired keys. These packages all come from Debian; keep its signature
    # checks and avoid refreshing repositories this application does not use.
    apt_options=()
    if [[ -f /etc/apt/sources.list.d/debian.sources ]]; then
      apt_options=(-o Dir::Etc::sourcelist=sources.list.d/debian.sources -o Dir::Etc::sourceparts=-)
    fi
    if [[ "$EUID" == 0 ]]; then
      apt-get "${apt_options[@]}" update
      apt-get "${apt_options[@]}" install -y --no-install-recommends libglib2.0-0 libgl1 fonts-dejavu-core antiword
    else
      sudo -n apt-get "${apt_options[@]}" update
      sudo -n apt-get "${apt_options[@]}" install -y --no-install-recommends libglib2.0-0 libgl1 fonts-dejavu-core antiword
    fi
  fi
fi
if [[ -e .venv ]] && ! .venv/bin/python -c 'import sys; assert sys.version_info[:2] == (3, 12); import platform; assert platform.libc_ver()[0] == "glibc"' 2>/dev/null; then
  backup="$(mktemp -d .venv-preserved-XXXXXXXX)"
  mv .venv "$backup/environment"
  printf 'Preserved incompatible virtual environment in %s/environment\n' "$backup"
fi
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
.venv/bin/python - <<'PY'
import sys
if sys.version_info[:2] != (3, 12):
    sys.exit('The existing .venv uses a different Python version. Rename .venv, '
             'then rerun bash scripts/setup-codespaces.sh with Python 3.12.')
PY
.venv/bin/python -m pip install -r requirements.lock.txt
.venv/bin/python -m pip check
printf '\nSetup complete. Start the website: bash scripts/start-codespaces.sh\n'
