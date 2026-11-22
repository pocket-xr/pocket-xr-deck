#!/bin/bash
# Builds dist/pocket-xr-deck.tar.gz: what a release carries and the install line in the README downloads.
set -euo pipefail
cd "$(dirname "$0")"
python3 tests/test_offline.py >/dev/null
python3 tests/test_space.py >/dev/null
rm -rf dist && mkdir -p dist/pocket-xr-deck
cp -r pocketxr assets install.sh uninstall.sh update.sh VERSION README.md LICENSE dist/pocket-xr-deck/
# PC VR's native libraries (native/build.sh): ALVR's client and Pocket XR's bridge
if [ -f native/out/libpxr_pcvr.so ]; then
  mkdir -p dist/pocket-xr-deck/native
  cp native/out/libalvr_client_core.so native/out/libpxr_pcvr.so dist/pocket-xr-deck/native/
else
  echo "note: no PC VR libraries in native/out (run native/build.sh); the release has no PC VR" >&2
fi
# The host's native pieces (native/host/build.sh): PC screens with this Deck as the computer
if [ -f native/out/pxr-host-video ] && [ -f native/out/libpxr_host.so ]; then
  mkdir -p dist/pocket-xr-deck/native
  cp native/out/pxr-host-video native/out/libpxr_host.so dist/pocket-xr-deck/native/
  chmod +x dist/pocket-xr-deck/native/pxr-host-video
else
  echo "note: no host programs in native/out (run native/host/build.sh); the release has no Deck host" >&2
fi
# GNOME on Wayland's screen and pointer (native/mutter/build.sh): Pocket XR on Ubuntu's default desktop
if [ -f native/out/pxr-mutter ]; then
  mkdir -p dist/pocket-xr-deck/native
  cp native/out/pxr-mutter dist/pocket-xr-deck/native/
  chmod +x dist/pocket-xr-deck/native/pxr-mutter
else
  echo "note: no pxr-mutter in native/out (run native/mutter/build.sh); the release has no GNOME Wayland view" >&2
fi
# Gaming Mode's Quick Access panel for Decky (decky/, built with npm run build there)
if [ -f decky/dist/index.js ]; then
  mkdir -p dist/pocket-xr-deck/decky/dist
  cp decky/plugin.json decky/package.json decky/main.py dist/pocket-xr-deck/decky/
  cp decky/dist/index.js dist/pocket-xr-deck/decky/dist/
  # The same panel as a Decky plugin zip (PocketXR/plugin.json one folder deep), for Decky's Install from URL
  python3 - <<'EOF'
import zipfile
with zipfile.ZipFile("dist/pocket-xr-decky.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for f in ("plugin.json", "package.json", "main.py", "dist/index.js"):
        z.write("decky/" + f, "PocketXR/" + f)
EOF
else
  echo "note: no Decky panel in decky/dist (run npm run build in decky/); the release has no Quick Access panel" >&2
fi
find dist -name '__pycache__' -prune -exec rm -rf {} +
tar -C dist -czf dist/pocket-xr-deck.tar.gz pocket-xr-deck
echo "dist/pocket-xr-deck.tar.gz ($(cat VERSION))"
