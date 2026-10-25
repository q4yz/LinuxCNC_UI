#!/bin/bash
# Compile and install the LinuxCNC HAL components from the Remora fork
# (https://github.com/q4yz/Remora-m8p, LinuxCNC/Components) into
# LinuxCNC's module directory, so `loadrt remora-spi` etc. in the
# generated machine.hal find their .so. Run as root — the module
# directory belongs to root:
#
#   sudo bash scripts/install_hal_components.sh              # all components
#   sudo bash scripts/install_hal_components.sh remora-spi   # only these
#
# The newest commit of the fork's main branch is built (it only gets bug
# fixes). Override with REMORA_REPO=<git url> / REMORA_REF=<branch|tag>.
# The source is cloned to a temp dir — nothing is written to this repo.
#
# install.sh runs this once. Updates run as the normal user and cannot
# write the module directory; scripts/update.sh says when the fork has
# new commits and this needs a re-run.
#
# Without it LinuxCNC stops at the first loadrt:
#   remora-spi: dlopen: /usr/lib/linuxcnc/modules/remora-spi.so: cannot open shared object file
set -e

if [ "$EUID" -ne 0 ]; then
    echo "Error: run as root (sudo bash $0)" >&2
    exit 1
fi

REMORA_REPO="${REMORA_REPO:-https://github.com/q4yz/Remora-m8p.git}"
REMORA_REF="${REMORA_REF:-main}"
# Which fork commit is installed — scripts/update.sh compares it with the
# fork's current main to tell the operator a re-run is due.
STATE_FILE="/var/lib/linuxcnc-ui/hal-components.commit"
# Userspace Python components (loadusr) go on PATH under these names.
USER_BIN_DIR="/usr/local/bin"

# module name -> source below LinuxCNC/Components. The module name is
# what machine.hal loadrt's (= the source's file name). Each source's
# own folder is on halcompile's include path, so remora-spi.c's
# `#include "bcm2835.c"` etc. resolve.
# Not built: Extruder/Extruder.c (a .comp source, unfinished), Heater/
# (empty), Compensation/ (an NGC/Python tool, not a HAL module).
declare -A SOURCES=(
    [remora-spi]="Remora-spi/remora-spi.c"
    [remora-eth-3.0]="Remora-eth/remora-eth-3.0.c"
    [remora_lpc]="Remora/remora_lpc.c"
    [PIDcontroller]="PIDcontroller/PIDcontroller.c"
    [nvmpg]="NVMPG/nvmpg.c"
    [PRUencoder]="PRUencoder/PRUencoder.c"
    [rpi-monitor]="RPiMonitor/rpi_monitor.py"
)
ALL=(remora-spi remora-eth-3.0 remora_lpc PIDcontroller nvmpg PRUencoder rpi-monitor)

if [ $# -gt 0 ]; then
    SELECTED=("$@")
else
    SELECTED=("${ALL[@]}")
fi
for name in "${SELECTED[@]}"; do
    if [ -z "${SOURCES[$name]}" ]; then
        echo "Error: unknown component '$name' (known: ${ALL[*]})" >&2
        exit 2
    fi
done

# halcompile ships in linuxcnc-uspace-dev; the Remora drivers' bcm2835
# code needs libcap's <sys/capability.h>.
if ! command -v halcompile >/dev/null 2>&1 || ! command -v git >/dev/null 2>&1 \
        || ! dpkg -s libcap-dev >/dev/null 2>&1; then
    echo "---> Installing build dependencies (linuxcnc-uspace-dev, libcap-dev, build-essential, git)..."
    apt-get update
    apt-get install -y linuxcnc-uspace-dev libcap-dev build-essential git
fi

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT
echo "---> Fetching $REMORA_REPO ($REMORA_REF)..."
git clone --quiet --depth 1 --branch "$REMORA_REF" "$REMORA_REPO" "$WORK_DIR/remora"
COMMIT="$(git -C "$WORK_DIR/remora" rev-parse HEAD)"
COMPONENTS_DIR="$WORK_DIR/remora/LinuxCNC/Components"
echo "Building from commit ${COMMIT:0:12}"

INSTALLED=()
FAILED=()
cd "$COMPONENTS_DIR"
for name in "${SELECTED[@]}"; do
    src="${SOURCES[$name]}"
    echo -e "\n---> $name ($src)"
    if [[ "$src" == *.py ]]; then
        # Userspace component: loadusr -Wn rpi-monitor rpi-monitor
        if install -m 0755 "$src" "$USER_BIN_DIR/$name"; then
            INSTALLED+=("$name")
        else
            FAILED+=("$name")
        fi
    elif halcompile --install "$src"; then
        INSTALLED+=("$name")
    else
        FAILED+=("$name")
    fi
done

# Only a complete run counts as "this commit is installed".
if [ ${#FAILED[@]} -eq 0 ] && [ $# -eq 0 ]; then
    mkdir -p "$(dirname "$STATE_FILE")"
    echo "$COMMIT" > "$STATE_FILE"
fi

MOTMOD=$(find /usr/lib/linuxcnc /usr/lib/*/linuxcnc -name 'motmod.so' 2>/dev/null | head -n 1 || true)
echo -e "\n=========================================="
echo " Remora-m8p commit:        ${COMMIT:0:12} ($REMORA_REF)"
echo " HAL components installed: ${INSTALLED[*]:-none}"
[ -n "$MOTMOD" ] && echo " Module directory:         $(dirname "$MOTMOD")"
if [ ${#FAILED[@]} -gt 0 ]; then
    echo " FAILED:                   ${FAILED[*]} (see the compiler output above)"
    echo "=========================================="
    exit 1
fi
echo "=========================================="
