# Pocket XR for the Steam Deck (prototype)

An early look at Pocket XR on the Steam Deck. Read [docs/FEASIBILITY.md](docs/FEASIBILITY.md) first.

## Run the prototype

On the Deck, in Desktop Mode, with the XREAL glasses plugged in:

1. In the glasses' own menu, turn **Spatial Anchor off**. It fights the app's head tracking.
2. Copy the `prototype` folder to the Deck.
3. In Konsole: `python3 prototype/deckxr.py`
4. Keep your head still for 2 seconds while the gyro settles.

Add `--capture` to show the Deck's own screen instead of the test card.

Keys: Enter, Space, R or a click recentres. Up and Down move the screen nearer or further.
Left and Right make it smaller or bigger. Escape or Q quits.

The prototype only reads the glasses' motion. It sends nothing to the glasses.

## Checks without glasses

`python3 prototype/test_offline.py`

## Licence

GPL-3.0, the same as Pocket XR.
