#!/bin/bash
# Builds dist/pocket-xr-deck.tar.gz: what a release carries and the install line in the README downloads.
set -euo pipefail
cd "$(dirname "$0")"
python3 tests/test_offline.py >/dev/null
python3 tests/test_space.py >/dev/null
rm -rf dist && mkdir -p dist/pocket-xr-deck
cp -r pocketxr assets install.sh uninstall.sh VERSION README.md LICENSE dist/pocket-xr-deck/
find dist -name '__pycache__' -prune -exec rm -rf {} +
tar -C dist -czf dist/pocket-xr-deck.tar.gz pocket-xr-deck
echo "dist/pocket-xr-deck.tar.gz ($(cat VERSION))"
