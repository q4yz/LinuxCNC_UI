# Remora HAL components

The generated HAL files load LinuxCNC components from the
[Remora-m8p](https://github.com/q4yz/Remora-m8p) fork (`LinuxCNC/Components`), compiled with
`halcompile` into LinuxCNC's module directory:

```bash
sudo bash scripts/install_hal_components.sh              # all
sudo bash scripts/install_hal_components.sh extruder     # only these
```

The script builds the newest commit of the fork's `main` (`REMORA_REF=<branch|tag>` for
another); `scripts/update.sh` says when the fork has new commits.

| Component | Used for |
|-----------|----------|
| `remora-spi`, `remora-eth-3.0` | the link to the Remora board |
| `PIDcontroller` | heater PID loops |
| `extruder` | the cold-extrusion guard (`min_extrude_temp`) |
| `remora-compensation` | bed mesh Z compensation (external offsets) |
| `rpi-monitor` | the host's CPU temperature and load |
| `remora-upload` | puts `config_<mcu>.txt` / `firmware.bin` on the board |

LinuxCNC stopping with *dlopen: …/<name>.so: cannot open shared object file* means that
component is not installed: run the script with its name.
