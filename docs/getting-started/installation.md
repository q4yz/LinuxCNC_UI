# Installation

Run `install.sh` from a checkout of the repository on the LinuxCNC machine:

```bash
git clone https://github.com/q4yz/LinuxCNC_UI.git
cd LinuxCNC_UI
sudo ./install.sh                  # builds the checked-out commit on the board (needs ~2 GB RAM)
sudo ./install.sh --release        # latest GitHub release, prebuilt UI — for 1 GB boards (BTT CB1)
sudo ./install.sh --release v1.2.0 # a specific release
```

On a 1 GB board (BTT CB1) use `--release`: building the UI (`vite build`) needs more memory
than the board has.

## HAL components

The generated HAL files load components from the
[Remora-m8p](https://github.com/q4yz/Remora-m8p) fork (`remora-spi`, `PIDcontroller`,
`extruder`, …). `install.sh` builds them once; after an update of the fork, or when a
generated machine needs a new one, run:

```bash
sudo bash scripts/install_hal_components.sh             # all components
sudo bash scripts/install_hal_components.sh extruder    # only these
```

Without them LinuxCNC stops at the first `loadrt` with *cannot open shared object file*. See
{doc}`../hardware/remora-components`.

## Installing a CI build

Every CI run (not only releases) has a `linuxcnc-ui-dist` artifact with the prebuilt UI. To
install one over SSH (a token that can read the repository's Actions is needed):

```bash
ssh pi@cb1 "GITHUB_TOKEN=<token> bash -s -- <artifact-url>" < scripts/install_artifact.sh
```

A first install (or `--full`) needs a terminal for the `sudo` password: copy the script over
first and run it with `ssh -t`.

## Starting

With the machine configured (see {doc}`first-machine`), start LinuxCNC with the machine's INI:

```bash
linuxcnc <path>/machine.ini
```

Open `http://<machine-ip>` in a browser.
