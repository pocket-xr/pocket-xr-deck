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

# Gaming Mode: a small service that starts with the session and acts only while Gaming Mode runs (pocketxr/gaming.py)
UNITS="$HOME/.config/systemd/user"
mkdir -p "$UNITS"
cat > "$UNITS/pocket-xr-gaming.service" <<EOF
[Unit]
Description=Pocket XR in Gaming Mode: your games on a screen held still in your XR glasses

[Service]
WorkingDirectory=$DEST
ExecStart=/usr/bin/python3 -m pocketxr.gaming
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload >/dev/null 2>&1 || true
systemctl --user enable pocket-xr-gaming.service >/dev/null 2>&1 || true
systemctl --user restart pocket-xr-gaming.service >/dev/null 2>&1 || true

# Gaming Mode's Quick Access panel, for Decky Loader (https://decky.xyz), when Decky is installed. Where Decky's
# plugins folder belongs to this user (read-only), it is opened, filled and closed again without a password. Where it
# belongs to root, only Decky can add the panel: from the release's pocket-xr-decky.zip, by its Install from URL.
PLUGINS="$HOME/homebrew/plugins"
PANEL_URL="https://github.com/pocket-xr/pocket-xr-deck/releases/latest/download/pocket-xr-decky.zip"
PANEL=""
if [ -d "$PLUGINS" ] && [ -O "$PLUGINS" ] && [ -f "$SRC/decky/dist/index.js" ]; then
  chmod u+w "$PLUGINS"
  [ -d "$PLUGINS/PocketXR" ] && chmod -R u+w "$PLUGINS/PocketXR" && rm -rf "$PLUGINS/PocketXR"
  mkdir -p "$PLUGINS/PocketXR/dist"
  cp "$SRC/decky/plugin.json" "$SRC/decky/package.json" "$SRC/decky/main.py" "$PLUGINS/PocketXR/"
  cp "$SRC/decky/dist/index.js" "$PLUGINS/PocketXR/dist/"
  chmod -R a-w "$PLUGINS/PocketXR"
  chmod u-w "$PLUGINS"
  PANEL=yes
fi

echo "Done. Pocket XR $(cat "$SRC/VERSION") is on the desktop and in the app menu."
echo "Plug in your glasses and open it from Desktop Mode. In Gaming Mode it starts by itself."
want=$(grep -o '"version": *"[^"]*"' "$SRC/decky/package.json" 2>/dev/null || true)
have=$(grep -o '"version": *"[^"]*"' "$PLUGINS/PocketXR/package.json" 2>/dev/null || true)
if [ -n "$PANEL" ]; then
  echo "Its Gaming Mode panel is in Decky: restart the Deck once to see Pocket XR in Quick Access."
elif [ -n "$want" ] && [ "$want" = "$have" ]; then
  echo "Its Gaming Mode panel is in Quick Access, under Decky."
elif [ -d "$PLUGINS" ]; then
  echo "To add its Gaming Mode panel to Quick Access: in Gaming Mode, open Decky's settings and turn on Developer"
  echo "mode. Then under Developer, choose Install Plugin from URL and enter:"
  echo "  $PANEL_URL"
else
  echo "For its Gaming Mode panel in Quick Access, install Decky Loader (decky.xyz) and run this again."
fi
