# Updating

The **System Update** card has two buttons:

Build newest commit
: `git pull` on the current branch, then build the UI on the board. For testing; needs ~2 GB
  RAM.

Install latest release
: Check out the latest release tag and download its prebuilt UI. Nothing is compiled on the
  board — the way to update a 1 GB board.

By hand, always as the normal user (never with `sudo`):

```bash
scripts/update.sh --mode commit
scripts/update.sh --mode release [--tag v1.2.0]
```

After an update:

- **Regenerate the machine** when the release notes say the generated files changed (new HAL
  wiring, new INI keys) — the Config page, *Generate*.
- **Rebuild the HAL components** when `update.sh` reports new Remora-m8p commits:
  `sudo bash scripts/install_hal_components.sh`.
- **Restart LinuxCNC** — the INI, HAL files and user M-codes are only read at start.
