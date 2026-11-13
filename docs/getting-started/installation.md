# Installation

The quickest way: a ready-made SD card image with LinuxCNC, the UI and everything set up.

:::{admonition} Placeholder
:class: warning
Download link for the image and the supported host boards (BTT CB1, Raspberry Pi 4 / 5) — to
be added.
:::

## 1. Write the image to an SD card

1. Download the image: *(placeholder: link)*.
2. Write it to a microSD card (8 GB or more) with [Rufus](https://rufus.ie),
   [balenaEtcher](https://etcher.balena.io) or
   [Raspberry Pi Imager](https://www.raspberrypi.com/software/) (*Use custom*).
3. Put the card into the host board (the CB1 on the M8P, or the Raspberry Pi).

## 2. Put the firmware on the Remora board

1. Get `firmware.bin` for your board from the
   [Remora-m8p repository](https://github.com/q4yz/Remora-m8p) *(placeholder: release /
   download link per board)*.
2. Copy it onto the **board's own** SD card (not the host's) and power the board: the
   bootloader flashes it.

Later updates of the firmware can be flashed from the UI: put `firmware.bin` into the machine's
folder on the Config page and use **Upload to board**.

## 3. Start and log in

Power everything on. The host boots LinuxCNC and the UI. On a console (HDMI and keyboard, or
SSH) the login is:

| User | Password |
|------|----------|
| `remora` | `remora` |

Change the password after the first login: `passwd`.

## 4. Open the UI

In a browser on the same network open `http://<host-ip>` — the IP is shown by your router, or
on the host with `hostname -I`. Install it as an app from the browser menu if you like.

## 5. Update

On the **Config** page press **Install latest release** in the *System Update* card, so the UI
is current before you configure the machine.

Next: {doc}`wiring`, then {doc}`config`. Installing on your own LinuxCNC system instead?
See {doc}`install-from-repo`.
