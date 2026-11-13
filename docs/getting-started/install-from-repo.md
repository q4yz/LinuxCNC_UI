# Install from the repository

On an existing LinuxCNC installation (Debian with LinuxCNC 2.9), install from a checkout:

```bash
git clone https://github.com/q4yz/LinuxCNC_UI.git
cd LinuxCNC_UI
sudo ./install.sh                  # builds the checked-out commit on the board (needs ~2 GB RAM)
sudo ./install.sh --release        # latest GitHub release, prebuilt UI — for 1 GB boards (BTT CB1)
sudo ./install.sh --release v1.2.0 # a specific release
```

`install.sh` also builds the Remora HAL components ({doc}`../architecture/remora-components`).

## Updating

The *System Update* card on the Config page:

Build newest commit
: `git pull` on the current branch, then build the UI on the board (~2 GB RAM).

Install latest release
: Check out the latest release and download its prebuilt UI — nothing is compiled.

By hand, as the normal user (never with `sudo`):

```bash
scripts/update.sh --mode commit
scripts/update.sh --mode release [--tag v1.2.0]
```

After an update: rebuild the HAL components when `update.sh` says the Remora fork has new
commits (`sudo bash scripts/install_hal_components.sh`), generate the machine again when the
release asks for it ({doc}`compile`), and restart LinuxCNC.

## Installing a CI build

Every CI run has a `linuxcnc-ui-dist` artifact with the prebuilt UI:

```bash
ssh pi@cb1 "GITHUB_TOKEN=<token> bash -s -- <artifact-url>" < scripts/install_artifact.sh
```

The token must be able to read the repository's Actions. A first install (or `--full`) needs a
terminal for the `sudo` password: copy the script over and run it with `ssh -t`.
