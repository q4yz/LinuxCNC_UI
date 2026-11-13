# Troubleshooting

## The UI shows the machine offline

- **LinuxCNC is not running** — the machine backend (port 8000) only answers while it does.
  The console says so.
- **E-stop / CAN fault** — a missing CAN node keeps the machine in E-stop; heaters and fans
  stay off.
- **The machine backend hangs** (port 8000 accepts nothing, `ss -ltn` shows a growing
  Recv-Q) — fixed since the HAL pin list reads `halcmd` through a file. On an older version,
  do **not** kill a hanging `halcmd`: it would leave HAL locked until LinuxCNC restarts. Drain
  its output instead:

  ```bash
  ls -l /proc/<backend-pid>/fd | grep pipe          # the read end of halcmd's output
  timeout 20 cat /proc/<backend-pid>/fd/<fd> > /dev/null
  ```

## "Unknown m code used: M106"

The Marlin M-codes are user M-code programs in `machine_config/m_codes/` (`M104`, `M106`, …).
Check they exist and are executable (`ls -l machine_config/m_codes/M1*`), that the INI's
`[RS274NGC] USER_M_PATH` points there, and restart LinuxCNC — `USER_M_PATH` is only read at
start. In the console, `S` works (`M106 S128`); it is converted to `P`.

## "extrude below minimum temp"

The cold-extrusion guard stopped an extruder move: heat the hotend above `min_extrude_temp`
first ({doc}`../getting-started/config-reference`).

## "Probe move would exceed Z's negative limit"

The probe did not trigger before Z's lower limit (`[stepper_z] position_min`). Check the probe
(pin, `!`), start higher, or lower `position_min` if the bed really is lower.

## LinuxCNC stops at a `loadrt`

*cannot open shared object file* — a Remora component is missing:
{doc}`../architecture/remora-components`.
