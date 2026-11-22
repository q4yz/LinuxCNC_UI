# Installation

The quickest way: a ready-made SD card image with LinuxCNC, the UI and everything set up.

## 1. Write the image to an SD card

1. Download the image for your host board from the
   **[latest image release](https://github.com/q4yz/LinuxCNC_UI-images/releases/latest)**
   ([all releases](https://github.com/q4yz/LinuxCNC_UI-images/releases),
   [build scripts](https://github.com/q4yz/LinuxCNC_UI-images)):

   | Host board | Image file (`.img.xz`) contains |
   |---|---|
   | BigTreeTech CB1 (e.g. on a Manta M8P) | `Bigtreetech-cb1` |
   | Raspberry Pi 3 / 4 / 400 / 5, CM4 / CM5 (one image for all) | `Rpi4b` |

   Each image has a `.sha` file next to it with its SHA-256 checksum.
2. Write the `.img.xz` to a microSD card (8 GB or more) with
   [balenaEtcher](https://etcher.balena.io),
   [Raspberry Pi Imager](https://www.raspberrypi.com/software/) (*Use custom*) or
   [Rufus](https://rufus.ie) (DD mode). No need to unpack it first.
3. Put the card into the host board (the CB1 on the M8P, or the Raspberry Pi).

What is on the image: Armbian (Debian 13) with a PREEMPT_RT kernel (6.18.64), LinuxCNC 2.9.4,
LinuxCNC UI (prebuilt) and the Remora HAL components (`remora-spi` and the others).

:::{admonition} Not yet tested on hardware
:class: warning
Both images were checked file by file but have not been booted on hardware yet. The Raspberry
Pi image is new and untested on a Pi. Please report what you find.
:::

:::{admonition} A specific version: v1.0.0 direct downloads
:class: note
Use these only when you want exactly v1.0.0; the file names change with every release (they
contain the kernel version), so link the release page otherwise.

- BigTreeTech CB1:
  [image](https://github.com/q4yz/LinuxCNC_UI-images/releases/download/v1.0.0/Armbian-unofficial_26.11.0-trunk_Bigtreetech-cb1_trixie_current_6.18.64_xfce_desktop.img.xz),
  [SHA-256](https://github.com/q4yz/LinuxCNC_UI-images/releases/download/v1.0.0/Armbian-unofficial_26.11.0-trunk_Bigtreetech-cb1_trixie_current_6.18.64_xfce_desktop.img.xz.sha)
- Raspberry Pi 3 / 4 / 400 / 5 / CM4 / CM5:
  [image](https://github.com/q4yz/LinuxCNC_UI-images/releases/download/v1.0.0/Armbian-unofficial_26.11.0-trunk_Rpi4b_trixie_current_6.18.64_xfce_desktop.img.xz),
  [SHA-256](https://github.com/q4yz/LinuxCNC_UI-images/releases/download/v1.0.0/Armbian-unofficial_26.11.0-trunk_Rpi4b_trixie_current_6.18.64_xfce_desktop.img.xz.sha)

Release page: [v1.0.0](https://github.com/q4yz/LinuxCNC_UI-images/releases/tag/v1.0.0). It
contains LinuxCNC UI at commit `ec1ee6f`; update it from the UI after the first start (step 5).
:::

## 2. Put the firmware on the Remora board

1. Get `firmware.bin` for your board from the
   [Remora-m8p repository](https://github.com/q4yz/Remora-m8p) *(placeholder: release /
   download link per board)*.
2. Copy it onto the **board's own** SD card (not the host's) and power the board: the
   bootloader flashes it.

Later updates of the firmware can be flashed from the UI: put `firmware.bin` into the machine's
folder on the Config page and use **Upload to board**.

## 3. Start and log in

Power everything on. The host boots LinuxCNC and the UI. On a console (HDMI and keyboard) or
over SSH (`ssh remora@remora.local`) the login is:

| User | Password |
|------|----------|
| `remora` | `remora` |
| `root` | `remora` |

Change both passwords after the first login: `passwd` (and `sudo passwd root`).

## 4. Open the UI

In a browser on the same network open **<http://remora.local>**. If that name does not resolve
on your network, use `http://<host-ip>` — the IP is shown by your router, or on the host with
`hostname -I`. Install it as an app from the browser menu if you like.

## 5. Update

On the **Config** page press **Install latest release** in the *System Update* card, so the UI
is current before you configure the machine.

Next: {doc}`wiring`, then {doc}`config`. Installing on your own LinuxCNC system instead?
See {doc}`install-from-repo`.
