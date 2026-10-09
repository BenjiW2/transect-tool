#!/bin/bash
# Builds "Transect Tool.app" and a .dmg for Apple-silicon Macs (macOS 13+).
# Needs uv (https://docs.astral.sh/uv/) – it fetches a portable Python, so the app doesn't depend on
# whatever Python is installed on the build machine.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
BUILD=${BUILD_DIR:-/tmp/transect-tool-build}
VERSION=$(cat packaging/VERSION)

echo "==> Python environment"
rm -rf "$BUILD/venv"
uv venv -q --python 3.12 --python-preference only-managed "$BUILD/venv"
# --python-platform makes uv pick wheels that run on macOS 13+, not just this machine's macOS
VIRTUAL_ENV="$BUILD/venv" uv pip install -q --python-platform aarch64-apple-darwin \
  -r requirements.txt pywebview pyinstaller

echo "==> Building app"
"$BUILD/venv/bin/pyinstaller" --noconfirm --clean \
  --distpath "$BUILD/dist" --workpath "$BUILD/work" packaging/TransectTool.spec
APP="$BUILD/dist/Transect Tool.app"

echo "==> Signing (ad-hoc)"
codesign --force --deep --sign - "$APP"
codesign --verify --deep "$APP"

echo "==> Disk image"
STAGE="$BUILD/dmg"
rm -rf "$STAGE" && mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
cp packaging/FIRST_OPEN.txt "$STAGE/How to open the first time.txt"
mkdir -p "$ROOT/dist"
DMG="$ROOT/dist/Transect-Tool-$VERSION-mac.dmg"
rm -f "$DMG"
hdiutil create -quiet -volname "Transect Tool" -srcfolder "$STAGE" -format UDZO -ov "$DMG"
echo
echo "Built: $DMG ($(du -h "$DMG" | cut -f1))"
