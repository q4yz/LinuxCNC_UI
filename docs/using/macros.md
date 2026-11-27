# Macros

Macros live in the `macros/` folder (Config → Macros & NGC; edit them in the editor). Start
them from the **Macros & NGC** card, a macro button, or the console.

| Kind | What it is | Runs |
|------|-----------|------|
| `.macro` | G-code lines, sent through MDI one after the other | machine ON |
| `.ngc` | a LinuxCNC subroutine (`o<name> sub`), called with arguments | machine ON |
| `.py` | **Python**: `run(m)` with loops, conditions, waiting, HAL pins | any time; only `m.mdi()` needs the machine ON |

## Python macros

```python
def run(m):
    m.console("Warming up")
    m.heater("extruder", 210)
    m.hal.set("webgui.enclosure-light", True)
    m.wait_until(lambda: m.temp("extruder") > 200, timeout=300)
    m.mdi("G28")                       # moves go through MDI
    for x in (10, 50, 90):
        m.mdi(f"G0 X{x} F3000")
```

A Python macro runs in **its own process**: **Stop** (on the card) or the **E-stop** ends it at
once — also in an endless loop — and aborts a move it started. A crash only ends the macro.

### What `m` can do

| Call | |
|------|---|
| `m.mdi("G0 X10")` | one MDI line, waits until it finished (`timeout=` s, default 600). The UI's own commands work too: `G28` (homing routine), `SET_LED`, `ACE_FEED`, `T1` with an ACE, ... Needs the machine ON. |
| `m.hal.get("pin")` | a HAL pin's or signal's value |
| `m.hal.set("pin", value)` | set a pin nothing else drives: the UI's `webgui.*` pins, an unconnected input, a signal without a writer (HAL allows one writer per signal) |
| `m.heater("extruder", 210)` | a heater's target (°C), 0 = off |
| `m.temp("extruder")` | a heater / sensor's temperature |
| `m.state()` | `estop`, `on`, `homed`, `position`, `program`, `temperatures` |
| `m.wait_until(fn, timeout=60)` | wait until `fn()` is true |
| `m.wait_pin("pin", True, timeout=60)` | wait until a pin has a value |
| `m.sleep(s)` | wait |
| `m.console("text", "info")` / `print(...)` | a line in the console (`info`, `warning`, `error`) |
| `m.args` | the numbers the macro was started with |

A refused call (a soft limit, a pin that cannot be set, the machine off) raises `MacroError`:
catch it to react, or let it end the macro — the console shows why.

### Limits

- **Not real-time.** A macro reacts within 10–50 ms and sets pins *now*, not at a line of a
  running program. Something that must happen at a point in a print belongs in the G-code
  (`M64` / `M62`, an M-code).
- **One macro at a time** (`.macro`, `.ngc` and `.py` together).
- **Who may:** editing macros is for admins (`macros.write`), running them for users
  (`macros.run`); the assistant may not write them. Uploaded programs never run Python — only
  files in `macros/`. There is no sandbox: a macro can do what the backend can, so only admins
  write them.

The `{ … }` Python blocks in a `.macro` file are not run (the console says so): write a `.py`
macro instead.
