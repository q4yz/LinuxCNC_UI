# Remora HAL components

The generated HAL files load LinuxCNC components from the
[Remora-m8p](https://github.com/q4yz/Remora-m8p) fork (`LinuxCNC/Components`). They are
compiled with `halcompile` into LinuxCNC's module directory:

```bash
sudo bash scripts/install_hal_components.sh              # all
sudo bash scripts/install_hal_components.sh extruder     # only these
```

The script builds the newest commit of the fork's `main` branch (`REMORA_REF=<branch|tag>` to
pick another). `scripts/update.sh` tells you when the fork has new commits.

| Component | Used for |
|-----------|----------|
| `remora-spi`, `remora-eth-3.0` | the link to the Remora board (SPI, Ethernet) |
| `PIDcontroller` | heater PID loops |
| `extruder` | the cold-extrusion guard — {doc}`../configuration/heaters-extruder` |
| `remora-compensation` | bed mesh Z compensation |
| `rpi-monitor` | CPU temperature / load of the host |
| `remora-upload` | puts `config_mcu.txt` on the board at every LinuxCNC start |

If LinuxCNC stops with *dlopen: …/<name>.so: cannot open shared object file*, that component
is not installed: run the script with its name, then start LinuxCNC again.
