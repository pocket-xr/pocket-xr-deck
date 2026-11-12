# PC VR on the Steam Deck: plan

Written 11 November 2026, before any of it is built. For Mike to read and decide on.

## What it is

SteamVR games from your Windows PC, played in your glasses plugged into the Deck. The same as Pocket XR's PC VR on
Android: a **PC VR** tile in the launcher (and the Control Center), one press, and SteamVR Home is in your glasses. The
PC side does not change: the same Pocket XR PC helper starts SteamVR and its bundled ALVR streamer.

## Why it does not come free from Steam

- **Steam Remote Play** streams flat games to a Deck, not VR.
- **Steam Link's VR streaming** is only for Quest headsets.
- **ALVR's own clients** are for headsets (Android and the like). There is no ALVR app for a Linux PC with glasses.

So, as on Android, Pocket XR carries the client itself.

## How it works

Pocket XR on Android embeds ALVR's client library (`alvr_client_core`, MIT, built from ALVR 21.0.0-dev14 with a
22 line Pocket XR patch). The Deck version does the same.

| Piece | Android (today) | Deck (planned) |
| --- | --- | --- |
| ALVR client library | Built for arm64 Android | Built for Linux x86_64 from the same ALVR commit and patch, so it speaks to the same PC helper |
| Video decode | ALVR's built-in Android decoder | Pocket XR's own: ALVR hands over the video through `alvr_set_decoder_input_callback`; FFmpeg's decoder runs it on the Deck's GPU (VA-API, already on SteamOS), and `alvr_report_frame_decoded` tells ALVR it is done |
| Drawing | The Space draws each eye's frame | The same: each eye's frame in the existing 3D side by side view, with the head pose the frame was rendered for |
| Head pose | Pocket XR's own, predicted | The same fusion the Deck version uses now, predicted by ALVR's pipeline delay |
| Controllers | Joy-Cons, hands | Joy-Cons (Linux's own `hid-nintendo` driver, mapped as on Android), and the Deck's own sticks, triggers, trackpads and gyro as a controller pair |
| Audio | ALVR's audio out of the glasses | ALVR's audio to the Deck's default output (the glasses, when they are the audio device) |

**One native piece.** Python cannot move 60 frames a second of video. The decode, and handing each decoded frame to
OpenGL, live in a small C library (about 500 lines, like `pocketxr_alvr.cpp` on Android) that the Python app loads.
Everything else (the tile, the Space, input, settings) stays in Python.

**60 frames a second.** The Aura's 3D mode is 3840 x 1080 at 60 Hz, so the stream is 1920 x 1080 per eye at 60. The
Deck's GPU decodes HEVC at that easily; the copy into OpenGL is about 370 MB a second, which the Deck's shared memory
handles. A later step can make it zero-copy (VA-API to EGL images).

## Building it

The library has to be built on Linux, for Linux.

- **On your PC, in WSL (Ubuntu is already there, stopped):** install Rust and a C compiler there, build
  `alvr_client_core` from ALVR's source at the dev14 commit with Pocket XR's patch, and build the C library against
  FFmpeg 7.1's headers. The Deck's FFmpeg is 7.1 (`libavcodec.so.61`), so the library is built against exactly that.
- **Nothing is installed on the Deck.** Both libraries are copied in with Pocket XR, as the rest of the app is.

**This needs your OK:** about 2 GB in WSL (Rust, build tools, ALVR's source and its build). Nothing on Windows itself.

## Steps

1. **Toolchain** in WSL (your OK first).
2. **Proof:** the Deck connects to the PC helper's ALVR, and the lobby, then SteamVR Home, shows in the glasses. Head
   tracking moves the view. Measured: frames shown a second, delay, and the Deck's CPU and heat.
3. **The tile:** PC VR in the launcher and the Control Center; leaving it brings the Space back with the windows where
   they were.
4. **Controllers:** Joy-Cons, then the Deck's own controls.
5. **Audio and microphone.**

## What to expect

- **Will work:** SteamVR games from the PC, in 3D, with head turning (3DoF). On the Aura, Steady mode's 6DoF is not
  available in a game: the Aura holds a flat canvas, and a game needs the head's position sent to the PC, which the
  Aura does not give us (the same as on Android).
- **Limits:** Wi-Fi quality decides the picture and the delay, as with any streaming. The Deck's battery will go faster
  (Wi-Fi, decoding, the glasses).
- **Not affected:** the Android app and the PC helper.

## Risks

- **The ALVR build.** ALVR is developed on Linux, so this should be easier than Android's, but its build pulls in a lot.
- **Steam Input.** While a game runs, Steam still turns the Deck's controls into desktop mouse and keys. Pocket XR may
  need to ask Steam for a "Pocket XR" controller layout, or read the Joy-Cons only at first.
