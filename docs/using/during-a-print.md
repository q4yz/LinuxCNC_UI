# During a print

While a print runs (or is paused), the **Job status** card shows the controls below. They are
also commands for the console, macros and the slicer's G-code.

## Live Z offset (babystepping)

Move the nozzle closer to or further from the bed while the first layer goes down: the
**−0.05 −0.01 +0.01 +0.05** buttons (mm, + = up), **0** resets it. In the console or G-code:

```text
SET_GCODE_OFFSET Z_ADJUST=-0.02     ; change by
SET_GCODE_OFFSET Z=0.1              ; set
```

The offset is added to Z's external offset in HAL (together with the bed mesh), at most ±2 mm,
and stays until you change it or restart. Use it to find the right first layer, then put the
difference into `[probe] z_offset` (or `PROBE_CALIBRATE` again).

## Flow

The extrusion in percent — less for over-extrusion, more for gaps: the **Flow** box on the card,
or `M221 S95` (console, G-code). It scales the extruder's moves in the Remora `extruder` HAL
component from the next move on, without a jump. Remora boards only; it stays until changed.

## Excluding an object

When one part of a multi-part print fails, press **Exclude** next to it: the remaining parts
carry on, the excluded one is no longer printed. The slicer must label the objects:

- **OrcaSlicer / PrusaSlicer** — *Print settings → Output → Label objects* (and *Exclude
  objects* for Klipper-style labels).
- **Cura** — labels every object by itself (`;MESH:` comments).

It takes effect for the parts LinuxCNC has not read ahead yet — a few seconds. At most 32 objects
per file. Upload the file after updating, so the converter can mark the objects.

## Filament change (M600)

`M600` in the G-code (the slicer's *filament change* at a layer, or typed in the console):

1. Retracts, lifts Z, moves to the park position and unloads the filament.
2. Pauses — the card shows *Paused*. Put in the new filament.
3. **Resume**: loads, purges, goes back and carries on.

Lengths, speeds and the park position are `[filament_change]` in the profile
({doc}`../getting-started/config-reference`).

## Firmware retraction (G10 / G11)

With *Use firmware retraction* in the slicer, the slicer writes `G10` / `G11` instead of its
own retraction moves. The upload turns them into the `[firmware_retraction]` moves of the
profile — set the lengths and speeds there. (In LinuxCNC `G10` with `L` sets offsets; those
lines stay as they are.)

## Progress and time left

If the slicer writes progress (`M73 P<percent> R<minutes>` — OrcaSlicer, PrusaSlicer, Bambu
profiles do), the card shows the slicer's percentage and time left under *Slicer*.
