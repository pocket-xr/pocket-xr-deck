#!/bin/bash
# Builds dist/pocket-xr-deck.tar.gz: what a release carries and the install line in the README downloads.
set -euo pipefail
cd "$(dirname "$0")"
python3 tests/test_offline.py >/dev/null
python3 tests/test_space.py >/dev/null
rm -rf dist && mkdir -p dist/pocket-xr-deck
cp -r pocketxr assets install.sh uninstall.sh VERSION README.md LICENSE dist/pocket-xr-deck/
# PC VR's native libraries (native/build.sh): ALVR's client and Pocket XR's bridge
if [ -f native/out/libpxr_pcvr.so ]; then
  mkdir -p dist/pocket-xr-deck/native
  cp native/out/libalvr_client_core.so native/out/libpxr_pcvr.so dist/pocket-xr-deck/native/
else
  echo "note: no PC VR libraries in native/out (run native/build.sh); the release has no PC VR" >&2
fi
# Gaming Mode's Quick Access panel for Decky (decky/, built with npm run build there)
if [ -f decky/dist/index.js ]; then
  mkdir -p dist/pocket-xr-deck/decky/dist
  cp decky/plugin.json decky/package.json decky/main.py dist/pocket-xr-deck/decky/
  cp decky/dist/index.js dist/pocket-xr-deck/decky/dist/
else
  echo "note: no Decky panel in decky/dist (run npm run build in decky/); the release has no Quick Access panel" >&2
fi
find dist -name '__pycache__' -prune -exec rm -rf {} +
tar -C dist -czf dist/pocket-xr-deck.tar.gz pocket-xr-deck
echo "dist/pocket-xr-deck.tar.gz ($(cat VERSION))"
