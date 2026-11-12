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

The prototype only reads the glasses' motion. It sends nothing to the glasses.

## Checks without glasses

`python3 prototype/test_offline.py`

## Licence

GPL-3.0, the same as Pocket XR.
