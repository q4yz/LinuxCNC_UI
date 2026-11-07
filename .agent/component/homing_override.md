# Component: Homing routine (`[homing_override]`)

> **Implemented status:** parser (`MachineConfigParser._parse_homing_override`),
> routine parser `backend/common/core/homing_routine.py` (shared),
> `hardware_json_generator._homing_override_payload` (axis checks),
> `ini_template_generator` (`NO_FORCE_HOMING`), machine backend
> `HomingRoutineService` (runner + program guard), hooked into
> `AxisService.home_single_axes`. Tests:
> `backend/system/tests/test_homing_override.py`,
> `backend/machine/tests/test_homing_routine.py`.

A homing sequence of your own — e.g. lift Z clear, home X and Y, move
to the bed centre, home Z there (a probe as Z endstop). Klipper's
`[homing_override]`, same syntax.

## 1. INGESTION (Hand-Written CFG)

```cfg
[homing_override]
axes: xyz            # (optional) axes whose home button runs it; default: every axis
gcode:
    G91
    G0 Z5            ; lift 5 mm (works unhomed)
    G90
    G28 X            ; home X
    G28 Y
    G53 G0 X100 Y100 ; centre, in machine coordinates
    G28 Z
```

* `G28 <axes>` **homes** those axes (Klipper's meaning, not LinuxCNC's
  "go to the G28 position"); values are ignored (`G28 X0` = `G28 X`).
  A bare `G28` homes every joint by the INI's `HOME_SEQUENCE`. A `G28`
  line carries nothing else. `G28.1` etc. are ordinary MDI.
* Every other line is sent as **MDI**, one at a time, each waiting until
  it is finished. Modal state (`G91`, `#<_globals>`) carries over from
  line to line; a single-line `o<sub> call` works, O-word loops or
  branches spread over several lines do not.
* The extruder is an axis too (`a`), without a switch
  (`HOME_SEARCH_VEL = 0`, `exturder.md` § 3). The routine needs no
  `G28 A`: every such axis it leaves unhomed (`home_in_place`) is homed
  in place, without moving, after the last line.

## 2. hardware.json

```json
"homing_override": { "gcode": "G91\nG0 Z5\nG90\nG28 X\nG28 Y\nG53 G0 X100 Y100\nG28 Z", "axes": "xyz", "home_in_place": ["a"] }
```

`axes` is filled with every axis that has a `[stepper_*]` when the
section names none; `home_in_place` lists the switch-less axes (the
extruder) the routine does not home itself.

## 3. COMPILATION

machine.ini `[TRAJ]`: `NO_FORCE_HOMING = 1` — LinuxCNC refuses MDI
before every joint is homed otherwise, so the routine's first move would
fail. With it LinuxCNC also starts programs unhomed, so the UI refuses
`program/run` with 409 "Home the machine first" until every joint is
homed (`HomingRoutineService.require_homed`). No HAL.

## 4. RUNTIME

LinuxCNC cannot home from G-code (homing needs MANUAL mode, a program
runs in AUTO), so the machine backend runs the routine on a worker
thread (one at a time, not while a macro runs):

* "Home all", and the home button of any axis in `axes`, start it; the
  request returns at once. Other axes home directly as before.
* `G28 X`: MANUAL mode, joint mode, `home(<first joint of X>)` (a
  gantry's twin joints follow through their shared negative
  `HOME_SEQUENCE`), wait until every joint of X is homed.
* It stops at the first failure — E-stop, machine off, a line LinuxCNC
  refuses, someone leaving MDI mode, a joint that stops homing without
  being homed (switch not reached), 180 s per home step — and logs the
  line and the reason in the console. It ends in MANUAL mode.

## 5. VALIDATION

| Error | When |
|---|---|
| `MissingRequiredKeywordError` | no `gcode`. |
| `InvalidValueError` (`gcode`) | a `G28` line with other commands; a `G28` of an axis the machine does not have; an axis in `axes` the routine never homes. |
| `InvalidValueError` (`axes`) | not axis letters, or an axis the machine does not have. |
