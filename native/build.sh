#!/bin/bash
# Builds PC VR's native pieces for the Steam Deck (Linux x86_64), in WSL Ubuntu or any Linux:
#   - libalvr_client_core.so: ALVR's client library, from ALVR 21.0.0-dev14 with Pocket XR's patch
#     (the same source as Pocket XR's Android build, so it speaks to the same PC helper);
#   - libpxr_pcvr.so: Pocket XR's bridge (pxr_pcvr.c), built against FFmpeg 7.1's headers and linked to the
#     Deck's own libavcodec.so.61 / libavutil.so.59 (copied into deck-libs/ from SteamOS 3.7).
# Output in native/out/. ALVR_SRC, FFMPEG_SRC and the target dir can be set; the defaults are Mike's WSL.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ALVR_SRC="${ALVR_SRC:-$HOME/alvr-src}"
FFMPEG_SRC="${FFMPEG_SRC:-$HOME/pxr-deck-native/ffmpeg-7.1}"
TARGET="${ALVR_TARGET:-$HOME/alvr-deck-target}"
OUT="$HERE/out"
mkdir -p "$OUT"

source "$HOME/.cargo/env"
# Two jobs and no debug info: a full-speed build of ALVR took the PC's memory and the session down (12 Nov 2026).
(cd "$ALVR_SRC" && CARGO_PROFILE_RELEASE_DEBUG=false cargo build -j 2 -p alvr_client_core --release --target-dir "$TARGET")
cp "$TARGET/release/libalvr_client_core.so" "$OUT/"

# FFmpeg's one generated public header.
GEN="$HOME/pxr-deck-native/gen/libavutil"
mkdir -p "$GEN"
printf '#ifndef AVUTIL_AVCONFIG_H\n#define AVUTIL_AVCONFIG_H\n#define AV_HAVE_BIGENDIAN 0\n#define AV_HAVE_FAST_UNALIGNED 1\n#endif\n' > "$GEN/avconfig.h"

LIBS="$HOME/pxr-deck-native/deck-libs"
mkdir -p "$LIBS"
cp "$HERE/deck-libs/libavcodec.so.61.19.100" "$LIBS/libavcodec.so.61"
cp "$HERE/deck-libs/libavutil.so.59.39.100" "$LIBS/libavutil.so.59"

gcc -shared -fPIC -O2 -Wall -Wno-deprecated-declarations -o "$OUT/libpxr_pcvr.so" "$HERE/pxr_pcvr.c" \
    -I"$HERE" -I"$HOME/pxr-deck-native/gen" -I"$FFMPEG_SRC" \
    "$LIBS/libavcodec.so.61" "$LIBS/libavutil.so.59" -L"$OUT" -lalvr_client_core -lGL -lpthread \
    -Wl,--allow-shlib-undefined -Wl,-rpath,'$ORIGIN'
ls -la "$OUT"
readelf -d "$OUT/libpxr_pcvr.so" | grep -E "NEEDED|RPATH|RUNPATH"
