# LinuxCNC Web UI

A web-based operator interface for [LinuxCNC](https://linuxcnc.org): DRO, jogging, homing,
program execution, macros, heaters, probing and bed levelling in the browser — on the machine
itself, a tablet next to it or any computer on the network. Built for 3D printers and CNC
machines driven by [Remora](https://github.com/q4yz/Remora-m8p) boards, configured with
Klipper-style `.cfg` files.

![Dashboard](../images/dashboard.png)

These pages are built from the `docs/` folder of the
[LinuxCNC_UI repository](https://github.com/q4yz/LinuxCNC_UI): pick the version matching your
installation in the version menu, and use *Edit on GitHub* to improve a page.

```{toctree}
:maxdepth: 2
:caption: Getting Started

getting-started/introduction
getting-started/installation
getting-started/updating
getting-started/first-machine
```

```{toctree}
:maxdepth: 2
:caption: Machine Configuration

configuration/overview
configuration/steppers
configuration/heaters-extruder
configuration/probe
configuration/levelling
configuration/fans-leds
```

```{toctree}
:maxdepth: 2
:caption: Using the UI

using/dashboard
using/jogging
using/console-commands
using/programs
using/hal-tools
```

```{toctree}
:maxdepth: 2
:caption: Hardware

hardware/remora-components
```

```{toctree}
:maxdepth: 2
:caption: Reference

reference/troubleshooting
reference/writing-docs
```
