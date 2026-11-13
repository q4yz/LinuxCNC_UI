# Jogging

The **Jog controls** card has to be active before it jogs: the **first** click (or Tab, or
Numpad 5) highlights it — a blue frame and *Active* — and only then do the buttons and keys
move the machine. Clicking elsewhere, or leaving the browser window, deactivates it and stops
any jog.

| Keys | Axis |
|------|------|
| ← → / Numpad 4 6 | X |
| ↑ ↓ / Numpad 8 2 | Y |
| Page Up / Down / Numpad 9 3 | Z |
| + / − | jog speed |

A button or key jogs while it is held. The speed slider is logarithmic; it starts at the
fastest axis's limit (at most 500 mm/s).

Jogging is refused while a program runs (state *Running*); a jog in progress stops when a
program starts.
