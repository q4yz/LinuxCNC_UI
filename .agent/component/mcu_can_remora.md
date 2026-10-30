# MCU: Remora CAN node (`remora-can`)

> **Implemented status:** CAN expansion phase 2 of the Remora-m8p fork
> (`Firmware/FirmwareSource/Remora-OS6/TARGET_STM32G0/drivers/can/CAN_PROTOCOL.md`):
> a node (BTT EBB42 ...) behind a `remora-spi` hub (Manta M8P) carries
> **Digital Pin** inputs / outputs only. Code: `RemoraCanMapper`
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

Node pins: endstops (`endstop_pin: toolhead:^PB9`) and `[estop]
fault_pin` / `out_pin`. Anything else on a node is
`E_CAN_NODE_PIN` — heaters, fans, sensors and stepgen are later firmware
phases, and the few-ms CAN latency rules out a touch probe.

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
get `"Lost State": "Low"`. Digital inputs skip the status bit.

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
1 ... 15, at most 15 per hub), `E_CAN_NODE_PIN`; more than 16 digital
inputs or outputs on one hub (nodes included) fails the compile.
