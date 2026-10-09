#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Run this launcher on a Mac."
  exit 1
fi
if [[ ! -x .venv/bin/python ]]; then
  echo "Run Build-Mac.command first to install the engine."
  read -r -p "Press Return to close... " || true
  exit 1
fi
if ! .venv/bin/python app.py; then
  read -r -p "The app exited with an error. Press Return to close... " || true
  exit 1
fi
