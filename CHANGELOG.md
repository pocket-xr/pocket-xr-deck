# Changes

## Not released yet

From Pierre Zammit's report and logs (Steam Deck LCD, SteamOS 3.9.5, Pocket XR 0.7.0, XREAL XBX A01+). Thanks, Pierre.

- **Recentre takes your tilt.** With the head more than 15 degrees up or down, a recentre makes that pitch straight
  ahead too, so lying back or looking down the screen comes in front of you; the roll is never taken, so the picture
  stays level. Before, it only reset the heading: his log shows "recentred" and then "pitch 16.6 degrees". The same
  in Desktop Mode and Gaming Mode, and when switching the view. As Pocket XR for Mac does. Checked by tests (lying
  back, rolled, a small nod, looking straight down); not yet tried with glasses.
- **The installer updates Decky's panel.** When Decky's plugins folder belongs to root and Pocket XR's panel there is
  older, it now asks to replace it with your password (sudo) and restarts Decky. Before, it only said how to add it.
  Where the folder belongs to you (no password), the panel was replaced in a test install. On a Deck whose folder
  belongs to root (an old 0.2.0 panel there), the sudo path itself was not run, as it would replace that Deck's panel.
- **Update Pocket XR**, a launcher on the desktop and in the app menu that runs the latest installer in a terminal.
  Suggested by Pierre. Made and removed again by a test install.
- **Keys for the back buttons' jobs**, for controllers without L4 and R4: Pause recentres and Scroll Lock switches the
  view, and any action can be given a key in the settings. Map a controller button to the key in Steam Input. In
  Gaming Mode they are read from gamescope's X screens, where Steam Input sends keys: on a Deck, Pause and Scroll Lock
  sent there (XTest) were each seen once. Desktop Mode reads the keyboard devices: on that Deck the built-in keyboard
  and controller were readable, a new virtual keyboard was not. Not yet tried with a Steam Controller.
- **Calibrate (hold still)** in Quick Access: 4 seconds with the glasses lying still measure the gyro's drift, which
  is then taken out and saved for those glasses (and loaded in Desktop Mode too). His glasses drifted about 0.1
  degrees a second to the right while he held still (the log's head direction lines). Checked by tests; not yet tried
  with glasses.
- **Gaming Mode's mouse pointer lines up.** gamescope runs Pocket XR's effect on the game's picture only and draws
  its cursor afterwards (gamescope's source), so on a moved, smaller or curved screen the cursor wasn't over what it
  pointed at. Pocket XR now draws its own pointer on the screen in space, from where the pointer is on gamescope's X
  screen; gamescope's own cursor still shows. It hides after 3 seconds still, as gamescope's does on SteamOS. On a
  Deck: gamescope 3.16.30 compiled the new effect ("Using technique: PocketXR", the same as the current effect; a
  broken copy failed, so the check works), and the pointer was read from gamescope's screen. Not yet seen with glasses.

## 0.7.0 (21 Nov 2026)

- **Ubuntu.** Pocket XR runs on Ubuntu 24.04 and 26.04 as well as SteamOS. Tried in headless GNOME sessions on a PC
  (WSL), not yet with glasses or on real hardware; what was seen is in `docs/UBUNTU.md`.
  - **GNOME on Wayland** (Ubuntu's default, its only GNOME session from 25.10): the main screen in the glasses,
    through GNOME's own screen cast and remote desktop interfaces and a new native helper, `pxr-mutter`. No dialog;
    GNOME shows its screen sharing icon. App windows each in their own place need X11 for now.
  - **X11 with GNOME's window manager** (Ubuntu on Xorg): GNOME's own apps draw a shadow inside their window; app
    windows are now shown and sized without it.
  - **Installer**, off SteamOS: offers the missing system pieces (Python's Tk, SDL2) and a USB permission for the
    Air family's and VITURE's head tracking, both with your password; on GNOME adds shortcuts for the Deck's back
    buttons (Super+Alt+R, V, L, C). Gaming Mode, Decky and the Deck-on-your-phone host stay SteamOS (and Plasma) only.
  - `pocket-xr --button L4 tap` (and the other buttons) works the running app from a shortcut.
  - The panel is not started again and again when it can't open, and a missing library is named instead of a
    traceback.

## 0.6.4 (21 Nov 2026)

- **Readability**, off by default, the same switch as in Pocket XR for Mac and Windows (from a Mac tester's change:
  one lower-resolution screen shown about 30 degrees wide, for sharp text on 1080p glasses). Not yet tried with
  glasses.
  - **Desktop Mode** (a switch on the control panel): the Deck screen alone, 30 degrees wide and in front. It keeps
    the Deck's own 1280x800, already lower than 1440x810; 1280 px across 30 degrees is about one pixel to one
    glasses pixel. In Steady 6DoF the screen is drawn at exactly its own pixels.
  - **Gaming Mode** (a switch in Quick Access): the game screen 30 degrees wide. The game sets its own resolution,
    so this can't make its text larger; it is sharpest for a game drawn 1280 pixels wide.
  - Off puts back exactly what on changed: in Desktop Mode, Deck screen or App windows, the Deck screen's size and
    place, and Steady's size; in Gaming Mode, the size. The values are kept in the settings file, so quitting in
    between changes nothing. Turning it on and off is logged with the values before and after.

## 0.6.3 (21 Nov 2026)

- **Gaming Mode: a curved screen.** Quick Access, Decky, Pocket XR has a **Curve** slider under Size, from 0 % (flat,
  as before) to 100 % (bent round you, every part as far away as the middle). The screen keeps its width along the
  curve. It's remembered, and is off by default. Asked for by Pierre Zammit. Not yet tried on a Deck or with
  glasses; the shader's curve has only been checked by a test that redoes its sums.

## 0.6.2 (20 Nov 2026)

- **XREAL XBX A01 and A01+:** with 0.6.1 an A01+ sent motion after the controller's heartbeat (522 reports a second),
  but the screen still followed the head, and the glasses' buttons were off afterwards. XR Gaming's driver was still
  running on that Deck after its plugin was removed; it reads the same glasses and sets the game screen's effect
  itself. Now:
  - The heartbeat runs only until motion flows (3 s), then stops, because the glasses kept sending without it. If
    the motion then stops, it stays on.
  - The logs carry the first 5 s of motion reports in full (`imu-raw.log`) and, for a minute after the glasses
    appear, a mode is picked or the view is recentred, where the head points once a second.
  - Not yet tried with the glasses. Whether unplugging and replugging gives the buttons back is not yet known.
- **XR Gaming's driver:** the message now says it can still run with its plugin removed, and gives the command that
  stops it: `systemctl --user disable --now xr-driver`.
- **Desktop Mode on Wayland:** the message and the README no longer suggest switching SteamOS's desktop to X11. A
  tester's Deck had trouble after that switch. They point to Gaming Mode, and the README gives the command that puts
  Wayland back: `steamosctl set-default-desktop-session plasma.desktop`.
- **Two buttons in Quick Access**, shown only when they apply, with no terminal or password:
  - **Stop XR Gaming's driver** runs `systemctl --user disable --now xr-driver` when XR Gaming's driver is running
    or set to start.
  - **Put the desktop back to Wayland** runs `steamosctl set-default-desktop-session plasma.desktop` when Desktop
    Mode is set to X11. It applies the next time you switch to Desktop.
  - Both say in the panel whether they worked, and log it. Checked on a Deck with a stand-in for XR Gaming's service.
- **Quick Access panel:** its version now follows Pocket XR's, so the installer offers the new panel when it changes.

Thanks to Pierre Zammit for testing 0.6.1 and sending logs, which led to these changes.

## 0.6.1 (20 Nov 2026)

- **XREAL XBX A01 and A01+:** 0.6.0 got no motion from an A01+: not a single byte came back on its interface 1. Now,
  if interface 1 stays silent for 6 s, Pocket XR wakes the glasses' controller on interface 0 the way XR Gaming's
  driver does (a start-up handshake, then a "heartbeat" every 100 ms), asks again, and then tries interface 2. It
  uses whichever interface sends motion and logs that choice. Not yet tried with the glasses.
- **More in the logs:** which hidraw node is which interface of the glasses, and the first bytes of what each one
  sends, answers included.
- **XR Gaming check:** when XR Gaming's driver (`xrDriver`) runs, the panel and Quick Access say "XR Gaming is running;
  turn it off for Pocket XR's head tracking (or uninstall it)", and the logs' glasses report says whether it is
  running or installed. Two programs asking the same glasses for motion get in each other's way.
- **Gaming Mode's Off** now stops the Air family's motion stream (and the XBX heartbeat) until a mode is picked again,
  so the glasses are left alone.

Thanks to Pierre Zammit for testing 0.6.0 with his XBX A01+ and sending logs, which led to these changes.

## 0.6.0 (20 Nov 2026)

- **Your Deck on your phone.** Pocket XR on the phone can show this Deck's screens as its PC screens, up to three.
  The Deck answers the phone itself in Desktop Mode: no Sunshine Flatpak (the Pocket XR PC Screens app) and no
  separate PC helper. The installer switches those off and keeps their pairings. Tried with one phone so far; more in
  `docs/HOST-DECK.md`.
- **H.264 on SteamOS.** SteamOS's HEVC encoder (Mesa 26.1.2) writes pictures that do not decode: the first phone test
  showed coloured blocks. The Deck now encodes and decodes a few test pictures with each encoder when it starts and
  leaves out any that fail, so it sends H.264. HEVC comes back by itself if a later Mesa fixes it.
- **KDE's display-switch pop-up** ("Only use external screen" and the other layouts) no longer stays on the Deck's
  screen when a phone stream starts: Pocket XR closes it. Other uses of the pop-up are left alone.
- **Show a PC.** Opens your Windows PC's screens as windows in the Space, up to three, through Moonlight and Apollo.
  Not yet tried on a Deck.
- **XREAL XBX A01 and A01+.** Head tracking read as on the other Air models, from the glasses' HID interface 1. Not
  yet tried with the glasses.
- **Desktop Mode on Wayland.** SteamOS 3.9 starts Desktop Mode on Wayland, which Pocket XR's Desktop Mode can't use.
  The message now gives the `steamosctl` command that switches it to X11 (not yet tried), or points to Gaming Mode.
  On X11 the phone's PC screens stop working.

Thanks to Pierre Zammit for his Steam Deck logs with the XREAL XBX A01+, which led to XBX A01 and A01+ head tracking.

## 0.5.1 (18 Nov 2026)

- The VITURE Beast with USB id 35CA:1201 is recognised as a Beast.
