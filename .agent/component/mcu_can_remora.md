# MCU: Remora CAN node (`remora-can`)

> **Implemented status:** CAN expansion phase 2 of the Remora-m8p fork
> (`Firmware/FirmwareSource/Remora-OS6/TARGET_STM32G0/drivers/can/CAN_PROTOCOL.md`):
> a node (BTT EBB42 ...) behind a `remora-spi` hub (Manta M8P) carries
> **Digital Pin** inputs / outputs and up to two **joints** (Stepgen). Code: `RemoraCanMapper`
> (`backend/system/services/halcompiler/mcus/RemoraCanMapper.py`), routing
> in `HalAssembler`, E-stop wiring in `RemoraRouterMapper.base_fragment`,
> rules in `MachineValidator._check_can`. Tests: `test_remora_can.py`.

## 1. INGESTION (Hand-Written CFG)

```cfg
[mcu]                         // the hub — a normal remora-spi MCU
connection: remora-spi
can_bitrate: 1000000          // (Optional) CAN bit rate, default 1000000
can_status_bit: 15            // (Optional) LinuxCNC input bit that is 1 only while every
                              // mandatory node runs; default 15 once a node is mandatory

[mcu toolhead]                // a node — pins on it: toolhead:PB9
connection: remora-can
canbus_uuid: 0e0d81e4210c     // required: 12 hex digits, printed by the hub's debug console
can_node: 1                   // (Optional) 1 ... 15, default: next free in declaration order
can_hub: mcu                  // (Optional) default: the machine's only remora-spi MCU
mandatory: true               // (Optional) default true: losing the node means E-stop
```

Node pins: endstops (`endstop_pin: toolhead:^PB9`), `[estop]
fault_pin` / `out_pin`, a joint's `step_pin` / `dir_pin` /
`enable_pin` (`[extruder] step_pin: toolhead:PD0`), a `[tmc2209 ...]
uart_pin` (at most 2 per node), a `heater_pin` and a `sensor_pin` (NTC
thermistors with a known beta curve, e.g. `Generic 3950` — no PT1000; at
most 4 per node). Anything else on a node is `E_CAN_NODE_PIN` — fans need
the node PWM output of a later firmware phase, and the few-ms CAN
latency rules out a touch probe.

Heater on a node: there is no PWM on a node yet, so the heater pin is a
Digital Pin output that a slow `pwmgen` (1 Hz, `scale 100` for the PID's
0 ... 100 %) pulses in the servo thread — plenty for a heater's thermal
mass. The node drives it Low as soon as it loses the hub or LinuxCNC.

```hal
loadrt pwmgen output_type=0
net heater_extruder-heater-SP => pwmgen.0.value
net heater_extruder-heater-SP-pulse <= pwmgen.0.pwm
net heater_extruder-heater-SP-pulse => remora.output.00
```

Thermistor on a node: a `"Temperature"` module with the next free PV
number (shared with the hub, `remora.PV.N`); the node reports 999 when
the sensor is open / shorted or the node is lost, and the PID turns the
heater off.

Joints on a node: at most 2 per node, every pin of the joint on that
node (`E_CAN_NODE_JOINT`). The position reaches LinuxCNC one servo
period (~1 ms) later than a local joint's, so the following error grows
by speed × 1 ms — `FERROR` may need a little more room. Each node with
joints uses about a quarter of the CAN bus.

## 2. hardware.json

The keys above, flat on the MCU record, present only when declared.

## 3. COMPILATION

A node has no SD card and LinuxCNC only sees the hub: the node's
requests route through the **hub's** `RemoraRouterMapper` (one 16-bit
input / output space — `remora.input.NN` / `remora.output.NN`), and the
finished modules move into the hub's `config_<hub>.txt`:

```json
"CAN": { "Bitrate": 1000000, "Status Bit": 15,
         "Nodes": [ { "UUID": "0e0d81e4210c", "Node": 1, "Comment": "toolhead",
                      "Mandatory": "True",
                      "Modules": [ { "Type": "Digital Pin", "Pin": "PB_9", "Modifier": "Pull Up",
                                     "Mode": "Input", "Data Bit": 0, "Lost State": "Low" } ] } ] }
```

Node dialect: pull-up is `"Modifier": "Pull Up"` (no `^` prefix), inputs
get `"Lost State": "Low"`. Digital inputs skip the status bit. A joint is
a `"Stepgen"` with the machine's joint number (LinuxCNC still sees
`remora.joint.N` on the hub), no `"Name"` / `"Thread"`:

```json
{ "Type": "Stepgen", "Comment": "extruder", "Joint Number": 3,
  "Step Pin": "PD_0", "Direction Pin": "PD_1", "Enable Pin": "PD_2" }
```

A TMC2209 or a Temperature is the local module without `"Name"` /
`"Thread"` (no node module carries those); the node configures the
driver over its own UART.

**Fallback levels are fixed, never configurable:** every output's `Safe
State` (LinuxCNC / hub gone) and every node input's `Lost State` (node
gone) is Low. The machine must be safe at Low — design the wiring for it
(an inverted `!pin` is still physically Low).

E-stop: the status bit's inverted twin is a fault into the hub's
`estop_latch` (`ok-in` = SPI link), ORed with a physical `fault_pin`
when there is one:

```hal
loadrt estop_latch
loadrt or2 names=estop-fault-or            # only with a fault_pin too
net remora-status <= remora.SPI-status => estop-latch.0.ok-in
net can-fault <= remora.input.15.not
net estop-fault => estop-fault-or.in0      # without fault_pin:
net can-fault => estop-fault-or.in1        #   net can-fault => estop-latch.0.fault-in
net estop-fault-any <= estop-fault-or.out => estop-latch.0.fault-in
net estop-ext <= estop-latch.0.ok-out => iocontrol.0.emc-enable-in
```

LinuxCNC cannot leave E-stop until every mandatory node runs, and a lost
node latches E-stop until the operator resets. Optional nodes
(`mandatory: false`) only switch their inputs to Low; with no
mandatory node there is no status bit unless `can_status_bit` is declared.

## 4. RULES

`E_CAN_NO_HUB`, `E_CAN_DUPLICATE_UUID`, `E_CAN_NODE_NUMBER` (unique,
1 ... 15, at most 15 per hub), `E_CAN_NODE_PIN`, `E_CAN_NODE_JOINT`; more than 16 digital
inputs or outputs on one hub (nodes included) fails the compile.
