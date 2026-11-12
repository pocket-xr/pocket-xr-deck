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

## Proof, 12 November 2026

On Mike's Deck with his Aura in 3D, and his PC running the Pocket XR PC helper:

- The Deck found the helper, Mike allowed it on the PC, and the helper started SteamVR and trusted the Deck in ALVR.
- ALVR streamed HEVC at 1920 x 1056 per eye, 60 a second. The Deck decoded it on its GPU (VA-API) with no errors:
  1,797 frames decoded and 1,740 drawn in 30 s, the view at 60 fps.
- SteamVR's dashboard and Home showed in both eyes with the right colours, turned to the head as it moved.
- Pocket XR's process used about one of the Deck's four cores, mostly copying each decoded frame to OpenGL. A
  zero-copy path (VA-API to EGL images) is the way to bring that down.
- Building ALVR at full speed (16 jobs) ran the PC out of memory and took the session down; native/build.sh uses two
  jobs and no debug info (under 4 minutes).

Next: controllers (Joy-Cons, then the Deck's own), the microphone, and a Glasses report line for PC VR.

## Loading room and portal, 12 November 2026

PC VR now opens and closes as on Android (`pocketxr/pcvr_scene.py`, from `PcVrLoading.kt` and `PcVrRenderer.kt`):

- **Opening:** a circle with a blue rim grows from the middle of each eye over the Space (0.75 s) into the loading
  room: a dark room with a breathing blue horizon, a faint floor grid and one card saying what is happening.
- **The card:** "Connecting to your PC", "Still looking for your PC" after 20 s, "Starting SteamVR",
  "Reconnecting to your PC", with a turning arc. It stays where you were looking and drifts back once you turn more
  than 35 degrees away. On the Deck it also says "Hold L5 or R5 to leave PC VR".
- **Into the game:** once frames have come steadily for 1.5 s (and the room has shown at least 1.2 s), the room fades
  over 0.8 s. If the picture stops for 1 s, "Waiting for your PC" eases in over the game.
- **Leaving:** hold L5 or R5 for 2 s. After 0.3 s "Going back to your Space" shows with a ring filling; let go to stay.
  When it fills (or Leave PC VR is pressed on the panel), the circle closes over 0.55 s onto the Space.

Tested on Mike's Deck and Aura: the portal, the room and card, the fade into SteamVR Home (steady after 91 frames),
holding L5 to leave, and opening it again.
