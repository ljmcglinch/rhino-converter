#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

failed() {
  echo
  echo "Build failed. Read the error above; no working Mac package is claimed."
  if [[ "${1:-}" != "--no-pause" ]]; then read -r -p "Press Return to close... " || true; fi
}
trap 'failed "${1:-}"' ERR

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Run this script on a Mac to build the Mac application."
  exit 1
fi
if ! command -v python3.12 >/dev/null 2>&1; then
  echo "Install Python 3.12 from https://www.python.org/downloads/macos/ first."
  echo "Coworkers will not need Python after the app is built."
  if [[ "${1:-}" != "--no-pause" ]]; then read -r -p "Press Return to close... " || true; fi
  exit 1
fi
python3.12 - <<'PY'
import platform
import sys
import tkinter
if sys.version_info[:2] != (3, 12):
    raise SystemExit('The build requires Python 3.12.')
if int(platform.mac_ver()[0].split('.')[0]) < 14:
    raise SystemExit('These pinned engine dependencies require macOS 14 or newer.')
print('Building for', platform.machine(), 'on macOS', platform.mac_ver()[0])
PY
if [[ ! -x .venv/bin/python ]]; then
  python3.12 -m venv .venv
fi
.venv/bin/python -c 'import sys; assert sys.version_info[:2] == (3, 12), "Recreate .venv with Python 3.12"'
.venv/bin/python install_dependencies.py --build
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m PyInstaller --noconfirm --clean --onedir --windowed \
  --name RhinoConverter --icon "assets/RhinoConverter.icns" --add-data "assets:assets" --add-data "VERSION.txt:." --add-data "update-config.json:." --hidden-import mac_update --collect-all cryptography --osx-bundle-identifier com.rhinoconverter.desktop \
  --paths vendor --collect-all OCP --collect-all rhino3dm \
  --collect-submodules serpentine3d \
  --copy-metadata numpy --copy-metadata cadquery-ocp-novtk \
  --copy-metadata rhino3dm app.py
cp README.txt THIRD-PARTY-NOTICES.txt LICENSE.txt \
  vendor/Serpentine3D-LICENSE.txt dist/RhinoConverter.app/Contents/Resources/
build_version="$(tr -d '\r\n' < VERSION.txt)"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString ${build_version}" dist/RhinoConverter.app/Contents/Info.plist || \
  /usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString string ${build_version}" dist/RhinoConverter.app/Contents/Info.plist
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion ${build_version}" dist/RhinoConverter.app/Contents/Info.plist || \
  /usr/libexec/PlistBuddy -c "Add :CFBundleVersion string ${build_version}" dist/RhinoConverter.app/Contents/Info.plist
# Refresh the development signature after adding resources and bundle metadata.
codesign --force --deep --sign - dist/RhinoConverter.app
build_arch="$(.venv/bin/python -c 'import platform; print(platform.machine())')"
ditto -c -k --sequesterRsrc --keepParent dist/RhinoConverter.app \
  "dist/RhinoConverter-Mac-${build_arch}.zip"
echo
echo "Done. Open dist/RhinoConverter.app and test your office sample files."
echo "Share dist/RhinoConverter-Mac-${build_arch}.zip with matching Macs."
echo "Build separately on Apple Silicon and Intel for both architectures."
if [[ "${1:-}" != "--no-pause" ]]; then read -r -p "Press Return to close... " || true; fi
