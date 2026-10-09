#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Build the Mac installer on a Mac."
  exit 1
fi
failed() {
  echo "Disk image build failed. Read the error above; do not share an older image."
  if [[ "${1:-}" != "--no-pause" ]]; then read -r -p "Press Return to close... " || true; fi
}
trap 'failed "${1:-}"' ERR
bash Build-Mac.command --no-pause
build_arch="$(.venv/bin/python -c 'import platform; print(platform.machine())')"
stage="$(mktemp -d "${TMPDIR:-/tmp}/rhino-converter-dmg.XXXXXX")"
trap 'rm -rf "$stage"' EXIT
ditto dist/RhinoConverter.app "$stage/RhinoConverter.app"
ln -s /Applications "$stage/Applications"
cat > "$stage/Install.txt" <<'TEXT'
Drag RhinoConverter.app onto the Applications folder.
Open Rhino Converter from Applications.
Rhino and Python are not required.
TEXT
hdiutil create -volname "Rhino Converter" -srcfolder "$stage" \
  -format UDZO -ov "dist/RhinoConverter-Mac-${build_arch}.dmg"
echo
echo "Done. Test dist/RhinoConverter-Mac-${build_arch}.dmg, then share it."
echo "Coworkers open the disk image and drag the app into Applications."
if [[ "${1:-}" != "--no-pause" ]]; then read -r -p "Press Return to close... " || true; fi
