#!/bin/bash
# Starts the prototype as a user service, so it keeps running when an SSH session ends
# (SDL takes the hang-up from a closing SSH session as "quit"). Stop it with Ctrl+Q or
# `systemctl --user stop pocketxr-deck`. The log is deckxr.log beside this folder.
here="$(cd "$(dirname "$0")/.." && pwd)"
systemctl --user stop pocketxr-deck 2>/dev/null
exec systemd-run --user --unit=pocketxr-deck --collect -p WorkingDirectory="$here" \
  /bin/bash -c "exec ./prototype/run.sh $* > deckxr.log 2>&1"
