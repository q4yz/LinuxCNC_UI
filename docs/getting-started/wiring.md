# Hardware wiring

:::{admonition} Placeholder
:class: warning
Wiring diagrams are to be added: the images below are placeholders.
:::

## BTT Manta M8P with CB1

The CB1 sits on the M8P and talks to it over SPI — no wiring between them.

*(placeholder image: M8P overview with the main connections drawn — power, motors, endstops,
heaters, thermistors, fans, CAN)*

*(placeholder image: CB1 mounted on the M8P)*

| Connection | Where | Notes |
|------------|-------|-------|
| Power | *(placeholder)* | |
| Stepper motors | *(placeholder)* | |
| Endstops | *(placeholder)* | |
| Heaters, thermistors | *(placeholder)* | |
| Fans | *(placeholder)* | |
| CAN to the toolhead | *(placeholder)* | 120 Ω termination at both ends |

## BTT Octopus with a Raspberry Pi

The Pi talks to the Octopus over SPI: *(placeholder: which header pins, the cable)*.

*(placeholder image: Octopus and Raspberry Pi with the SPI connection)*

Next: {doc}`config`.
