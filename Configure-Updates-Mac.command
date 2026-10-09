#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  echo "Run Build-Mac.command once to create the build environment first."
  read -r -p "Press Return to close... " || true
  exit 1
fi
.venv/bin/python install_dependencies.py
.venv/bin/python release_tools.py configure
echo "Rebuild the app and commit source with update-config.json. Keep the private key outside the project."
read -r -p "Press Return to close... " || true
