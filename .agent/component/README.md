# Component Templates — Compiler Contract

Each file in this folder defines ONE component that may appear in a
machine `.cfg`, in three (MCUs: four) fixed sections:

1. **INGESTION** — the hand-written `.cfg` block and its parameters.
2. **UI ABSTRACTION** — the `hardware.json` fragment it produces.
3. **COMPILATION** — the `machine.ini` / `machine.hal` /
   `webgui_connections.hal` it emits.
4. **PIN ROUTER** *(MCU templates only)* — how generic pin exports
   from other components get bound to this MCU's physical hardware.

This file holds what all of them share: the pin grammar, the MCU
capability classes, and the validation rules a compiler must enforce.

## Index

| File | Component | Notes |
|---|---|---|
| `template.md` | — | Blank skeleton for a new component. |
| `stepper.md` | `[stepper_<axis>]` | Axis / joint. Class A shown. |
| `exturder.md` | `[extruder]` | Heater + joint. (Filename is transposed.) |
| `heater.md` | `[heater_*]`, `[temperature_sensor]` | Bed / hot end. |
| `fan.md` | `[fan_*]` | Part, hot-end, controller, exhaust. |
| `analog_spindle.md` | `[spindle_analog]` | 0–10 V via `pwmgen`. Class A only. |
| `digital_spindle_rs485.md` | `[spindle_digital]` `protocol: vfdmod` | Modbus VFD. |
| `digital_spindle_ethercat.md` | `[spindle_digital]` `protocol: ethercat` | Fieldbus VFD. |
| `mcu_parallelport.md` | `[mcu]` `type: parallelport` | **Class A.** |
| `mcu_spi_remora.md` | `[mcu]` `type: remora-spi` | **Class B.** |
| `mcu_ethercat.md` | `[mcu]` `type: ethercat` | **Class B.** |
| `mcu_usb_arduino.md` | `[mcu]` `type: usb_arduino` | **Class C — I/O only.** |

Reference machines used to ground these: `machine_config/example/ender3/`
(Remora printer: heaters, extruder, PID) and
`machine_config/example/PrintNC-WEBGUI/` (parport router, stepgen,
estop chain).

---

## 1. Pin string grammar

Pin values are Klipper-style strings, since that is the source format
(`hardware.json.source = "KlipperToLinuxCNCCompiler"`):

```
[modifiers][<mcu_id>:]<pin_id>
```

| Part | Meaning |
|---|---|
| `!` | Invert the logic level. |
| `^` | Enable pull-up (input pins only). |
| `~` | Enable pull-down (input pins only). |
| `<mcu_id>:` | Which MCU block owns the pin. **Optional** — omitted means the MCU with `id: "mcu"`. |
| `<pin_id>` | The MCU-local pin name. Its shape is defined by the target MCU (`02` for parport, `PF13` for an STM32 running Remora, `din-0` for an EtherCAT slave). |

Examples: `!par0:02` → invert, mcu `par0`, pin `02`.
`^PC0` → pull-up, default mcu, pin `PC0`. `PE3` → default mcu, pin `PE3`.

**Parse order:** strip modifiers first (they may combine, e.g. `^!PC0`),
then split on the *first* `:`.

Modifiers are flags on the parsed pin, not part of `pin_id`:

```json
{ "raw": "^!PC0", "mcu_id": "mcu", "pin_id": "PC0", "invert": true, "pullup": true, "pulldown": false }
```

---

## 2. MCU capability classes

The MCU decides **how motion reaches the motor**, which in turn decides
what the stepper component is allowed to emit. This is the single most
important branch in the compiler.

| Class | Motion interface | MCUs | Consequences |
|---|---|---|---|
| **A — step/dir realtime** | LinuxCNC software `stepgen` makes pulses; the MCU is a dumb pin driver. | `parallelport` | Needs a `base-thread` (`BASE_PERIOD`). Stepper exports `<joint>-step` / `-dir` / `-enable` for the router to bind. |
| **B — position command** | The MCU/drive runs its own motion engine; LinuxCNC sends a position (or velocity) setpoint per servo cycle. | `remora-spi`, `ethercat` | **No `stepgen`, no `base-thread`.** `joint.N.motor-pos-cmd` is wired straight to the MCU's position pin. Physical step/dir pins live in the MCU's *own* config (Remora `config.txt`, EtherCAT slave XML) — they never appear as HAL nets. |
| **C — I/O only** | None. | `usb_arduino` | Must **reject** any joint/stepper pin. Only endstops, buttons, relays, lamps, non-critical sensors. Userspace latency: `servo-thread` only, never `base-thread`. |

A joint's `step_pin` / `dir_pin` therefore mean two different things
depending on the class it resolves to:

* Class A → a HAL net endpoint the router emits (`parport.0.pin-02-out`).
* Class B → a value copied into the MCU's firmware/slave config; the
  HAL side only ever sees `remora.joint.0.pos-cmd` / the CiA402 PDO.

---

## 3. Validation rules

A machine is valid only if all of these hold. Each rule names the error
a compiler should raise. These are the **global** rules; each component
template's § 4 adds its own local ones (`E_HEATER_ID_PREFIX`,
`E_EXTRUDER_NO_AXIS`, `E_MOTION_ON_IO_MCU`, …).

**Referential**

* `E_UNKNOWN_MCU` — every parsed `mcu_id` matches an `mcus[].id`.
* `E_NO_DEFAULT_MCU` — a pin omits `<mcu_id>:` but no MCU has `id: "mcu"`.
* `E_UNKNOWN_REF` — every `axes[].endstop`, `joints[].driver`,
  `tools[].sensor` and `tools[].fan` resolves to a declared id.
* `E_PIN_CONFLICT` — the same `(mcu_id, pin_id)` is claimed twice.

**Motion**

* `E_MOTION_ON_IO_MCU` — a joint pin resolves to a class C MCU.
* `E_MIXED_MOTION_CLASS` — joints resolve to MCUs of different classes.
  (One machine, one motion interface — mixing a parport stepgen joint
  with a Remora position joint is not supported.)
* `E_NO_BASE_THREAD` — a class A machine has no MCU that defines
  `BASE_PERIOD`.
* `E_JOINT_NUMBERING` — `joints[].joint_number` is not `0..n-1`
  contiguous; `[KINS] JOINTS` must equal the joint count.
* `E_AXIS_WITHOUT_JOINT` — an axis lists no `joint_numbers`.

**Ranges**

* `E_LIMITS` — `position_min < position_max`, and
  `position_min <= position_endstop <= position_max`.
* `E_RPM_RANGE` — `min_rpm < max_rpm` on every spindle.
* `E_TEMP_RANGE` — `min_temp < max_temp` on every heater.

**Spindle**

* `E_MULTIPLE_SPINDLES` — more than one tool drives `spindle.0`.
  Additional spindles need explicit `spindle.N` assignment and
  `[TRAJ] SPINDLES = N`.

---

## 4. Emission order (`machine.hal`)

HAL is order-sensitive: a `net` may not reference a pin whose component
has not been loaded, and `addf` order defines execution order within a
thread. Emit in this order:

1. `loadrt` kinematics + `motmod` (from `[KINS]` / `[EMCMOT]`).
2. `loadrt` the MCU driver(s) — class A also `loadrt stepgen`.
3. `loadusr -W` userspace components (`vfdmod`, `lcec_conf`, Arduino bridge).
   `-W` matters: it blocks until the component's pins exist.
4. `addf` — base-thread first (read → make-pulses → write → reset),
   then servo-thread (read → motion → write).
5. `setp` configuration.
6. `net` component-local wiring.
7. `net` router output (§4 of each MCU template) — always last, since it
   consumes signals every other component exported.

---

## 5. Conventions for signal names

Components must not invent per-MCU names; they export
hardware-agnostic signals that the router consumes:

| Signal | Direction | Exported by |
|---|---|---|
| `<joint_id>-step` | out of stepgen | stepper (class A only) |
| `<joint_id>-dir` | out of stepgen | stepper (class A only) |
| `<joint_id>-enable` | out of `joint.N.amp-enable-out` | stepper |
| `<axis_id>-home-sw` | into `joint.N.home-sw-in` | stepper |
| `spindle-forward` / `spindle-reverse` | out of `spindle.0.*` | spindle |
| `spindle-speed-cmd` | out of `spindle.0.speed-out` | spindle |
| `spindle-at-speed` | into `spindle.0.at-speed` | spindle |
| `estop-out` | out of `iocontrol.0.user-enable-out` | machine core |
| `estop-fault` | into `estop-latch.0.fault-in` | machine core |

`webgui.*` pins are the userspace UI component's surface — the
authoritative list is generated per machine into the `machine.hal`
template by `backend/system/services/machinetemplates/pin_catalog.py`.
Wire them in `webgui_connections.hal` only, never in `machine.hal`.
