# The Deck as the computer for the phone's PC screens

Pocket XR on the phone shows a computer's desktops as PC screens, each in its own window. Here the Steam Deck is that
computer, with nothing else installed. It replaces the Pocket XR PC Screens app (Sunshine in a Flatpak,
`com.hayeco.pocketxr.PCScreens`).

The code is `pocketxr/host/` (Python) and `native/host/` (C). It is a service, `pocket-xr-host`, which runs in
Desktop Mode only.

## How it is built

The host answers Moonlight's protocol the way Sunshine and Apollo do. The logic is ported from them (GPLv3), as
Pocket XR for Windows' own host (`src/PocketXR/PcHost`) is.

| Part | Where | How |
| --- | --- | --- |
| Pairing, serverinfo, app list, launch, cancel | `server.py` | HTTP on P, HTTPS on P-5. TLS through OpenSSL with ctypes (`ossl.py`): any client certificate is let through, then checked against the paired phones |
| RTSP | `server.py` | TCP on P+21: OPTIONS, DESCRIBE, SETUP, ANNOUNCE, PLAY |
| Control stream | `control.py` | moonlight-common-c's ENet fork (`native/host/pxr_host.c`) on P+10, AES-GCM (CONTROL_V2) |
| Picture | `native/host/pxr_host_video.c` | A KWin virtual output per stream (`zkde_screencast_unstable_v1`, `stream_virtual_output`, pointer drawn in), captured through PipeWire. Encoded by FFmpeg as `hwupload` + `scale_vaapi` (NV12, BT.709) + `h264_vaapi` or `hevc_vaapi` (each checked first: see below): peak-limited VBR (mean 3/4 of the phone's bitrate), no B-frames, a key frame only when asked. Sent as Moonlight's video packets with Reed-Solomon FEC (nanors, 20 %) to P+9 |
| Sound | `audio.py` | A null sink per stream, made the default while it streams, recorded with `parec`. Opus at 192 kbps in 5 ms packets, AES-CBC, RS(4,2) parity, to P+11 |
| Mouse, keys, text | `inputs.py` | uinput: a keyboard, a mouse (relative moves, wheel) and an absolute pointer over the whole desktop |
| Clipboard | `desktop.py` | Klipper over D-Bus (`qdbus6`), for `/actions/clipboard` |
| Finding the Deck | `helper.py` | The PC helper's UDP/TCP protocol on 47610, with the screens' ports in the UDP answer. `avahi-publish` is tried too |

The ports are the PC Screens app's: P = 47989, 48989 and 49989 for PC screens 1, 2 and 3. Three are served at
first. **PC screens for a phone** on the control panel (`host_screens` in `~/.config/pocket-xr-deck/settings.json`,
1 to 6) changes that, and the host follows within 10 seconds with no restart: screens 4, 5 and 6 are P = 50989, 51989
and 52989, P = 47989 + 1000 per screen, so each screen's P-5 to P+21 never meets another's. A screen left out by a
lower number stops once no phone streams from it. The count and the ports are set in one place, `screens.py`.
`python3 -m pocketxr.host --ports ...` serves the ports given and ignores the setting. Nothing has been streamed from
more than three screens yet.

KWin lets only programs named in a desktop file use the screencast protocol. So the installer writes
`~/.local/share/applications/pocket-xr-host.desktop` with `X-KDE-Wayland-Interfaces=zkde_screencast_unstable_v1` for
`native/pxr-host-video`, then runs `kbuildsycoca6`.

On its first start the host takes over the PC Screens app's settings from `~/.config/pocketxr`: its certificate, each
screen's unique id and its paired phones. So a phone paired with it should not need pairing again (not yet tried with
a phone). The helper keeps phones allowed in the same file the old helper used, `~/.config/pocketxr/pc-helper.json`.

The installer switches off the PC Screens app's services (`pocketxr-sunshine@1..3` and `pocketxr-pc-helper`). The
Flatpak itself stays installed.

## The PC helper, built in

Pocket XR for Linux and the Steam Deck now does the PC helper's jobs itself (`helper.py`), so there is no separate
helper (pc-helper/unix's `pocketxr_pc_helper.py`) and no Sunshine Flatpak. The wire format is the same as the
Windows, macOS and Linux helpers':

- UDP 47610: `POCKETXR-FIND 1` gets `POCKETXR-HERE 1 47610 <name> <ports>`. The fifth field lists the PC screens'
  ports, comma-separated, because SteamOS refuses mDNS.
- TCP 47610 takes one JSON line and answers one:
  - `pair`: a Yes on the Deck (kdialog).
  - `apollo-pin`: the PIN goes straight to the host.
  - `screen-prepare`: `{"ok":true}`.
  - `screens-setup`: `{"ok":true,"ports":[...]}`, because the screens are always there.
  - `status` and `start`: `"os":"linux-virtual"`, `"virtual":true`.
- Phones allowed once stay allowed through the same token file, `~/.config/pocketxr/pc-helper.json`.

When another streaming host still holds a screen's ports (an earlier Sunshine), that screen is left out. The others
still serve, and the UDP answer lists only them.

## Moving over from the old helper and the PC Screens app

Running Pocket XR's `install.sh` does the move. Nothing has to be typed again:

1. **The PC Screens app (Sunshine in a Flatpak, with its helper).** The installer switches off
   `pocketxr-sunshine@1`, `@2` and `@3` and `pocketxr-pc-helper`. At its first start, the host takes over that app's
   certificate, each screen's unique id and its paired phones, from `~/.config/pocketxr`. A phone paired with it
   should connect with no new pairing and no new Yes (not yet tried with a phone). The Flatpak stays installed until
   you remove it: `flatpak uninstall com.hayeco.pocketxr.PCScreens`. Its setup's udev rule
   (`/etc/udev/rules.d/60-sunshine.rules`) and its desktop file copy can stay; they do nothing without it.
2. **The Linux PC helper alone, with your own Sunshine.** The installer switches off `pocketxr-pc-helper`; its allowed
   phones carry over. Your own Sunshine keeps its ports, so those PC screens are left out of Pocket XR's host. Stop
   that Sunshine to let Pocket XR serve them.
3. **Going back.** `systemctl --user disable --now pocket-xr-host`, then `systemctl --user enable --now
   pocketxr-pc-helper pocketxr-sunshine@1 pocketxr-sunshine@2 pocketxr-sunshine@3`.

macOS keeps the separate helper; this is Linux only.

## Show a PC: the other direction

The launcher card's and control panel's **Show a PC** shows another computer's screens in the glasses plugged into
this Deck (`pocketxr/pcscreens.py`, `docs/PC-SCREENS-DECK.md`). It never offers this Deck itself: its own helper's
answer, a saved address and mDNS entries that are this machine's are passed over. With no glasses plugged in, it says
so and does nothing. The control panel has a line under its buttons: glasses on a phone open PC screens from the phone.

## Building

Run `native/host/build.sh` in WSL Ubuntu or another Linux with gcc, wayland-scanner and the PipeWire and Wayland
development files. It uses FFmpeg 8.1's headers and the Deck's own `libavcodec.so.62`, `libavutil.so.60` and
`libavfilter.so.11`, copied into `native/deck-libs/`. `make-release.sh` puts both programs in the release's
`native/`.

## Seen on the Deck (SteamOS, KWin 6.7.3, FFmpeg 8.1.2, 20 Nov 2026)

These were checked with `tools/host_check.py`, a test client that talks to the host as the phone's Moonlight core
does. It ran on the Deck against the host on test ports, not with a phone.

- Encoders that open: H.264 and HEVC. There is no AV1 (the chip has no AV1 encoder). HEVC's streams do not decode
  (see below), so only H.264 is offered.
- Pairing completed in about 1.1 s once the PIN was given.
- serverinfo over HTTPS answered with and without a client certificate. An unknown certificate gets `PairStatus` 0.
- launch, the RTSP steps and PLAY all worked. The control stream connected over ENet.
- The first 1280x720 picture left about 0.3 to 0.75 s after PLAY.
- Every frame arrived whole, with none bad. Key frames carried their parameter sets: H.264 NAL types 7, 8 and 5, and
  HEVC 32, 33, 34 and 19. A key frame asked for over the control stream came. (These checks did not decode the
  frames; the HEVC ones turned out not to decode.)
- Sound: every packet decrypted and Opus-decoded (1,350 in 8 s).
- A pointer move to the middle of a 1600x900 PC screen put KWin's pointer at its middle (1750,450, with the output at
  949,0).
- Two PC screens at once (1920x1080 H.264 and 1280x800 HEVC) each passed all 16 checks (before the decode check). Their outputs sat side by
  side at 949,0 and 2869,0, and both were gone after cancel.
- Encoding: about 4 ms a frame at 1280x720 and about 6 ms at 1920x1080 (H.264).
- A still screen sends its last picture again about 10 times a second.
- The Klipper clipboard was read and written, including accents and symbols.
- The helper answered `POCKETXR-HERE 1 47610 steamdeck <ports>` and refused unknown tokens.
- KWin's virtual outputs run at 60 Hz, so a stream that asks for 120 fps gets at most 60 new pictures a second.
- mDNS: SteamOS refused (`Failed to create entry group: Not permitted`), so the phone learns the ports from the
  helper's answer.

Problems found and fixed along the way:

- A Python socket timeout made OpenSSL's reads fail. The TLS socket now blocks, with kernel timeouts.
- KWin opens a new uinput device a moment after it appears, and the kernel drops an absolute position equal to the
  device's last one. The first centring was lost, and the phone's move to the same middle then did nothing. The
  devices are now made when the host starts, and a repeated position is nudged by one unit first.
- kscreen-doctor gives the panel's size already turned. Turning it again put a virtual output over the panel.
- KDE's display-switch pop-up ("Only use external screen" and the other layouts) opened on the Deck's screen when the
  first phone stream started, and stayed there. KWin 6.7 opens it itself when it meets a set of exactly two outputs,
  one built in, that it has no stored setup for: the Deck's screen with a PC screen it has not seen before. The host
  now closes it (kscreen's `hideOsd`, over `busctl`) if it opens in the 6 seconds after a PC screen's output
  appears; other uses of the pop-up are left alone. Seen on the Deck with two new test screens: the pop-up's service
  started and was closed in the same second, and every check still passed. It may show for a moment before closing.

- **HEVC came out as coloured blocks in the glasses** (first phone test, 20 Nov 2026: 1784x976 HEVC; magenta and
  green blocks along the top, pale blocky noise below). SteamOS's Mesa 26.1.2 `hevc_vaapi` writes HEVC that does not
  decode: FFmpeg 8.1.2's decoder, on the Deck and on Windows, reported bad slice headers
  (`alignment_bit_equal_to_one=0`) and missing references, for every size tried (640x368 to 1920x1080), with
  FFmpeg's own command line as well as the host, and with every rate control tried. H.264 from the same pipeline
  decoded with no errors, and a decoded frame showed the desktop as it was. Now `pxr-host-video --probe` encodes
  six moving test pictures with each encoder and decodes them in software (0.2 s in all); an encoder whose pictures
  do not decode is left out, and the host log says `encoder broken hevc`. So the Deck offers H.264 only, and HEVC
  comes back by itself if a later Mesa fixes it. `tools/host_check.py` now decodes the frames it receives with
  FFmpeg too. With the phone's settings (1784x976, 120 fps asked, 64 Mbps, packets of 1024) the H.264 stream passed
  all 17 checks, decoding included.

## To check with the phone

- Pairing through the helper with nothing typed, and that a phone paired with the PC Screens app stays paired.
- The picture at the phone's window shape: frame rate, lag and quality over Wi-Fi.
- Mouse, scrolling, typing (US-layout keys; text that is not on a US keyboard is dropped) and the clipboard both ways.
- Sound on the phone. The Deck's own speakers are silent while a stream runs (a sink of its own), and only the newest
  stream has sound.
- Three PC screens at once.
- GNOME and other desktops: not tried, and not expected to work. The picture needs KWin.
- Gaming Mode: no host (no KWin). The service runs only with Plasma.
