#!/bin/bash
# Runs the prototype on the Desktop Mode screen, from SSH or Konsole.
export DISPLAY=:0
export XAUTHORITY=$(tr "\0" "\n" < /proc/$(pgrep -x kwin_x11)/environ | sed -n "s/^XAUTHORITY=//p")
cd "$(dirname "$0")/.."
exec python3 prototype/deckxr.py "$@"
