# ACE Pro (multi-colour)

The Anycubic **ACE Pro** (the original, USB) feeds up to four filaments. The machine backend
talks to it over USB; a tool change in a print (`T0` … `T3` from the slicer) parks, cuts,
swaps the filament and purges.

## Wiring

- **ACE → Pi:** the ACE's 4-pin Molex: pin 2 GND, pin 3 USB D−, pin 4 USB D+ to a USB cable;
  **leave pin 1 (3.5 V) unconnected**. The ACE has its own mains supply. Check with a meter.
  On the Pi it appears as `/dev/serial/by-id/usb-ANYCUBIC_ACE_1-if00` (check with
  `ls /dev/serial/by-id/` and `lsusb`).
- **Filament sensors** (switches that close when filament is there), each on a free input of a
  Remora board:
  - **toolhead sensor** (required): right before the extruder gears;
  - **hub sensor** (optional): where the four lanes join, or at the ACE's outlet.
- **Cutter** (strongly recommended): a lever at the toolhead that cuts the filament when the
  head moves against a fixed post. Without one the filament is pulled back as it is; that
  needs a clean tip and fails more often.

## Configuration

```ini
[input_pin toolhead_filament]
pin: ^PG11

[input_pin ace_hub]
pin: ^PG12

[ace]
toolhead_sensor: toolhead_filament
hub_sensor: ace_hub
# serial: /dev/serial/by-id/usb-ANYCUBIC_ACE_1-if00
bowden_length: 1000          # ACE outlet -> toolhead sensor (mm)
approach_length: 100         # the last part of it, fed slowly until the sensor triggers
feed_speed: 25               # mm/s
retract_speed: 25
# unload_length: 1050        # wound back after the cut (default bowden_length + 50)
park_x: 0                    # where it purges (machine coordinates; default X / Y minimum)
park_y: 0
z_lift: 5
cutter_start_x: 250          # the cut: from start to end and back (machine coordinates)
cutter_start_y: 10
cutter_end_x: 265
cutter_end_y: 10
cutter_speed: 50
cut_retract: 30              # after the cut: pull the rest out of the extruder gears
sensor_to_nozzle: 60         # toolhead sensor -> nozzle (mm)
load_speed: 5
purge_length: 40
purge_speed: 3
timeout: 180                 # s a change may take before the print pauses
```

Regenerate the machine. It gets `REMAP=M640` (`machine_config/m_codes/ace_change.ngc`) and the
hand-over between the program and the backend in HAL.

## A tool change

1. The slicer's `T<n>` becomes **`M640 P<n>`** when the file is uploaded (LinuxCNC's own `T0`
   means "no tool").
2. The head lifts, cuts, pulls the rest out of the gears and parks.
3. The backend winds the old filament back (until the sensors are clear), feeds the new one
   fast, then slowly until the **toolhead sensor** triggers, and turns feed assist on.
4. The extruder pushes it to the nozzle and purges; the print goes on.

If a step fails (empty slot, jam, filament still at a sensor, the ACE not answering) the print
**pauses** with a message in the console. Fix it and press **Resume**: the change runs again.
If you took filament out or put it in by hand, tell the backend which slot is loaded
(`PUT /api/v1/ace/current`, or the ACE card once it exists).

In the slicer, set four extruders/filaments and a **prime tower** (it cleans the nozzle after
the change; the purge here only pushes out the cut piece).

## Commands

Console / MDI: `T2` or `ACE_CHANGE_TOOL TOOL=2` (a tool change, `M640 P2`; `P-1` unloads),
`ACE_FEED INDEX=0 LENGTH=50 SPEED=20`, `ACE_RETRACT INDEX=0 LENGTH=50`,
`ACE_START_DRYING TEMP=50 DURATION=240`, `ACE_STOP_DRYING`.

## First test with a new ACE

With the backends **stopped** (one program per port):

```
cd backend/machine
PYTHONPATH=../common python -m services.filament.ace.probe /dev/serial/by-id/usb-ANYCUBIC_ACE_1-if00
```

It prints model, firmware, the slots (material, colour) and the dryer. Then try small moves:
`--feed 1 --length 20`, `--unwind 1 --length 20`. Without an ACE (no HAL, or
`LINUXCNC_UI_ACE_SIM=1`) the backend runs a simulated one.
