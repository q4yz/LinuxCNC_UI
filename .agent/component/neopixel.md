# Component: RGB LEDs (`[neopixel NAME]`)

> **Implemented status:** parser (`MachineConfigParser._parse_neopixel`),
> `hardware_json_generator` (`leds[]`), `LedHalMapper` / `LedWebguiMapper`,
> the Remora router's `PinRole.RGB` (firmware `"RGB"` module), validator
> `E_LED_*`, machine backend `LedService` + `/api/v1/leds`, `SET_LED` in
> MDI and `.macro` lines, uploads: `SET_LED` / `M150` -> `M183`
> (`core.gcode_converter`, helper `machine_config/m_codes/M183`), the
> dashboard's LED card (`LedPanel.vue`). Firmware: Remora-m8p `main`,
> `modules/rgb` (WS2812 / SK6812 on a timer channel + DMA, hub and CAN
> nodes, STM32G0). Tests: `backend/system/tests/test_neopixel.py`,
> `backend/machine/tests/test_leds.py`, `backend/common/tests/test_led_color.py`,
> `frontend/tests/test-led-panel.ts`.
>
> Not tested on hardware. Not supported: Klipper's `[dotstar]`, `[led]`,
> `[pca9632]`, `led_effect`; a separate white channel (see § 4).

## 1. INGESTION (Hand-Written CFG)

Klipper's `[neopixel]`, one extra key:

```cfg
[neopixel sb_leds]
pin: ebb:PD3            # the board's (or a CAN node's) LED data pin — a timer channel:
                        #   PA9, PB15 (M8P v1.1), PC6 (M8P v1.0), PD3 (EBB42 / SB2209)
chain_count: 3          # (Optional) LEDs, 1 ... 64, default 1
color_order: GRBW       # (Optional) R, G, B once each, W for RGBW chips; default GRB.
                        #   Klipper's per-LED list ("GRB, GRB") must name one order
initial_RED: 0.0        # (Optional) 0.0 ... 1.0, also _GREEN, _BLUE, _WHITE
initial_WHITE: 1.0
segments: 1, 2-3        # (Optional, not Klipper) LED groups, one colour each; default
                        #   one group, the whole chain
```

Why `segments`: a Remora board has **6 set points** (`remora.SP.N`, the
firmware's `VARIABLES`) for everything — heaters, fans, PWM outputs and
LED colours, its CAN nodes included. Every segment takes one. A
Stealthburner's logo + two nozzle LEDs is `segments: 1, 2-3` (two set
points); a whole case-light chain is one.

## 2. hardware.json

```json
"leds": [ { "id": "sb_leds", "pin": "ebb:PD3", "chain_count": 3, "color_order": "GRBW",
            "segments": [[1, 1], [2, 2]], "initial": [0.0, 0.0, 0.0, 1.0] } ]
```

## 3. COMPILATION

machine.hal — a set point per segment (the colour 0xRRGGBB as a float):

```hal
net sb_leds-rgb0 => remora.SP.4
net sb_leds-rgb1 => remora.SP.5
```

config_<mcu>.txt (in the node's entry for a CAN node pin) — one module per chain:

```json
{ "Name": "rgb_sb_leds", "Thread": "Servo", "Type": "RGB", "Comment": "sb_leds", "Pin": "PD_3",
  "Chain Count": 3, "Color Order": "GRBW",
  "Segments": [ { "First": 1, "Count": 1, "SP[i]": 4 }, { "First": 2, "Count": 2, "SP[i]": 5 } ] }
```

webgui_connections.hal — the machine backend writes each segment:

```hal
net sb_leds-rgb0 <= webgui.led-sb_leds-0
net sb_leds-rgb1 <= webgui.led-sb_leds-1
```

## 4. RUNTIME

* **Dashboard:** the LED card, a colour picker per segment, "Off" per chain.
* **MDI / `.macro` lines:** Klipper's
  `SET_LED LED=sb_leds RED=1 GREEN=0.5 BLUE=0 WHITE=0 INDEX=2`
  (`TRANSMIT` / `SYNC` accepted, every change is sent at once).
* **Uploaded prints:** `SET_LED …` and Marlin's
  `M150 R U B [W] [P<brightness>] [I<LED from 0>] [S<chain>]` become
  `M183 P<0xRRGGBB> Q<chain × 100 + LED>` (chain: the `[neopixel]` in
  declaration order of the active machine, LED from 1, 0 = all). Without
  LEDs a `M150` stays a user M-code as before.
* **API:** `GET /api/v1/leds`, `PUT /api/v1/leds/<id>` `{red, green, blue, white, index}`.

`INDEX` sets the **segment** that LED belongs to (a whole-chain segment:
every LED). `WHITE` is added to R, G and B: the firmware drives an RGBW
chip's white LED from the colour itself (W = min(R, G, B)), so white
lights the white LED. The chain is off while LinuxCNC is not connected;
`initial_*` is applied when the machine backend starts.

## 5. VALIDATION

| Error | When |
|---|---|
| `MissingRequiredKeywordError` | no `pin`. |
| `InvalidValueError` | `chain_count` outside 1 … 64; a bad / mixed `color_order`; `segments` not covering 1 … `chain_count` once each; an `initial_*` outside 0 … 1. |
| `UndefinedMcuError` | the pin's `mcu:` prefix names no `[mcu]`. |
| `E_LED_NOT_REMORA` | the pin is on an MCU that is no Remora board or node. |
| `E_LED_LIMIT` | a hub chain with more than 6 segments, more than 4 chains on a hub, or a CAN node with more than 2 chains / 4 segments. |
| `E_COMPILE` (set points) | more than 6 set points on one board, its nodes included. |
| `E_PIN_CONFLICT`, `E_IO_ID_CONFLICT` | the pin or the name is already used. |
