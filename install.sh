#!/bin/bash
# Installs Pocket XR for Steam Deck for this user. Nothing goes in SteamOS's own folders, so a SteamOS update
# leaves it in place, and no password is needed. Run it again to update.
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/.local/share/pocket-xr-deck"
APPS="$HOME/.local/share/applications"
ICONS="$HOME/.local/share/icons/hicolor/512x512/apps"
BIN="$HOME/.local/bin"

if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
  echo "Pocket XR needs Python 3.9 or newer, which SteamOS has. Is this a Steam Deck in Desktop Mode?" >&2
  exit 1
fi

echo "Installing Pocket XR to $DEST"
mkdir -p "$DEST" "$APPS" "$ICONS" "$BIN"
rm -rf "$DEST/pocketxr" "$DEST/assets" "$DEST/native"
cp -r "$SRC/pocketxr" "$SRC/assets" "$DEST/"
[ -d "$SRC/native" ] && cp -r "$SRC/native" "$DEST/"
cp "$SRC/uninstall.sh" "$SRC/VERSION" "$DEST/"
find "$DEST" -name '__pycache__' -prune -exec rm -rf {} +

cat > "$BIN/pocket-xr" <<EOF
#!/bin/bash
cd "$DEST" && exec python3 -m pocketxr "\$@"
EOF
chmod +x "$BIN/pocket-xr"

cp "$SRC/assets/pocket-xr.png" "$ICONS/pocket-xr.png"

# Inter, Pocket XR's font (SIL Open Font License), for this user only
FONTS="$HOME/.local/share/fonts/pocket-xr"
mkdir -p "$FONTS"
cp "$SRC/assets/fonts/"*.ttf "$FONTS/"
fc-cache -f "$FONTS" >/dev/null 2>&1 || true

entry() {
  cat <<EOF
[Desktop Entry]
Type=Application
Name=Pocket XR
GenericName=Windows in your glasses
Comment=Your Deck's screen and apps on XREAL and VITURE glasses
Exec=$BIN/pocket-xr
Icon=pocket-xr
Terminal=false
Categories=Utility;
Keywords=XREAL;VITURE;AR;glasses;XR;
StartupNotify=false
EOF
}
entry > "$APPS/pocket-xr.desktop"
if [ -d "$HOME/Desktop" ]; then
  entry > "$HOME/Desktop/pocket-xr.desktop"
  chmod +x "$HOME/Desktop/pocket-xr.desktop"
fi
update-desktop-database "$APPS" >/dev/null 2>&1 || true

echo "Done. Pocket XR $(cat "$SRC/VERSION") is on the desktop and in the app menu."
echo "Plug in your glasses and open it from Desktop Mode."
