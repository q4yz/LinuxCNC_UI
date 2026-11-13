# Adding a toolhead board

A toolhead board (BTT EBB42, SB2209, …) on CAN carries the hotend, the part fan, the probe and
LEDs, so only four wires go to the toolhead. It runs Remora too and talks to the main board
(the CAN *hub*).

:::{admonition} Placeholder
:class: warning
Supported toolhead boards and the firmware file for each — to be added.
:::

## 1. Download the firmware

Get the toolhead `firmware.bin` for your board from the
[Remora-m8p repository](https://github.com/q4yz/Remora-m8p) *(placeholder: download link)*.

## 2. Flash it in DFU mode

1. Connect the board to the host (or a PC) with USB.
2. Hold the **BOOT** button, press and release **RESET**, release BOOT — the board is now in
   DFU mode (`lsusb` shows `0483:df11 STMicroelectronics … DFU Mode`).
3. Flash:

   ```bash
   sudo dfu-util -a 0 -d 0483:df11 --dfuse-address 0x08000000:leave -D firmware.bin
   ```

   *(placeholder: the flash address per board, if it differs)*
4. Disconnect USB, wire CAN (see {doc}`wiring`) and set the termination jumper at the end of
   the bus.

## 3. Add it to the config

The main board's debug console prints the toolhead's UUID. Add the node to the config and use
its pins with its name as prefix (`toolhead:PB9`):

```ini
[mcu toolhead]
connection: remora-can
canbus_uuid: 0e0d81e4210c
```

See [mcu] in {doc}`config-reference`.
