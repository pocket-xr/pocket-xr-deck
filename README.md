# Pocket XR for the Steam Deck (prototype)

An early look at Pocket XR on the Steam Deck. Read [docs/FEASIBILITY.md](docs/FEASIBILITY.md) first.

## Run the prototype

On the Deck, in Desktop Mode, with the XREAL glasses plugged in:

1. In the glasses' own menu, turn **Spatial Anchor off**. It fights the app's head tracking.
2. Copy the `prototype` folder to the Deck.
3. In Konsole: `./prototype/run.sh`. From SSH use `./prototype/start.sh`, which keeps it running
   after SSH closes.
4. Hold still for a moment now and then. The gyro learns its zero from quiet half seconds.

Add `--capture` to show the Deck's own screen instead of the test card. The pointer is drawn in
the glasses and kept on the Deck's screen; hold it at the right edge for a second to recentre.

Keys: Enter, Space, R or a click recentres. Up and Down move the screen nearer or further.
Left and Right make it smaller or bigger. Ctrl+Q quits.

### Steady mode in 6DoF (XREAL Aura)

The glasses hold the picture in the room as you move, as Pocket XR's Steady mode does on the phone.

1. `python3 prototype/steady.py on` (2D, Ultrawide, largest size, then Spatial Anchor on)
2. `./prototype/start.sh --capture --canvas`
3. To leave: `python3 prototype/steady.py off`, then start without `--canvas`.

`python3 prototype/steady.py status` reads the glasses' settings and changes nothing.

Only `steady.py` sends anything to the glasses, and only commands Pocket XR has proven on the Aura.
The 3DoF view only reads the glasses' motion.

## Checks without glasses

`python3 prototype/test_offline.py`

## Licence

GPL-3.0, the same as Pocket XR.
