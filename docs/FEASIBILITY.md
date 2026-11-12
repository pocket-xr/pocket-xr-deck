# Pocket XR on the Steam Deck: is it worth it?

Written 11 Nov 2026, before any test on the Deck. The test result goes at the end.

## The short answer

Yes, a first version is quick. Reading the glasses and holding one window still in Desktop Mode is
a few days, not weeks. A version that sits under Gaming Mode games is harder, and Breezy Desktop
already does that for most glasses, but not for the XREAL Aura.

It is a new Linux app. It shares Pocket XR's knowledge of the glasses, not its Android code.

## What the Deck version is

- The glasses plug into the Deck's USB-C port. They get the picture over DisplayPort and send
  their motion back over the same cable.
- The Deck reads head tracking itself. No phone is involved.
- The Deck draws its game or desktop windows as screens that stay put in space while the head
  turns (3DoF). Later, on the Aura, the glasses' own Spatial Anchor can hold a wide canvas in
  6DoF, as Pocket XR's Steady mode does on the phone.

## Desktop Mode or Gaming Mode

| | Desktop Mode (KDE Plasma) | Gaming Mode (gamescope) |
|---|---|---|
| Who owns the screen | KDE. Our app is one fullscreen window on the glasses' output. | gamescope. Nothing else can draw on top without hooking into it. |
| Getting window pictures | X11 or PipeWire screen capture of a window or the whole desktop. Ordinary, documented. | Only by being inside the frame path: a gamescope effect, a Vulkan layer, or a patched gamescope. |
| Input | Normal mouse and keyboard; Steam Input as a desktop controller. | Steam Input belongs to the game. |
| Who wants it | People using the Deck as a small PC with a big virtual screen. | People playing games, which is most Deck owners. |
| Effort | Small. The prototype here is this path. | Large. Breezy did it with a Vulkan layer. |

So the plan is Desktop Mode first, because it can be built and tested fast. Gaming Mode is a
separate decision, made after seeing whether Desktop Mode is good enough to use.

## Breezy Desktop already exists

Breezy Desktop (GPL-3.0, by Wayne Heaney) and its Decky plugin, Decky XR Gaming, already do
this on the Deck.

- **Desktop:** Breezy Desktop runs on KDE Plasma 6 and GNOME. Its virtual displays need Wayland.
  After a two month trial, the many-screens features need a paid licence ($10 a year or $25
  once for 3DoF, more for 6DoF).
- **Gaming Mode:** Decky XR Gaming installs Breezy's Vulkan layer. Virtual display, VR-lite
  mouse look and Follow are free. Smooth Follow, auto recentre and side by side 3D are a
  supporter tier ($10 a year or $25 once).
- **Glasses:** its driver, XRLinuxDriver, lists VITURE, RayNeo, Rokid, the XREAL Air family and
  the XREAL One, One Pro and 1S. It marks XREAL as "not recommended". **The Aura is not listed.**

What Pocket XR on the Deck could do that Breezy does not:

1. **The Aura, done properly.** Pocket XR already knows the Aura's control link: 2D and 3D,
   Ultrawide, screen size, and turning Spatial Anchor on and off. That gives 6DoF on the Aura
   for free, from the glasses themselves.
2. **Free and open.** No paid tier. Same GPL-3.0 as Pocket XR.
3. **The same app on phone and Deck.** One set of settings words, one Glasses report, one place
   to send logs.

What Breezy does that we would not have for a long time: Gaming Mode games, many glasses
brands, years of testing. For a non-Aura user on Gaming Mode, Breezy is the better answer
today, and we should say so.

## The stack

- **Language:** Python 3 for the prototype, because SteamOS has it and nothing must be
  installed. It talks to SDL2 and OpenGL through `ctypes`, both already on SteamOS. A real app
  would likely move to C or Rust with SDL2 or Vulkan, and ship as a Flatpak or AppImage, since
  the SteamOS system folders are read only and wiped on updates.
- **Head tracking:** a plain TCP read of the glasses' sensor stream, then our own fusion filter.
- **Picture:** one fullscreen window on the glasses' output, drawing a textured quad with the
  head's rotation undone. Window contents come from X11 capture now, PipeWire later.
- **Glasses link:** the Linux kernel's own `cdc_ncm` network driver brings up the glasses'
  USB network, as Android does on the phone.

## What ports from Pocket XR

Rewritten in our own words for the new language. These are protocol facts, so they move over
cleanly.

| Pocket XR piece | What it is | On the Deck |
|---|---|---|
| `OneImuProtocol` | One family and Aura sensor stream on 169.254.2.1:52998: magic 0x28 0x36, 128 byte reports, gyro, accel, mag, temperature | Ports directly. Done in the prototype. |
| `GlassesWire` | Control link on 169.254.2.1:52999: u16 type, u32 length, u32 id, protobuf body | Ports directly. Needed for 2D/3D and Spatial Anchor. Not used in the prototype. |
| Aura commands | 10273/10274 2D and 3D, 10277/10278 Ultrawide, 10397/10398 size, 10404/10405 Spatial Anchor, 10015 calibration | Ports directly, only the proven ones. |
| `AirImuProtocol`, `AirDisplayMode` | Air family HID stream and display mode | Ports, through Linux hidraw. |
| `VitureImuProtocol` | VITURE HID stream | Ports, through hidraw. |
| `HeadFusion`, `FactoryCalibration`, `AxisMap` | Fusion filter, factory gyro matrix and display mount, sensor axes per model | The ideas port. The code is 2400 lines of Kotlin tied to the phone's timing, so it is a rewrite. |
| Steady mode, `WideCanvas` | Aura 6DoF through Spatial Anchor | Ports as a sequence of proven commands. |

What does not port: virtual displays and Shizuku, Android apps as windows, DeX, the phone's
Presentation display, Joy-Con pairing through Android, the Play Store build, and the OpenXR
runtime as packaged for Android. Linux has its own answers to each (X11 or PipeWire capture,
BlueZ for Joy-Cons, Monado runs natively on Linux).

## Testing

There is no real Steam Deck emulator. A SteamOS virtual machine shows that the app starts, but
not the glasses' USB network, the DisplayPort picture, or gamescope. So every test runs on
Mike's Deck, over SSH, with Mike wearing the glasses.

## Risks

- **Aura on Linux is untried.** If the Deck's kernel does not bring up the glasses' USB
  network, there is no head tracking. The prototype finds this out first.
- **Spatial Anchor and 3D.** The glasses' own anchor fights our tracking, so it must be off for
  3DoF (the prototype asks Mike to turn it off in the glasses' menu; it sends no commands).
- **Gaming Mode is the real prize** and the costly part.
- **Time.** Every hour here is an hour not spent on the phone app and its testers.

## Prototype test result

11 Nov 2026, Mike's Steam Deck (SteamOS 3.7.17, Desktop Mode on X11) with his XREAL Aura on
the Deck's USB-C port, in 2D, Spatial Anchor off.

- **Glasses link:** SteamOS brought up both of the Aura's USB networks by itself (169.254.2.10
  and 169.254.1.10, by the glasses' DHCP). No setup, no root.
- **Head tracking:** 1000 reports a second from 169.254.2.1:52998, none dropped, over about
  3 minutes. Gravity reads along +y, so the Aura's axes are the same on Linux as on the phone.
- **Picture:** the glasses show as "XREAL 1 Ultra" at 1920x1080, 90 Hz. The prototype drew a
  steady 90 fps for the whole test.
- **Mike, wearing the glasses:** "Stays put, works." The test card held still in the room
  while he turned and nodded.
- **Nothing was sent to the glasses.**

**Second test, the Deck's own desktop as the window (`--capture`):**

- The Deck's screen (1280x800) is copied 30 times a second through X11 and shown on the
  glasses at 90 fps.
- Two faults found and fixed on the day:
  - The window closed a few seconds in. SDL treats the hang-up from a closing SSH session as
    "quit". The prototype now runs as a user service (`start.sh`).
  - The window crept right, about 3 deg/s. The gyro zero was learnt from the first 1.5 s while
    Mike's head was turning. The Aura's stream is already close to zero at rest (under
    0.5 deg/s, about 0.3 deg/s of noise), so the zero is now learnt only from quiet half
    seconds, all the time.
- Mike, after the fixes: "Stays put now."
- Mike chose to go on after reading this write-up.

**Third test, the mouse pointer:** X11 capture leaves the pointer out, so the prototype draws
its own arrow on the window. The pointer is also kept on the Deck's screen: on the glasses'
screen it could not be seen. Mike: "Pointer works." Holding the pointer at the right edge for
a second recentres; it is in, but no recentre was used in that test.

**Fourth test, Steady mode in 6DoF on the Aura (`steady.py on`, then `--canvas`):**

- The Deck sent its first commands to the glasses, only those Pocket XR proved on the Aura:
  Ultrawide on (10278), then Spatial Anchor on (10405), each read back. The size was already
  Ultrawide's largest (1.2). The bytes are checked offline against Pocket XR's, and every other
  id is refused (never 10079 or 10325 to 10328).
- An anchor set sent within a second of Ultrawide was refused with 5001. Spaced 3 s apart, as
  Pocket XR does on the phone, it took first time.
- The desktop is drawn flat on the 3840x1080 canvas at 60 Hz; the glasses hold it in the room.
- Mike, leaning and stepping around: "Holds in 6DoF."
- Other glasses follow Pocket XR's rules: the One series with the XREAL Eye gets the canvas and
  is told to turn 6DoF on in its own menu (untested, Mike has no One); VITURE waits on its SDK;
  others have no 6DoF source. Nothing is sent to them.

Not tried yet: `steady.py off` on the Deck, 3D side by side, runs of an hour or more, Gaming Mode.

So the main risk, whether the Aura works on the Deck at all, is gone.
