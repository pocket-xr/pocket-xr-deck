#!/bin/bash
# Removes Pocket XR for Steam Deck. Your settings stay in ~/.config/pocket-xr-deck unless you add --all.
set -euo pipefail

systemctl --user disable --now pocket-xr-gaming.service >/dev/null 2>&1 || true
rm -f "$HOME/.config/systemd/user/pocket-xr-gaming.service" "$HOME/.local/share/gamescope/reshade/Shaders/PocketXR.fx"
systemctl --user daemon-reload >/dev/null 2>&1 || true
rm -rf "$HOME/.local/share/pocket-xr-deck"
rm -f "$HOME/.local/bin/pocket-xr" \
      "$HOME/.local/share/applications/pocket-xr.desktop" \
      "$HOME/Desktop/pocket-xr.desktop" \
      "$HOME/.local/share/icons/hicolor/512x512/apps/pocket-xr.png"
rm -rf "$HOME/.local/share/fonts/pocket-xr"
update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true
if [ "${1:-}" = "--all" ]; then
  rm -rf "$HOME/.config/pocket-xr-deck" "$HOME/.local/state/pocket-xr-deck"
  echo "Pocket XR and its settings are removed."
else
  echo "Pocket XR is removed. Your settings are kept in ~/.config/pocket-xr-deck (uninstall.sh --all removes them too)."
fi
