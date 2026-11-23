#!/bin/bash
# Removes Pocket XR for Steam Deck. Your settings stay in ~/.config/pocket-xr-deck unless you add --all.
set -euo pipefail

systemctl --user disable --now pocket-xr-gaming.service >/dev/null 2>&1 || true
systemctl --user disable --now pocket-xr-host.service >/dev/null 2>&1 || true
rm -f "$HOME/.config/systemd/user/pocket-xr-gaming.service" "$HOME/.config/systemd/user/pocket-xr-host.service" \
      "$HOME/.local/share/gamescope/reshade/Shaders/PocketXR.fx"
systemctl --user daemon-reload >/dev/null 2>&1 || true
# GNOME's keyboard shortcuts the installer added (pocket-xr-N), leaving any others as they are.
KEYS=org.gnome.settings-daemon.plugins.media-keys
if command -v gsettings >/dev/null 2>&1 && gsettings list-schemas 2>/dev/null | grep -qx "$KEYS"; then
  list=$(gsettings get "$KEYS" custom-keybindings)
  case "$list" in *pocket-xr-*)
    for path in $(echo "$list" | grep -o "'[^']*pocket-xr-[0-9]*/'" | tr -d "'"); do
      for key in name command binding; do gsettings reset "$KEYS.custom-keybinding:$path" "$key" || true; done
    done
    rest=$(echo "$list" | sed -E "s#'[^']*pocket-xr-[0-9]+/'(, )?##g; s#, \]#]#")
    case "$rest" in "[]" | "@as []") rest="@as []" ;; esac
    gsettings set "$KEYS" custom-keybindings "$rest" || true
    ;;
  esac
fi
# The udev rules the installer added with your password: the glasses' USB permissions (reading them, resetting them)
RULES=""
for r in /etc/udev/rules.d/70-pocket-xr.rules /etc/udev/rules.d/71-pocket-xr-usb.rules; do
  [ -f "$r" ] && RULES="$RULES $r"
done
if [ -n "$RULES" ]; then
  echo "Pocket XR added the glasses' USB permissions:$RULES"
  answer=""
  if [ -t 0 ]; then
    read -r -p "Remove them too (sudo, your password)? [Y/n] " answer || answer=n
  else
    answer=n
  fi
  case "$answer" in
    ""|[Yy]*)
      if sudo rm -f $RULES && sudo udevadm control --reload-rules; then
        echo "Removed."
      else
        echo "Not removed. Later: sudo rm$RULES" >&2
      fi
      ;;
    *) echo "They stay. Later: sudo rm$RULES" ;;
  esac
fi
if [ -d "$HOME/homebrew/plugins/PocketXR" ] && [ -O "$HOME/homebrew/plugins" ]; then
  chmod u+w "$HOME/homebrew/plugins" && chmod -R u+w "$HOME/homebrew/plugins/PocketXR"
  rm -rf "$HOME/homebrew/plugins/PocketXR"
  chmod u-w "$HOME/homebrew/plugins"
elif [ -d "$HOME/homebrew/plugins/PocketXR" ]; then
  echo "Pocket XR's panel stays in Decky. Remove it in Decky's settings, under Plugins."
fi
rm -rf "$HOME/.local/share/pocket-xr-deck"
rm -f "$HOME/.local/bin/pocket-xr" \
      "$HOME/.local/share/applications/pocket-xr.desktop" \
      "$HOME/.local/share/applications/pocket-xr-host.desktop" \
      "$HOME/Desktop/pocket-xr.desktop" \
      "$HOME/.local/share/applications/pocket-xr-update.desktop" \
      "$HOME/Desktop/pocket-xr-update.desktop" \
      "$HOME/.local/share/icons/hicolor/512x512/apps/pocket-xr.png"
rm -rf "$HOME/.local/share/fonts/pocket-xr"
update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true
if [ "${1:-}" = "--all" ]; then
  rm -rf "$HOME/.config/pocket-xr-deck" "$HOME/.local/state/pocket-xr-deck"
  echo "Pocket XR and its settings are removed."
else
  echo "Pocket XR is removed. Your settings are kept in ~/.config/pocket-xr-deck (uninstall.sh --all removes them too)."
fi
