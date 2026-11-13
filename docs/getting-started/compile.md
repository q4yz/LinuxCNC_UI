# Compile

**Generating** turns your profile into the files LinuxCNC runs. Do it after every change to the
profile, then restart LinuxCNC.

## Generate

1. Open the **Config** page. The *Profiles* list holds your `.cfg` files: create one, upload one
   or edit it in place.
2. Press **Generate** on the profile. The generated machine appears in the *Machines* list.
3. If something is wrong, the profile is marked with its problems (*Generate failed*): each
   names the section and key — an unknown key, a missing pin, a pin used twice, a value out of
   range. Fix the profile and generate again.

Every generated file is rewritten each time — change the profile, not the generated files:

| File | Content |
|------|---------|
| `machine.cfg` | a copy of the profile |
| `hardware.json` | the machine as the UI sees it |
| `machine.ini` | LinuxCNC's INI: joints, axes, limits, homing, heater loops |
| `machine.hal` | the HAL wiring: motion, steppers, heaters, probe, components |
| `webgui_connections.hal` | the UI's HAL pins |
| `config_<mcu>.txt` | the Remora board's configuration, put on the board at every start |

## Choose as main

In the *Machines* list:

Set main
: Makes this machine the **main** (default) machine: the one the UI shows and LinuxCNC starts
  with.

Start
: Sets it as main and starts LinuxCNC with its `machine.ini`.

## First start

Check the basics before anything moves: E-stop and power, each axis's direction with a short
jog, every endstop, then homing. Next: {doc}`../using/dashboard`.
