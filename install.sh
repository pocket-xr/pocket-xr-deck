#!/bin/bash
# Installs Pocket XR for Steam Deck for this user. Nothing goes in SteamOS's own folders, so a SteamOS update
# leaves it in place, and no password is needed. Run it again to update.
# On other Linux (Ubuntu and the like) it also checks for the few system pieces SteamOS has and others may not, and
# offers to add them and the glasses' USB permission with your password (sudo); saying no installs the rest anyway.
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

STEAMOS=""
command -v steamosctl >/dev/null 2>&1 && STEAMOS=yes
ask() {  # ask "question": yes for an empty answer or one starting with y; no when there is no terminal to ask on
  local a
  [ -t 0 ] || return 1
  read -r -p "$1 [Y/n] " a || return 1
  case "$a" in ""|[Yy]*) return 0 ;; *) return 1 ;; esac
}
# systemctl --user without what a program started from Steam passes on (Steam's own libraries, LD_PRELOAD and
# LD_LIBRARY_PATH), and with the user's bus where none is set. A tester's update of 0.7.5 from Gaming Mode (Pierre
# Zammit, 23 Nov 2026) restarted Decky but left 0.7.3's Gaming Mode service running; that restart's error was hidden.
user_systemctl() {
  env -u LD_PRELOAD -u LD_LIBRARY_PATH XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"     DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$(id -u)/bus}" systemctl --user "$@"
}

# The system pieces Pocket XR loads. SteamOS has them all; Ubuntu leaves Python's Tk out, a minimal install SDL2 too.
if [ -z "$STEAMOS" ]; then
  MISSING=""
  python3 -c 'import tkinter' 2>/dev/null || MISSING="$MISSING python3-tk"
  for pair in "SDL2-2.0:libsdl2-2.0-0" "cairo:libcairo2" "rsvg-2:librsvg2-2" "GL:libgl1"; do
    lib="${pair%%:*}"
    pkg="${pair#*:}"
    python3 -c "import ctypes.util, sys; sys.exit(0 if ctypes.util.find_library('$lib') else 1)" 2>/dev/null \
      || MISSING="$MISSING $pkg"
  done
  if [ -n "$MISSING" ]; then
    if command -v apt-get >/dev/null 2>&1; then
      echo "Pocket XR needs these from your system:$MISSING"
      if ask "Install them now (sudo apt-get install)?"; then
        sudo apt-get install -y $MISSING || echo "Not installed. Later: sudo apt-get install$MISSING" >&2
      else
        echo "Skipped. Later: sudo apt-get install$MISSING"
      fi
    else
      echo "Pocket XR needs these from your system (Debian and Ubuntu names; yours may differ):$MISSING" >&2
    fi
  fi
fi

echo "Installing Pocket XR to $DEST"
mkdir -p "$DEST" "$APPS" "$ICONS" "$BIN"
rm -rf "$DEST/pocketxr" "$DEST/assets" "$DEST/native"
cp -r "$SRC/pocketxr" "$SRC/assets" "$DEST/"
[ -d "$SRC/native" ] && cp -r "$SRC/native" "$DEST/"
cp "$SRC/uninstall.sh" "$SRC/VERSION" "$DEST/"
[ -f "$SRC/update.sh" ] && cp "$SRC/update.sh" "$DEST/" && chmod +x "$DEST/update.sh"
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
Comment=$([ -n "$STEAMOS" ] && echo "Your Deck's screen" || echo "Your screen") and apps on XREAL and VITURE glasses
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
# "Update Pocket XR": the latest release's installer in a terminal (update.sh), beside Pocket XR. Suggested by a tester,
# Pierre Zammit (November 2026).
update_entry() {
  cat <<EOF
[Desktop Entry]
Type=Application
Name=Update Pocket XR
Comment=Download and install the latest Pocket XR
Exec=$DEST/update.sh
Icon=pocket-xr
Terminal=true
Categories=Utility;
StartupNotify=false
EOF
}
if [ -x "$DEST/update.sh" ]; then
  update_entry > "$APPS/pocket-xr-update.desktop"
  if [ -d "$HOME/Desktop" ]; then
    update_entry > "$HOME/Desktop/pocket-xr-update.desktop"
    chmod +x "$HOME/Desktop/pocket-xr-update.desktop"
  fi
fi
update-desktop-database "$APPS" >/dev/null 2>&1 || true

# The glasses' motion sensors (XREAL Air family, VITURE) and Joy-Cons are USB HID devices. SteamOS lets the signed-in
# user read them; Ubuntu and most others need a udev rule for that (uaccess: whoever sits at the computer, no group).
UDEV_RULE=/etc/udev/rules.d/70-pocket-xr.rules
if [ -z "$STEAMOS" ] && [ ! -f "$UDEV_RULE" ] && [ -d /etc/udev/rules.d ]; then
  echo "Head tracking on XREAL Air and VITURE glasses needs permission to read them over USB (a udev rule)."
  if ask "Add it now (sudo)?"; then
    if printf '%s\n' \
         '# Pocket XR: the signed-in user may read XREAL and VITURE glasses and Nintendo Joy-Cons (hidraw)' \
         'KERNEL=="hidraw*", ATTRS{idVendor}=="3318", TAG+="uaccess"' \
         'KERNEL=="hidraw*", ATTRS{idVendor}=="35ca", TAG+="uaccess"' \
         'KERNEL=="hidraw*", ATTRS{idVendor}=="057e", TAG+="uaccess"' | sudo tee "$UDEV_RULE" >/dev/null \
       && sudo udevadm control --reload-rules && sudo udevadm trigger --subsystem-match=hidraw; then
      echo "Added $UDEV_RULE. If your glasses are plugged in, unplug them and plug them back in."
    else
      echo "Not added. The glasses still show the picture; their head tracking may not work." >&2
    fi
  else
    echo "Skipped. Without it XREAL Air and VITURE glasses may have no head tracking (the XREAL Aura doesn't need it)."
  fi
fi

# 0.7.7 offered a udev rule (71-pocket-xr-usb.rules) so "Use the glasses' buttons" could reset the glasses over USB.
# On a tester's XBX the reset did not give the buttons back (the glasses kept running), so the reset is gone and the
# rule is no longer offered. It is harmless (XREAL and VITURE glasses only); uninstall.sh offers to remove it.
USB_RULE="${POCKET_XR_USB_RULE:-/etc/udev/rules.d/71-pocket-xr-usb.rules}"  # the variable: for tests
USB_RULE_STATE=""
[ -f "$USB_RULE" ] && USB_RULE_STATE=unused

# Keyboard shortcuts for what the Deck's back buttons do, on GNOME (a computer has no back buttons). Added once,
# beside any custom shortcuts already there; uninstall.sh takes them out again.
SHORTCUTS=""
KEYS=org.gnome.settings-daemon.plugins.media-keys
if [ -z "$STEAMOS" ] && command -v gsettings >/dev/null 2>&1 && gsettings list-schemas 2>/dev/null | grep -qx "$KEYS"; then
  BASE=/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings
  list=$(gsettings get "$KEYS" custom-keybindings)
  case "$list" in
    *pocket-xr-*) SHORTCUTS=kept ;;
    *)
      n=0
      for spec in "Recentre|L4 tap|<Super><Alt>r" "Window in space or Steady 6DoF|L4 hold|<Super><Alt>v" \
                  "Launcher|L5 tap|<Super><Alt>l" "Control Center|R5 tap|<Super><Alt>c"; do
        IFS='|' read -r label button binding <<<"$spec"
        path="$BASE/pocket-xr-$n/"
        gsettings set "$KEYS.custom-keybinding:$path" name "Pocket XR: $label"
        gsettings set "$KEYS.custom-keybinding:$path" command "$BIN/pocket-xr --button $button"
        gsettings set "$KEYS.custom-keybinding:$path" binding "$binding"
        case "$list" in "@as []" | "[]") list="['$path']" ;; *) list="${list%]}, '$path']" ;; esac
        n=$((n + 1))
      done
      gsettings set "$KEYS" custom-keybindings "$list" && SHORTCUTS=yes
      ;;
  esac
fi

# Pocket XR's desktop app, if it is open: closed (it puts the glasses back on SIGTERM) and, with a desktop to show it
# on, opened again, so it runs the new files.
APP=""
GAMING=""
APP_PIDS=$(pgrep -u "$(id -u)" -f -- '-m pocketxr( |$)' || true)
if [ -n "$APP_PIDS" ]; then
  kill -TERM $APP_PIDS 2>/dev/null || true
  for _ in $(seq 20); do
    pgrep -u "$(id -u)" -f -- '-m pocketxr( |$)' >/dev/null || break
    sleep 0.5
  done
  if [ -n "${DISPLAY}${WAYLAND_DISPLAY}" ]; then
    setsid "$BIN/pocket-xr" >/dev/null 2>&1 < /dev/null &
    APP=reopened
  else
    APP=closed
  fi
fi

# Gaming Mode: a small service that starts with the session and acts only while Gaming Mode runs (pocketxr/gaming.py).
# For SteamOS's Gaming Mode (gamescope); elsewhere it would only wait for a gamescope that never comes.
UNITS="$HOME/.config/systemd/user"
mkdir -p "$UNITS"
if [ -n "$STEAMOS" ] || command -v gamescope >/dev/null 2>&1; then
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
user_systemctl daemon-reload >/dev/null 2>&1 || true
user_systemctl enable pocket-xr-gaming.service >/dev/null 2>&1 || true
if out=$(user_systemctl restart pocket-xr-gaming.service 2>&1); then
  GAMING=restarted
else
  GAMING="${out:-no reason given}"
fi
fi

# PC screens with this Deck as the computer (pocketxr/host): the phone's Pocket XR shows the Deck's screens, each a
# KWin virtual output at the phone's window shape. A service in Desktop Mode (Plasma) only. KWin lets the picture's
# program make virtual outputs only when a desktop file names it: written here, hidden from the menus.
HOST=""
if [ -x "$DEST/native/pxr-host-video" ] && [ -f "$DEST/native/libpxr_host.so" ] && command -v kwin_wayland >/dev/null 2>&1; then
  cat > "$APPS/pocket-xr-host.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Pocket XR host
Comment=Pocket XR's PC screens: this Deck's screens on your phone
Exec=$DEST/native/pxr-host-video
NoDisplay=true
X-KDE-Wayland-Interfaces=zkde_screencast_unstable_v1
EOF
  kbuildsycoca6 >/dev/null 2>&1 || true
  # It takes the place of the Pocket XR PC Screens app (Sunshine in a Flatpak) and its helper: the same ports. Its
  # certificate and paired phones are taken over at the host's first start, so a paired phone stays paired.
  for unit in pocketxr-sunshine@1 pocketxr-sunshine@2 pocketxr-sunshine@3 pocketxr-pc-helper; do
    if systemctl --user is-enabled "$unit.service" >/dev/null 2>&1 || systemctl --user is-active "$unit.service" >/dev/null 2>&1; then
      systemctl --user disable --now "$unit.service" >/dev/null 2>&1 || true
      HOST=replaced
    fi
  done
  cat > "$UNITS/pocket-xr-host.service" <<EOF
[Unit]
Description=Pocket XR host: this Deck's screens on the phone's PC screens (Desktop Mode)
After=plasma-workspace.target
PartOf=graphical-session.target

[Service]
WorkingDirectory=$DEST
ExecStart=/usr/bin/python3 -m pocketxr.host
Restart=on-failure
RestartSec=5

[Install]
WantedBy=plasma-workspace.target
EOF
  user_systemctl daemon-reload >/dev/null 2>&1 || true
  user_systemctl enable pocket-xr-host.service >/dev/null 2>&1 || true
  if user_systemctl is-active plasma-workspace.target >/dev/null 2>&1; then
    user_systemctl restart pocket-xr-host.service >/dev/null 2>&1 || true
  fi
  [ -n "$HOST" ] || HOST=yes
fi

# Gaming Mode's Quick Access panel, for Decky Loader (https://decky.xyz), when Decky is installed. Where Decky's
# plugins folder belongs to this user (read-only), it is opened, filled and closed again without a password. Where it
# belongs to root and an older Pocket XR panel is there, it is replaced with your password (sudo), asked here in the
# terminal, and Decky is restarted so it loads the new one: a tester (Pierre Zammit, November 2026) found the update
# left his panel as it was. Saying no, or a Deck with no password set, leaves it and says how to add it in Decky.
PLUGINS="$HOME/homebrew/plugins"
PANEL_URL="https://github.com/pocket-xr/pocket-xr-deck/releases/latest/download/pocket-xr-decky.zip"
PANEL=""
want=$(grep -o '"version": *"[^"]*"' "$SRC/decky/package.json" 2>/dev/null || true)
have=$(grep -o '"version": *"[^"]*"' "$PLUGINS/PocketXR/package.json" 2>/dev/null || true)
panel_files() {  # panel_files <command prefix>: the panel's files into the plugins folder
  $1 mkdir -p "$PLUGINS/PocketXR/dist"
  $1 cp "$SRC/decky/plugin.json" "$SRC/decky/package.json" "$SRC/decky/main.py" "$PLUGINS/PocketXR/"
  $1 cp "$SRC/decky/dist/index.js" "$PLUGINS/PocketXR/dist/"
}
if [ -d "$PLUGINS" ] && [ -O "$PLUGINS" ] && [ -f "$SRC/decky/dist/index.js" ]; then
  chmod u+w "$PLUGINS"
  [ -d "$PLUGINS/PocketXR" ] && chmod -R u+w "$PLUGINS/PocketXR" && rm -rf "$PLUGINS/PocketXR"
  panel_files ""
  chmod -R a-w "$PLUGINS/PocketXR"
  chmod u-w "$PLUGINS"
  PANEL=yes
elif [ -d "$PLUGINS/PocketXR" ] && [ -f "$SRC/decky/dist/index.js" ] && [ "$want" != "$have" ]; then
  echo "Pocket XR's Quick Access panel in Decky is older than this Pocket XR. Decky's plugins folder belongs to root,"
  echo "so updating it needs your password (the one you set with passwd)."
  if ask "Update the panel now (sudo)?"; then
    if sudo rm -rf "$PLUGINS/PocketXR" && panel_files sudo; then
      PANEL=replaced
      if sudo systemctl restart plugin_loader >/dev/null 2>&1; then
        PANEL=reloaded
      fi
    else
      echo "Not updated." >&2
    fi
  fi
fi

echo "Done. Pocket XR $(cat "$SRC/VERSION") is on the desktop and in the app menu."
if [ -n "$STEAMOS" ]; then
  echo "Plug in your glasses and open it from Desktop Mode. In Gaming Mode it starts by itself."
else
  echo "Plug in your glasses and open it from the app menu."
  case "${XDG_CURRENT_DESKTOP:-}:${XDG_SESSION_TYPE:-}" in
    *GNOME*:wayland) echo "On GNOME it shows your main screen in the glasses (each app window in its own place needs X11 for now)." ;;
    *:wayland) echo "Its view needs GNOME, or an X11 session such as Plasma (X11), on this computer." ;;
  esac
fi
if [ "$SHORTCUTS" = yes ]; then
  echo "Shortcuts: Super+Alt+R recentres, Super+Alt+V switches the view, Super+Alt+L opens the launcher and Super+Alt+C"
  echo "the Control Center (Settings, Keyboard, Custom Shortcuts to change them)."
fi
if [ "$HOST" = replaced ]; then
  echo "Your phone's PC screens now reach this Deck through Pocket XR itself: the PC Screens app's Sunshine and helper"
  echo "are switched off (flatpak uninstall com.hayeco.pocketxr.PCScreens removes it)."
elif [ -n "$HOST" ]; then
  echo "Your phone's Pocket XR can show this Deck's screens (PC screens) while it is in Desktop Mode."
fi
if [ "$USB_RULE_STATE" = unused ]; then
  echo "Pocket XR no longer uses the USB permission 0.7.7 added ($USB_RULE). It does no harm; to remove it:"
  echo "  sudo rm $USB_RULE"
fi
if [ "$APP" = reopened ]; then
  echo "Pocket XR was open: it was closed and opened again with the new version."
elif [ "$APP" = closed ]; then
  echo "Pocket XR was open: it was closed. Open it again from the app menu."
fi
if [ -n "$GAMING" ] && [ "$GAMING" != restarted ]; then
  echo "Pocket XR's Gaming Mode service could not be restarted ($GAMING). Restart the Deck to load the new version."
fi
[ -n "$STEAMOS" ] || exit 0  # the rest is about Gaming Mode's Quick Access panel: SteamOS only
have=$(grep -o '"version": *"[^"]*"' "$PLUGINS/PocketXR/package.json" 2>/dev/null || true)
if [ "$PANEL" = reloaded ]; then
  echo "Its Gaming Mode panel in Decky is updated, and Decky restarted to load it."
elif [ -n "$PANEL" ]; then
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
