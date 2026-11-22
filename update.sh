#!/bin/bash
# Update Pocket XR: downloads the latest release and runs its installer, as the install line in the README does.
# The "Update Pocket XR" launcher on the desktop and in the app menu runs this in a terminal (suggested by a tester,
# Pierre Zammit, November 2026), so a password the installer asks for (Decky's panel) can be typed there.
URL="https://github.com/pocket-xr/pocket-xr-deck/releases/latest/download/pocket-xr-deck.tar.gz"
TMP="$(mktemp -d)"
echo "Downloading the latest Pocket XR..."
if curl -fL "$URL" | tar xz -C "$TMP"; then
  "$TMP/pocket-xr-deck/install.sh"
  status=$?
else
  echo "The download did not work. Check the network and try again." >&2
  status=1
fi
rm -rf "$TMP"
echo
read -r -p "Press Enter to close. " _ || true
exit "$status"
