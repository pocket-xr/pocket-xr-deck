# Changes

## 0.7.19 (26 Nov 2026)

- **Logs show a slow drift.** The head's direction went in the log once a second for a minute after the glasses, a
  mode change or a recentre, then not at all, so a drift building over minutes never reached a log sent after it.
  It now goes on every 10 seconds (about 360 lines an hour). From Pierre Zammit's logs on 0.7.18's drift question.

## 0.7.18 (26 Nov 2026)

From Pierre Zammit's report and log on 0.7.17 (Steam Deck LCD, XREAL XBX A01+). Thanks, Pierre.

- **Pocket XR's pointer no longer disappears in games and apps.** 0.7.17's hiding of the app's cursor by name made
  Pocket XR mistake that hidden cursor for the app hiding its own, so its pointer went too: invisible in a game though
  it still worked, and in Stremio shown only over pictures. Against a stand-in X screen, 0.7.17 hid the pointer once
  the app set its cursor again and 0.7.18 keeps it. Not yet tried on a Deck.

## 0.7.17 (25 Nov 2026)

From Pierre Zammit's report and log on 0.7.16 (Steam Deck LCD, XREAL XBX A01+). Thanks, Pierre.

- **No second arrow with a second app open.** Gamescope draws the arrow of the app that has the keyboard, which can
  be on a different X screen from the one Pocket XR follows the mouse on. 0.7.16 hid the arrow on that one screen
  only, and only over an app's window, so with a second app open gamescope's arrow stayed and moved with the head.
  Now the arrow is hidden on every X screen, over the empty background too. Against two stand-in X screens, 0.7.16
  left both arrows showing and 0.7.17 hid both; not yet tried on a Deck.
- **The flicker over links and buttons, fixed at last.** 0.7.15's hiding by name and 0.7.16's instant hiding never
  actually ran: Pocket XR asked the X library for a function it doesn't have, and turned both off when it wasn't
  found. Against a stand-in X screen with a browser-like app hovering on and off a link 40 times, 0.7.16 showed the
  hand every time and 0.7.17 only the first time (then never again). A new cursor is now hidden within a millisecond,
  where 0.7.16 took about 7. Not yet tried on a Deck.
- **The pointer on a game's screen when it changes size.** Gamescope resizes a game's X screen after it opens, and
  Pocket XR kept the size from the moment it opened (his log has the pointer at 1916,1065 on a "1280x800" screen).
  The size is now read again as it changes.
- **Less slow drift once calibrated.** After a hold-still calibration, Pocket XR still kept fine-tuning the gyro's
  zero while the glasses were worn. His log's motion data shows a worn, still head moves just enough to look like a
  gyro error, so the screen could creep slowly to one side. Now, once calibrated, only stillness as quiet as glasses
  lying on a table fine-tunes it, and the log says each time it changes. Checked with his motion data and tests;
  not yet tried worn.

## 0.7.16 (25 Nov 2026)

From Pierre Zammit's report, videos and log on 0.7.15 (Steam Deck LCD, XREAL XBX A01+). Thanks, Pierre.

- **The pointer is followed in games, for real this time.** 0.7.15 opened the X screen that never answers on a thread
  of its own, but his log shows the program stuck all the same, now in its ordinary calls on the screen that did
  answer: the X library locks across the whole program, and the open that never ended held that lock. Now each new X
  screen is first asked over its socket, without the X library, and opened only once it answers. One that doesn't is
  asked again every 15 seconds while the others are followed. Checked by tests, against a socket that never answers
  and against WSL's own X server; not yet tried on a Deck.
- **The second arrow over links and buttons, again.** In Nested Desktop the browser's cursors come from the desktop
  inside it, which makes them from pictures with no name, so 0.7.15's blanking by name never applied there. Pocket XR
  is now told the moment the cursor changes and blanks the new one at once, instead of at its next look up to 1/30 s
  later, before gamescope draws its next frame in most cases. Checked by tests; not yet tried on a Deck.
- **Use the glasses' buttons:** the note now says unplugging the glasses and plugging them back in is quicker than
  waiting for them to blink (his tip), in every language.

## 0.7.15 (25 Nov 2026)

From Pierre Zammit's report and two logs on 0.7.14 (Steam Deck LCD, XREAL XBX A01+). Thanks, Pierre.

- **The pointer is followed in games again.** From the moment a game started, the program that follows the mouse got
  stuck opening one of gamescope's X screens, which was there but never answered. Each time it was restarted (every
  10 seconds) it tried that screen again and stuck again, so the pointer was never followed and gamescope's own arrow
  moved with the head. Now each X screen gets 2 seconds to open. One that doesn't answer is left to open on its own,
  and the others are followed meanwhile. The log says so once. Checked by tests with a stand-in screen that never
  answers; not yet tried on a Deck.
- **No second arrow flickering over links and buttons.** A browser sets a new cursor each time the pointer goes onto a
  link or a button (a hand, a text bar). Gamescope drew it until Pocket XR blanked it again up to 1/30 s later, which
  was the arrow flickering in and out. Cursors an app loads from its theme have a name, so Pocket XR now blanks every
  cursor of that name at once, and the next hover shows nothing. Turning the screen in space off gives them back from
  the cursor theme. If Pocket XR ends without giving them back, its next start does. Written from Xorg's and
  libXcursor's source and checked by tests; not yet tried on a Deck.

## 0.7.14 (24 Nov 2026)

- **Up to six PC screens for a phone.** Pocket XR on a phone could open three of this computer's screens; now it can
  open up to six. **PC screens for a phone** on the control panel, under Text size, sets how many (1 to 6). It starts
  at 3, so nothing changes until you raise it. Screens 4, 5 and 6 are on ports 50989, 51989 and 52989, after 47989,
  48989 and 49989, so open those on the firewall too if you have one. The host follows the setting within 10 seconds
  with no restart, and the helper tells the phone the new list. Lowering it never cuts a stream: a screen a phone
  streams from stops once that stream ends. The number and the ports are set in one place (`pocketxr/host/screens.py`).
  What has been checked: the tests, and the host in WSL, where it served all six (screen 6 answered as "screen 6" on
  52989, and the helper listed six ports) and dropped to four when the setting changed. **Not yet tried with a phone
  or on a Deck: nothing has streamed from more than three screens.** Whether the phone's Pocket XR opens more than
  three, and whether the Deck can capture and encode that many streams at once, is not known yet. The setting's line on
  the control panel is in English only for now, as the PC screens' other lines.
- **The control panel scrolls.** It was taller than its window (720 pixels high at most, 560 on a Deck), so its lower
  rows were cut off: Text size sat half under Send logs, and Window in front and the back buttons' guide could not be
  seen at all. Now everything between the title and Send logs scrolls, with the mouse wheel, the trackpad or a drag on
  the touch screen, and a thin bar on the right shows where you are. Send logs and Quit stay where they are. A drag
  that starts on a button scrolls and does not press it; a tap still does. Checked in WSL with the Inter fonts, at 560
  and 720 pixels: every row, PC screens for a phone included, could be scrolled into view clear of Send logs. Not yet
  tried on a Deck's touch screen.

## 0.7.13 (24 Nov 2026)

From Pierre Zammit's video and log on 0.7.12 ("I have taken a video of what the issue with the cursor/mouse pointer
is"). Thanks, Pierre.

- **The pointer reader starts again when it gets stuck.** His video shows one arrow, to the left of where clicks land.
  His log shows why: Pocket XR's pointer reader started, said one line and then nothing for the 17 minutes logged,
  without ending. So Pocket XR drew no pointer of its own, never hid gamescope's arrow and logged no clicks, and the
  arrow he saw was gamescope's, which is never where clicks land with the screen in space. The same reader on an X
  server here (WSLg) answered at once, so on his Deck one of gamescope's X screens most likely stopped answering a
  question. Now a look that takes more than 10 seconds prints where the reader was stuck into the log, the reader ends
  and Pocket XR starts it again 10 seconds later, as it does when gamescope restarts. The first three times the whole
  stack goes in the log, so the next log shows which X call it was. Checked by a test with an X screen that never
  answers; not yet tried on a Deck. During those 10 seconds Pocket XR's pointer and the back buttons' keys still don't work.

## 0.7.12 (24 Nov 2026)

From Pierre Zammit's report on 0.7.11: "if you manage to solve the mouse pointer issue I'd say it would be perfect".
Thanks, Pierre.

- **Only one pointer with the screen in space.** What was wrong, looked at end to end in gamescope's source and his
  logs: Pocket XR reads the pointer from the X screen gamescope says has the mouse, and since 0.7.5 measures it across
  the game's window, which his 0.7.10 log shows as the whole 1920x1080 X screen; gamescope runs Pocket XR's effect on
  that window's picture at its own size (rendervulkan.cpp, vulkan_composite), so the effect's arrow is drawn on the
  same point of the game's picture, after the curve and the size, where a click lands. gamescope then draws its own
  arrow after the effect (steamcompmgr.cpp, MouseCursor::paint), at the pointer's place on a flat screen: with the
  screen moved, smaller or curved it is somewhere else, and it moves with the head. gamescope has no option or
  property to hide it, but draws nothing when the app's cursor image is empty. So now, while the screen is in space,
  Pocket XR gives the app's window under the pointer a blank cursor (any X program may), and gives it back when the
  screen goes flat, the switch is turned off, or Pocket XR's pointer reader ends. It keeps track of whether the game
  wants a cursor, so Pocket XR's own arrow still shows and hides with the game's. **Hide the moving pointer** in Quick
  Access turns it off; it is on at first. Tried on an X server (WSLg's Xwayland): the cursor image went empty while
  hidden and came back after; not yet tried in gamescope on a Deck. While it is hidden, a game that changes its cursor
  may flash it for up to a thirtieth of a second. Given back, the window has the X screen's own arrow until the game
  sets its cursor again.
- **Clicks in the log.** The pointer reader logs where the left button went down (at most once a second): the X
  screen, the pointer there and where Pocket XR draws it on the picture, so a log can show any offset left.

## 0.7.11 (24 Nov 2026)

From Pierre Zammit's report and log on 0.7.10 (Steam Deck LCD, XREAL XBX A01+). Thanks, Pierre.

- **Tap sensitivity**, a slider in Quick Access under Taps on the glasses: 25% to 300%, 100% at first, which is the
  values he found "more sensitive than I expected, in a good way". It divides the jolt and the sudden jump a tap needs
  (0.25 g and 0.15 g at 100%), so higher catches softer taps and lower only firm ones. Pressing the glasses' buttons
  can count as a tap (he found it does), more so when it is high. The log gives the values when it changes. Checked
  by tests; not yet tried on glasses.
- **Recentre includes head tilt**, a switch in Quick Access, off at first: Recentre takes the head's roll too, as well
  as where it faces and its up or down, so lying on one side the picture lines up with the eyes and fills the
  glasses' picture, instead of staying level with the room ("a skewed picture"). Off keeps the horizon level, as
  before: on, a small tilt of the head sitting up would tilt the picture. Looking almost straight up or down, roll
  and heading are the same turn, so it behaves as without. Checked by tests (the view at a recentre is level with the
  eyes for any heading, pitch and roll); not yet tried with glasses.
- **Glasses brightness: not on the XBX.** Every set, 1 to 7, was answered "04" and his brightness stayed. The XBX's
  controller answers with a status byte first (0 for done: ermay12/xrdesk's notes on the A01+, GPL-3.0), so 04 is a
  status, not a level: 0.7.9's reading of it as "level 4" was wrong, and the XBX doesn't take Monado's commands. Now
  the slider shows only when the glasses read out a level (status 0, then the level), each set is read back, and it
  hides itself, with a line in the log saying why, when the answer is a refusing status or the level doesn't change.
  No public source documents a brightness command for the XBX. Those notes also say what his presses were: on the
  XBX, buttons 2 and 3 are volume up and down (1 is the menu), sent to Pocket XR while it has the glasses; still only
  logged.

## 0.7.10 (23 Nov 2026)

- **Text size and Readability for the PC screens a phone streams from this Deck or PC**, as in Pocket XR for Mac
  (asked for by Mike after a question on Reddit about text on PC screens). Text size, on the control panel: Standard,
  125% or 150%, the Mac's sizes (each 1920x1080 screen laid out as 1920x1080, 1536x864 or 1280x720). Readability lays
  it out as 1440x810 instead, as the Mac's. Each PC screen is a KWin virtual output at the size the phone asks for;
  Pocket XR now sets KWin's scale on it when it is made (kscreen-doctor, as Plasma's Display settings), so it keeps
  all its pixels and text stays sharp. Set at Standard too, as KWin remembers an output's scale. The host's log says
  what each screen was made at, the scale and what apps see. Plasma on Wayland only; checked by tests, not yet with a
  phone. Desktop Mode's own Space keeps its Readability (the Deck screen alone, 30 degrees wide: 1280 px at about 43
  px a degree, the Mac's 1440 px across 34 degrees is about 42); Text size is not offered there, as on X11 KDE has
  one scale for all screens, so a larger size there could only stretch pixels.

## 0.7.9 (23 Nov 2026)

From Pierre Zammit's report and log on 0.7.8 (Steam Deck LCD, XREAL XBX A01+). Thanks, Pierre.

- **Three taps bring the screen back from Off.** Triple taps worked, but only from the screen in space to Off. Off
  stopped the glasses' motion stream (the heartbeat keeps going), so in Off no tap could be seen. Now, with Taps on
  the glasses on, Off keeps reading the motion, for the taps only (the screen stays off), and three taps go back to
  the screen in space. With Taps off, Off stops the stream as before. "Use the glasses' buttons" still lets go of the
  glasses completely, so there taps can't work. Checked by tests; not yet tried on glasses.
- **The brightness slider shows.** His glasses answered the brightness question, but 0.7.8 expected Monado's layout
  (a status byte, then the level) and set the answer aside. The XBX's answer frame says by its length field (18 = 17
  + 1) that it carries one byte, 04: the level, 4 of 7. Now a frame's data is cut to its length field, and a one-byte
  answer is read as the level (Monado's two-byte layout still works). The slider shows once the glasses answer at
  all, with the last level known. Each answer is logged whole, and so is what the glasses answer to each set, so a log
  shows whether the XBX takes the set (not known yet). His log also shows the XBX reporting its own button presses
  in this mode (button 3, actions 16, 17 and 1); they are logged, not acted on, as what they mean isn't documented.

## 0.7.8 (23 Nov 2026)

From Pierre Zammit's report and log on 0.7.7 (Steam Deck LCD, XREAL XBX A01+). Thanks, Pierre.

- **Triple taps: firm taps count.** Double taps worked; triple taps mostly didn't. His firm taps (0.8 to 5 g)
  lasted 61 to 101 ms with the frame's swing after them, and the third taps that were left out were 86, 100 and
  101 ms long, over 0.7.7's 80 ms. A tap may now last up to 150 ms. His recordings of head movement and of putting
  the glasses on still give no gesture (even at 200 ms). One run reached four taps and did nothing: that was four
  real taps (all firm and sharp, about 440 ms apart), not an echo; each tap's echo is a small slow rebound 95 to 150
  ms later, which already doesn't count. That stays as it is. The jolt log allows 120 lines a minute (30 before ran
  out, so two gestures had no lines before them). Checked by tests and his recordings; not yet tried on glasses.
- **The USB reset is gone.** In his log the reset went through (with 0.7.7's USB permission) but the glasses carried
  on, and their buttons came back 2 min 40 s later as before: a reset leaves the glasses powered, so their
  controller keeps the mode Pocket XR's handshake put it in. Deauthorising them in sysfs also leaves them powered;
  cutting the port's power isn't something most USB hubs can do, and on the Deck's USB-C port the power comes from
  its USB Power Delivery controller. No public driver documents a command that ends that mode. The installer no
  longer offers the USB permission, says it's unused if it's there, and uninstall.sh still removes it. "Use the
  glasses' buttons" stays, with the steps (wait for the glasses to blink off and on).
- **Glasses brightness in Quick Access.** Instead of letting go of the glasses, Pocket XR can set their brightness
  while it has them, through their controller: Monado's XREAL Air driver (BSL-1.0) reads it with message 0x03 and
  sets it with 0x04 (one byte, 0 to 7), in the same frames Pocket XR already sends the XBX. A slider in Quick Access
  shows it while the controller is awake (the XBX's heartbeat). The glasses' own button presses (message 0x6C05) are
  logged, and when one says brightness up or down with the new level, Pocket XR sets that level, in case the glasses
  only report the press. Monado wrote these for the Air, Air 2 and Air 2 Pro; whether the XBX takes them is not
  known yet: the log says what it answers.

## 0.7.7 (23 Nov 2026)

From Pierre Zammit's report and logs on 0.7.6 (Steam Deck LCD, XREAL XBX A01+). Thanks, Pierre.

- **Taps on the glasses: softer taps count, and every jolt is logged.** He double tapped the top of the frame many
  times and it worked twice; the misses left nothing in the log. His one recording with taps in it (imu-raw.log,
  three taps about 320 ms apart) shows why: the taps were 0.33 to 0.51 g away from the 30 ms average, and 0.7.6
  wanted 0.8 g. What does set them apart is how suddenly they start: 0.23 to 0.42 g within 3 ms, where none of his
  plain head movement went over 0.10 g. Now a tap is a jolt of 0.25 g with a 0.15 g jump within 3 ms, lasting up to
  80 ms (the frame's swing after a tap is part of it, so it doesn't eat the next tap), after 60 ms still, with the
  head turning under 60 degrees a second. Taps may be 0.2 to 0.7 s apart (2 a second works; 0.7.6 took up to 0.45 s).
  Replayed through his six recordings: his three taps count as three; plain head movement and putting the glasses on
  (two sharp jolts 134 ms apart) give nothing. Every jolt over 0.15 g goes in the log with its peak, jump, length,
  the stillness before it, the head's turn, the gap to the last tap, and why it did or didn't count (at most 30 lines
  a minute). Quick Access says the cadence. Not yet tried with real taps on glasses; a few steps of walking with
  sharp heel strikes (made-up ones, 0.7 g over 20 ms) count as taps, so it stays off at first.
- **Use the glasses' buttons: the wait, and a USB reset.** It worked for him, but the buttons came back only 1 min
  20 s, 1 min 45 s and 3 min 25 s after turning it on: the glasses keep the mode Pocket XR's handshake puts them in
  until they reset themselves. No public driver documents a command that ends that mode (xrealAirLinuxDriver's list
  has none, and its close only closes the file), so none is sent. Pocket XR now tries a USB reset of the glasses when
  letting go (as unplugging them), and logs whether it was allowed: udev's default gives the user no write access to
  the glasses' USB device, so it may well be refused on SteamOS. The switch stays on when the glasses come back after
  the reset. Its text now gives his steps: set the mode to Off, turn this on, wait for the glasses to blink off and on
  (up to a few minutes), adjust them, turn this off, then pick a mode. Checked by tests; the reset is not yet tried on
  a Deck.
- **The USB permission for that reset.** The installer offers a udev rule, `/etc/udev/rules.d/71-pocket-xr-usb.rules`,
  that lets whoever sits at the Deck (uaccess) reset XREAL (3318) and VITURE (35ca) glasses over USB, and no other
  USB device. It asks with your password (sudo), as for the Quick Access panel, says why, reloads udev and asks you
  to unplug and plug in the glasses. Saying no keeps the rest working: the buttons then come back when the glasses
  reset themselves, and the log says the reset needs the rule. It is in /etc, which SteamOS keeps across its updates
  (not yet seen across one); uninstall.sh offers to remove it, and the older hidraw rule (70-pocket-xr.rules). Tried
  by a test install with a stand-in sudo; not yet on a Deck.

## 0.7.6 (23 Nov 2026)

From Pierre Zammit's report and logs on 0.7.5 (Steam Deck LCD, XREAL XBX A01+). Thanks, Pierre.

- **An update now restarts what is running.** His logs say 0.7.5 and the Quick Access panel 0.7.5, but the Gaming
  Mode service kept running 0.7.3's code all afternoon (its log lines are 0.7.3's), so 0.7.4's and 0.7.5's changes
  never ran for him. He updated in Gaming Mode: the installer restarted Decky (the panel came up as 0.7.5) but its
  restart of the service did not take, and it hid the error. Now:
  - the installer restarts the service without Steam's own libraries in the way (what a program started from Steam
    passes on), and says if it still can't, with what to do (restart the Deck);
  - the service checks every 5 seconds whether a new Pocket XR was installed over it, and starts again to load it;
  - the service logs its version when it starts, and Quick Access shows a warning when the service and the panel are
    different versions;
  - the installer closes Pocket XR's desktop app if it is open, and opens it again in Desktop Mode.
  Why the old restart failed is not known for sure: its error was hidden. The new restart was tried by tests and a
  test install (not on a Deck); the service's own restart by tests.
- **Use the glasses' buttons**, a switch in Quick Access: Pocket XR lets go of the glasses (no motion stream, no
  heartbeat, every file on them closed) until it is turned off, so their own buttons can work, for brightness say.
  Head tracking pauses meanwhile. Checked by tests with stand-in glasses; whether his glasses' buttons come back this
  way is not known yet.
- **Pointer in Nested Desktop.** Nested Desktop runs Plasma as a Wayland window inside gamescope, and no X screen
  sees its pointer: gamescope names a Wayland display as the one with the mouse then, and 0.7.5 took the last moved X
  screen instead, so its pointer could be anywhere. Now Pocket XR's pointer is hidden while a Wayland window has the
  mouse, and the log says so. The pointer's maths already take the curve and the size into account (it is drawn
  where the moved picture shows that point). His logs were from 0.7.3's code, so 0.7.5's pointer measured across the
  game's window has not been tried yet: a log from 0.7.6 will tell. Written from gamescope's source and checked by
  tests; not yet tried on a Deck.

## 0.7.5 (23 Nov 2026)

From Pierre Zammit's report and logs on 0.7.4 and 0.7.3 (Steam Deck LCD, XREAL XBX A01+). Thanks, Pierre.

- **XBX: the heartbeat at its pace.** With 0.7.4 he had no disconnects, but head tracking stopped about 3 minutes
  after it started, every time, and then every write to the glasses and every open timed out (ETIMEDOUT): the
  glasses' controller had stopped answering. Pocket XR sent the next heartbeat as soon as the glasses answered the
  last one, so far more often than XREAL's driver, which sends one every 100 ms: a test with stand-in glasses that
  answer at once counted about 6000 a second. Now exactly one goes out every 100 ms, it keeps going while the glasses
  are attached (as 0.7.4), and the log gives the rate once a minute. A test checks the pacing. Whether this stops the
  disconnects or the stopped tracking is not known yet: not yet tried with glasses.
- **Taps on the glasses:** tap the frame twice to recentre, three times to switch the view, with any controller or
  with the Deck put down. Read from the glasses' motion sensor: a short, sharp jolt after a quiet moment, left out
  during fast head turns, and walking's slower jolts are too soft or too long to count. Off at first, with a switch in
  Quick Access. Checked by tests (made-up taps, head turns and walking) and against his four recordings of head
  movement (no taps found); not yet tried with real taps on glasses.
- **Gaming Mode's pointer, across the game's window.** His 0.7.4 log shows the game's X screen (:1 1280x800) in use
  while he played, and the pointer was still off. gamescope's effect works on the game's window, not the whole X
  screen, so a game whose window is smaller than its screen (a 16:9 game on the Deck's 16:10 screen, say) put the
  pointer off by the difference. Now the pointer is measured across the window gamescope names as the focused one
  (GAMESCOPE_FOCUSED_WINDOW), and the log names that window. Written from gamescope's source and checked by tests;
  not yet tried on a Deck. The second arrow that moves with the head and the trackpad is gamescope's own, drawn
  after Pocket XR's effect: Pocket XR can't move or hide it.
- **Brightness in Quick Access: not added.** The glasses' buttons don't work while the heartbeat runs, so he asked
  for brightness in the panel. The only public driver found that names a brightness command (xrealAirLinuxDriver,
  MIT: "W_BRIGHTNESS", 0x04) never sends it and doesn't say what it takes, and doesn't cover the XBX. Pocket XR
  doesn't guess at commands for the glasses, so this is left out.

## 0.7.4 (22 Nov 2026)

From Pierre Zammit's report on his XREAL XBX A01+ (Steam Deck). Thanks, Pierre.

- **XBX: the heartbeat keeps going.** With Pocket XR disabled his glasses stopped disconnecting; with it on, the
  whole USB-C link (the display too) reset about every 10 minutes, with head tracking on and with Off. His first drop
  was on 21 Nov, the day after 0.6.2 began stopping the glasses' MCU heartbeat 3 seconds after motion started. XREAL's
  own driver keeps it going. So now, once Pocket XR has woken the MCU, the heartbeat (every 100 ms) keeps going while
  the glasses are attached, through Off too (Off still stops the motion stream). It stops when the glasses go, when
  Pocket XR stops reading them, or when a write to them fails. This is a guess that the glasses reset the link when
  the heartbeat stops, not proven. The known cost: with 0.6.1, whose heartbeat also kept going, his glasses' buttons
  did not work while it ran. Checked by tests; not yet tried with glasses.
- **The logs** say when the heartbeat starts and stops and why, and each drop says how long it was since the last
  heartbeat.

## 0.7.3 (22 Nov 2026)

From Pierre Zammit's report and logs on 0.7.2 (Steam Deck LCD, SteamOS 3.9.5, XREAL XBX A01+). Thanks, Pierre.

- **XBX: motion at once.** Each time his glasses appeared (after boot and after each USB drop), interface 1 sent
  nothing for the whole 6 second wait, then samples came within a second of the MCU heartbeat. The XBX now gets the
  heartbeat first, not after 6 silent seconds; if the MCU doesn't answer, interface 1 alone and then interface 2 are
  still tried. Checked by tests; not yet tried with glasses.
- **Gaming Mode's pointer: the right X screen.** gamescope runs two X screens, :0 (Steam, 1920x1080 on his glasses)
  and :1 (the game, 1280x800), and his log flips between them while playing: 0.7.2 took the one whose pointer moved
  last, so the pointer could be placed by the wrong screen's size. Now the screen gamescope says has the mouse
  (GAMESCOPE_MOUSE_FOCUS_DISPLAY) is taken, the last moved one otherwise. Written from gamescope's source and checked
  by tests; not yet tried on a Deck. gamescope's own arrow is drawn after Pocket XR's effect, so it still moves with
  the head.
- **One line, not one every 3 seconds.** A third X screen that wouldn't open put libX11's "Authorization required"
  in the log twice every 3 seconds. Now it is said once.
- **Stick clicks**, in every game without Steam Input setup, on the Deck's own controller: hold L3 for a second to
  recentre, hold R3 to switch the view, click L3 three times to calibrate (it starts 5 seconds later). On at first,
  with a switch in Quick Access. The stick click bits are taken from Linux's hid-steam driver, not yet checked by
  pressing them on a Deck. Other controllers: their buttons go to games through Steam Input, so the Stop and Next keys
  stay the way. Checked by tests.
- His two drops (19:35:10 and 20:17:32) show "Air link lost (Input/output error)" with the glasses' interfaces back
  within 3 seconds, and at 20:17:32 the glasses' display went too: the whole USB-C link reset. No change for this.

## 0.7.2 (22 Nov 2026)

From Pierre Zammit's report and logs on 0.7.1 (Steam Deck LCD, SteamOS 3.9.5, XREAL XBX A01+). Thanks, Pierre.

- **Recentre takes any tilt.** 0.7.1 took the head's up or down only past 15 degrees, and Pierre found recentre still
  moved the screen only sideways. Now a recentre you ask for always takes it, however small; the roll is still never
  taken. Checked by tests (a small nod up and down is taken); not yet tried with glasses.
- **Keys Steam Input has.** Steam Input's keyboard has no Pause or Scroll Lock (his screenshots), so the media key
  **Stop** now recentres and **Next** switches the view. Pause and Scroll Lock still work from a real keyboard. A
  setting can now give an action several keys. On a Deck in Gaming Mode, Stop and Next sent into gamescope's two X
  screens (XTest) were each seen once; not yet tried from a controller's Steam Input layout.
- **Calibrate says what to do.** A notification when it starts (take the glasses off and lay them down for 4
  seconds) and one with the result, even with Quick Access closed. His log had no calibration at all, and logs could
  not show which Quick Access panel was talking: now the log names the panel's version, the logs' info file does too,
  and a calibration asked for without glasses is logged. Built and checked by tests; the notifications are not yet
  seen on a Deck, as that Deck still has the 0.2.0 panel.
- **Pocket XR's pointer stays.** It hid after 3 seconds still, like gamescope's, but Pierre then saw only gamescope's
  arrow, which is out of line on a moved screen. Now it stays while the game shows a cursor. Checked by tests.

## 0.7.1 (22 Nov 2026)

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
