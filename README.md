# Pocket XR for Steam Deck

Your Steam Deck's screen and apps on your XR glasses, held still in space as you turn your head. On the
XREAL Aura, the glasses can hold them in place as you move around too.

It is the Steam Deck version of [Pocket XR](https://github.com/pocket-xr/pocket-xr), the free and open
source spatial desktop for Android phones. Same glasses, same rules, no account and no paid tier.

**Early version.** It runs in Desktop Mode. Gaming Mode is not supported yet.

## Install

On the Deck, switch to Desktop Mode, open Konsole and paste:

```bash
curl -L https://github.com/pocket-xr/pocket-xr-deck/releases/latest/download/pocket-xr-deck.tar.gz | tar xz -C /tmp && /tmp/pocket-xr-deck/install.sh
```

Pocket XR then appears on the desktop and in the app menu. No password is needed. It installs into your home
folder, so SteamOS updates leave it alone. Run the same line again to update.

To remove it: `~/.local/share/pocket-xr-deck/uninstall.sh`

## Use

1. Plug your glasses into the Deck's USB-C port.
2. Open **Pocket XR**. Your glasses show the Deck's screen in front of you. A control panel opens on the Deck.
3. Hold still for a moment now and then. The head tracking learns its zero point while you are still.

The control panel:

- **View**
  - **Window in space**: the screen stays where it is while you turn your head.
  - **Steady 6DoF**: the glasses hold the picture in place as you lean and walk around (see below).
- **Show**
  - **Deck screen**: the whole Deck screen as one window.
  - **App windows**: each open app as its own window, side by side around you.
- **Adjust**: Recentre, Smaller and Bigger, Nearer and Further.
- **Look at a window to bring it to the front.** In App windows, look at a window for a moment and it comes to
  the front on the Deck's screen, so touch, the trackpads and the keyboard work on it.
- **Quit and put the glasses back.** Every setting Pocket XR changed on the glasses is put back as it was.

The Deck's back buttons work at any time, alongside Steam's controls:

| Button | Tap | Hold |
| --- | --- | --- |
| L4 | Recentre | Switch between Window in space and Steady 6DoF |
| R4 | Next app window | Switch between Deck screen and App windows |
| L5 | Launcher | Lock screens |
| R5 | Control Center | Adjust all |

Holding the pointer against the right edge of the Deck's screen for a second also recentres.

The mouse pointer is drawn in the glasses on the window it is over. It stays on the Deck's screen: past its right
edge you could not see or use it.

## Glasses

The same glasses as Pocket XR on Android:

| Glasses | Head tracking | Steady mode in 6DoF | Tested on a Deck |
| --- | --- | --- | --- |
| XREAL Aura | Yes | Yes. Pocket XR turns the Aura's Spatial Anchor on and off for you. | Yes |
| XREAL One, One Pro, One Pro+, 1S | Yes | With the XREAL Eye. You turn 6DoF on in the glasses' menu when asked. | Not yet |
| XREAL Air, Air 2, Air 2 Pro, Air 2 Ultra | Yes | No | Not yet |
| VITURE Beast | Yes | No (waits on VITURE's SDK) | Not yet |
| Other VITURE glasses | Experimental, off until you turn it on in the panel | No | Not yet |
| Other glasses | No, the windows are shown flat | No | Not yet |

Settings on the glasses themselves, as on Android:

- **XREAL Aura:** nothing to do. Pocket XR turns Spatial Anchor off in Window in space, and on in Steady 6DoF.
- **XREAL One series:** use **Follow** mode and turn **Stabilizer off** in the glasses' menu. Otherwise the glasses
  and Pocket XR both move the picture.

**A "KDE Wallet" window pops up when you plug in the glasses?** KDE asks its wallet for network passwords each time
the glasses' USB network appears. Pocket XR doesn't need it. To stop it: System Settings, KDE Wallet, untick
"Enable the KDE wallet subsystem".

If your glasses are on the list but don't work, please open an issue with the log from
`~/.local/state/pocket-xr-deck/pocket-xr.log`.

## What it sends to the glasses

Pocket XR reads the glasses' motion. It sends a setting only on XREAL glasses with a control link (the Aura and the
One series), and only the commands Pocket XR on Android has already proven: 2D and 3D, Ultrawide, screen size,
Spatial Anchor and the canvas recentre. It never sends a firmware command or a guessed one. On the Air and VITURE
glasses it sends only the start and stop of the motion stream.

## Build and test

```bash
python3 tests/test_offline.py   # checks that need no glasses or screen
./make-release.sh               # dist/pocket-xr-deck.tar.gz
```

`docs/FEASIBILITY.md` covers why the Deck version is built this way, how it compares to Breezy Desktop, and the test
results on a real Deck.

## Licence

GPL-3.0, the same as Pocket XR. The glasses' protocols are written in our own words from Pocket XR's notes, which
credit the public, MIT licensed write-ups they come from.

The font is Inter 4.1, Copyright (c) 2016 The Inter Project Authors (https://github.com/rsms/inter), under the SIL
Open Font License 1.1 (https://openfontlicense.org): `assets/fonts/` holds its static Regular and Medium files,
unmodified, as Pocket XR on Android bundles them.
