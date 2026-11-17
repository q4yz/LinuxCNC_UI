# Dashboard and page layout

The **Dashboard** and the **Running** page show panels in columns. Which panels, in which column
and order, is a setting: **Settings → Page layout**, per page. Changes save at once and are shared
by every browser.

- **1 column / 2 columns / 3 columns** (the tabs at the top): each page has all three layouts,
  each switched on or off with its checkbox (the last one on stays on). The page uses the
  widest layout that is on and still gives every column at least 420 px; the editor says from
  which page width a layout is used. When none fits, the narrowest one that is on is used and
  its columns wrap one below the other (switch *1 column* off to get that).
- **Column widths** are twelfths, like a browser grid: − / + on a column takes from or gives to
  its neighbour.
- **The round + button** in the corner adds a panel at the end of the first column. A panel can
  be added more than once.
- **Drag** a panel to order it or move it to another column; drop it on the bin that appears
  while dragging to remove it. With a mouse drag the whole card, with a finger its grip (⠿), so
  the page still scrolls by touch.

A layout saved by an earlier version becomes the two-column layout (and one column with both in
a row); three columns starts off.

| Panel | Shows |
|-------|-------|
| Machine (power) | machine state, E-STOP, POWER, RESET MCU |
| DRO | positions, homed state, Home all, macro buttons per axis |
| Jog controls | jog buttons and speed — {doc}`jogging` |
| Probing | probing cycles: edges, corners, bore / boss and pocket / block centres into a work offset; the probe's tip diameter and search feed are **Settings → Probing** |
| Tools | extruder, spindle and heater controls |
| Temperatures | readings, targets, chart |
| I/O | fans, output and input pins |
| LEDs | `[neopixel]` colours |
| Job status | the loaded program, start / pause / stop, progress |
| Axis speed | speed multiplier (feed override), max speed |
| Console | log and MDI — {doc}`console-commands` |
| Camera | the camera stream |
| Macros & NGC, M-Codes | run macros / user M-codes |

Machine panels only appear while the machine backend is reachable (LinuxCNC running); the
console always shows — it explains why the machine is offline.

Both pages stay loaded in the background: a panel placed on both — or twice on one page — runs
that many times (for the camera, that many streams).

## Custom buttons

**Settings → Macro Buttons**: a button next to each DRO axis row and in the bottom-left corner of
the toolpath viewer and the camera view. Each has a name, an icon (an icon name or any text /
emoji) and a kind:

- **macro** / **ngc** — runs that macro or NGC program (not in E-stop, not while one runs).
- **UI component** — opens a panel (any the Dashboard can show) in a window: drag it by its
  title bar, close it with the ×; clicking the button again brings the open window to the front.
  A window shows the same panel as the Dashboard (a camera there and in a window streams twice).

Leave the macro / component empty to hide the button.

## The E-stop

The **STOP** button is always in the top-right corner, over the page. A card row that passes
under it moves its buttons left so nothing is covered.

## Temperatures

- The unit (°C, °F, K) is a setting: **Settings → Temperature**. A target typed in °F or K is
  converted; the machine always works in °C.
- **Cool all** in the card header switches every heater off.
- The eye button hides a sensor from the chart.
