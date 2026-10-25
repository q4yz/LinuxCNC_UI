#!/bin/bash
set -e # Exit immediately if a command fails

# Usage:
#   sudo ./install.sh                    build the checked-out commit on this board
#   sudo ./install.sh --release [vX.Y.Z] install a GitHub release (latest if no tag):
#                                        prebuilt frontend, no Node.js / npm / vite —
#                                        for 1 GB boards like the BTT CB1
RELEASE_MODE=0
RELEASE_TAG=""
if [ "$1" = "--release" ]; then
  RELEASE_MODE=1
  RELEASE_TAG="$2"
fi

# Ensure the script is run with sudo
if [ "$EUID" -ne 0 ]; then
  echo "Please run this script with sudo: sudo ./install.sh"
  exit 1
fi

# Get the original user who ran sudo (so we don't create venv as root)
REAL_USER=${SUDO_USER:-$USER}
REAL_GROUP=$(id -gn "$REAL_USER")
REAL_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)
PROJECT_DIR=$(pwd)
CERT_DIR="$PROJECT_DIR/frontend/.cert"
UI_DIST_DIR="$PROJECT_DIR/frontend/dist"

echo "=========================================="
echo " Starting LinuxCNC UI Installation"
echo " User: $REAL_USER"
echo " Project Dir: $PROJECT_DIR"
echo "=========================================="

# 0. Nothing in the project tree may belong to root.
#
# scripts/update.sh runs as $REAL_USER and must be able to overwrite
# every project file without sudo. Only /etc (systemd units, nginx,
# sudoers) is root-owned; everything below $PROJECT_DIR is written by
# `sudo -u "$REAL_USER"`. This repairs trees left behind by an earlier
# install or a hand-run `sudo` command.
echo -e "\n---> Making sure the project tree belongs to $REAL_USER..."
find "$PROJECT_DIR" -xdev -user root -exec chown -h "$REAL_USER:$REAL_GROUP" {} +

# 1. Update and install core system packages
echo -e "\n---> Installing system dependencies..."
apt-get update
# fonts-noto-color-emoji: the browser on the machine's own screen has no
# emoji font otherwise — user-typed emojis (e.g. macro button icons)
# would show as blank boxes. The UI's own icons are SVG and need none.
apt-get install -y curl wget git nginx python3-venv mkcert libnss3-tools ustreamer fonts-noto-color-emoji

# 1b. Release install: check out the release tag and fetch its
# prebuilt frontend now, so the venv below gets that tag's requirements.
if [ "$RELEASE_MODE" -eq 1 ]; then
    echo -e "\n---> Fetching release ${RELEASE_TAG:-(latest)}..."
    RELEASE_TAG=$(sudo -u "$REAL_USER" python3 "$PROJECT_DIR/scripts/fetch_release.py" tag $RELEASE_TAG)
    RELEASE_WORK=$(sudo -u "$REAL_USER" mktemp -d)
    RELEASE_TARBALL=$(sudo -u "$REAL_USER" python3 "$PROJECT_DIR/scripts/fetch_release.py" download "$RELEASE_TAG" "$RELEASE_WORK")
    sudo -u "$REAL_USER" git -C "$PROJECT_DIR" fetch --force --tags origin
    CURRENT_BRANCH=$(sudo -u "$REAL_USER" git -C "$PROJECT_DIR" symbolic-ref --short -q HEAD || true)
    if [ -n "$CURRENT_BRANCH" ]; then
        # "Build newest commit" returns to this branch later (scripts/update.sh).
        sudo -u "$REAL_USER" mkdir -p "$PROJECT_DIR/backend/data"
        echo "$CURRENT_BRANCH" | sudo -u "$REAL_USER" tee "$PROJECT_DIR/backend/data/update_branch" > /dev/null
    fi
    sudo -u "$REAL_USER" git -C "$PROJECT_DIR" checkout --detach "refs/tags/$RELEASE_TAG"
    echo "Installing release $RELEASE_TAG"
fi

# 1c. LinuxCNC HAL components (remora-spi, remora_lpc, PIDcontroller,
# rpi-monitor, ...) — built from the Remora-m8p fork
# (github.com/q4yz/Remora-m8p, LinuxCNC/Components, main branch).
# machine.hal loadrt's them; without the .so
# LinuxCNC stops at "dlopen: .../remora-spi.so: cannot open shared object
# file". Not fatal here — the UI installs fine without them, and the
# script can be re-run by hand: sudo bash scripts/install_hal_components.sh
echo -e "\n---> Compiling and installing LinuxCNC HAL components..."
if ! bash "$PROJECT_DIR/scripts/install_hal_components.sh"; then
    echo "WARNING: not every HAL component installed (see above). Re-run: sudo bash $PROJECT_DIR/scripts/install_hal_components.sh" >&2
fi

# 2. Install Node.js (LTS version) — not needed for a release install
echo -e "\n---> Installing Node.js..."
if [ "$RELEASE_MODE" -eq 1 ]; then
    echo "Release install: prebuilt frontend, Node.js not needed."
elif ! command -v node >/dev/null 2>&1; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y nodejs
else
    echo "Node.js is already installed."
fi

# 3. Set up the Python Backend Virtual Environment
#
# One venv shared by both services (backend/machine and
# backend/system) — see .agent/context/ARCHITECTURE.md for why the
# backend is split into two processes. Each service's own
# requirements file (today identical; they'll diverge if a
# service-only dependency shows up) is installed into it.
echo -e "\n---> Setting up Python virtual environment (with system-site-packages)..."
cd "$PROJECT_DIR/backend"
sudo -u "$REAL_USER" python3 -m venv venv --system-site-packages
if [ -f "requirements-machine.txt" ] && [ -f "requirements-system.txt" ]; then
    sudo -u "$REAL_USER" ./venv/bin/pip install -r requirements-machine.txt -r requirements-system.txt
elif [ -f "requirements.txt" ]; then
    sudo -u "$REAL_USER" ./venv/bin/pip install -r requirements.txt
fi

if [ "$RELEASE_MODE" -eq 1 ]; then
    # 4. Release install: unpack the frontend CI built for this tag.
    echo -e "\n---> Installing prebuilt frontend ($RELEASE_TAG)..."
    sudo -u "$REAL_USER" rm -rf "$UI_DIST_DIR"
    sudo -u "$REAL_USER" mkdir -p "$UI_DIST_DIR"
    sudo -u "$REAL_USER" tar -xzf "$RELEASE_TARBALL" -C "$UI_DIST_DIR"
    rm -rf "$RELEASE_WORK"
else
    # 4. Set up the Frontend and Build
    #
    # The typed API client is generated from BOTH services' merged
    # OpenAPI schema. backend/dump_openapi.py reads each app's schema
    # in-process (same as rebuild_ui.sh and CI) — no temporary servers.
    echo -e "\n---> Installing Frontend dependencies and building production app..."
    cd "$PROJECT_DIR/frontend"
    sudo -u "$REAL_USER" npm install

    echo "Generating API client..."
    SCHEMA_DIR=$(sudo -u "$REAL_USER" mktemp -d)
    sudo -u "$REAL_USER" "$PROJECT_DIR/backend/venv/bin/python" "$PROJECT_DIR/backend/dump_openapi.py" machine "$SCHEMA_DIR/machine.json"
    sudo -u "$REAL_USER" "$PROJECT_DIR/backend/venv/bin/python" "$PROJECT_DIR/backend/dump_openapi.py" system "$SCHEMA_DIR/system.json"
    sudo -u "$REAL_USER" env OPENAPI_FILE="$SCHEMA_DIR/machine.json" OPENAPI_FILE_SYSTEM="$SCHEMA_DIR/system.json" npm run generate-api
    rm -rf "$SCHEMA_DIR"

    echo "Building Vite application..."
    sudo -u "$REAL_USER" npm run build
fi

# 5. Set up mkcert and the Root CA
echo -e "\n---> Configuring local Certificate Authority..."
sudo -u "$REAL_USER" mkcert -install

# Locate the generated Root CA
CA_ROOT="$REAL_HOME/.local/share/mkcert/rootCA.pem"

echo -e "\n---> Copying Root CA for the Vue frontend..."
# Copy it directly into the built Vue files so your popup can link to "/cnc-root.crt".
# As the user (not root): a root-owned file here could not be replaced by
# rebuild_ui.sh during a non-root update.
sudo -u "$REAL_USER" cp "$CA_ROOT" "$UI_DIST_DIR/cnc-root.crt"
sudo -u "$REAL_USER" chmod 644 "$UI_DIST_DIR/cnc-root.crt"

# 6. Generate the initial SSL Certificate
echo -e "\n---> Generating initial SSL certificate..."
sudo -u "$REAL_USER" mkdir -p "$CERT_DIR"
cd "$CERT_DIR"
ALL_IPS=$(hostname -I)
sudo -u "$REAL_USER" mkcert -cert-file localhost.pem -key-file localhost-key.pem localhost 127.0.0.1 $ALL_IPS

# 7. Configure Camera Service (ustreamer)
echo -e "\n---> Configuring uStreamer (USB Camera) service..."
USTREAMER_SERVICE="/etc/systemd/system/ustreamer.service"
cat << EOF > "$USTREAMER_SERVICE"
[Unit]
Description=uStreamer for CNC Camera
After=network.target

[Service]
Type=simple
User=$REAL_USER
ExecStart=/usr/bin/ustreamer --device /dev/video0 --host 127.0.0.1 --port 8081 --resolution 1280x720 --desired-fps 15
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable ustreamer
systemctl restart ustreamer

# 7b. Configure the system backend service (machine + system split —
# see .agent/context/ARCHITECTURE.md). ONLY the system service (:8001)
# is a systemd unit: it owns every config/CRUD domain and must always
# be reachable, even while the machine backend or LinuxCNC itself is
# down. The machine backend (:8000) is deliberately NOT a unit — it is
# a program that gets started and shut off by the system service, like
# the LinuxCNC session it drives. Nginx (below) routes each path
# prefix to the service that owns it.
echo -e "\n---> Configuring backend services (system :8001 unit; machine :8000 is spawned by the system service)..."



SYSTEM_SERVICE="/etc/systemd/system/linuxcnc-ui-system.service"
cat << EOF > "$SYSTEM_SERVICE"
[Unit]
Description=LinuxCNC UI System Service (machine config, programs, macros, lifecycle — port 8001)
After=network.target

[Service]
Type=simple
User=$REAL_USER
WorkingDirectory=$PROJECT_DIR/backend/system
ExecStart=$PROJECT_DIR/backend/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8001
Restart=always
RestartSec=5
LimitMEMLOCK=infinity
# MachineLifecycleService spawns the LinuxCNC GUI, which needs a
# display; it already defaults to :0 if DISPLAY is unset, but a
# systemd unit has no environment of its own, so make it explicit.
Environment=DISPLAY=:0
KillMode=process

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable linuxcnc-ui-system
systemctl restart linuxcnc-ui-system

# 7c. Boot-time TLS certificate renewal.
#
# DHCP boxes get a new IP on every boot; an mkcert certificate that
# does not list the current IP makes browsers reject the HTTPS UI.
# start_network.sh re-mints the certificate for the current IPs and
# reloads nginx (passwordless via the sudoers rule in section 10), so
# run it as a oneshot on every boot once the network is up. Section 6
# already minted the initial certificate during this install — this
# unit keeps it fresh afterwards.
echo -e "\n---> Configuring boot-time certificate renewal (linuxcnc-ui-cert)..."
CERT_SERVICE="/etc/systemd/system/linuxcnc-ui-cert.service"
cat << EOF > "$CERT_SERVICE"
[Unit]
Description=LinuxCNC UI - re-mint TLS certificate for current IPs (start_network.sh)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$REAL_USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$PROJECT_DIR/start_network.sh

[Install]
WantedBy=multi-user.target
EOF

sudo -u "$REAL_USER" chmod +x "$PROJECT_DIR/start_network.sh"
systemctl daemon-reload
systemctl enable linuxcnc-ui-cert

# 8. Fix Directory Permissions for Nginx
echo -e "\n---> Fixing directory permissions so Nginx can serve files..."
# Nginx (www-data user) needs traverse (execute) permissions up the entire directory tree
chmod 755 "$REAL_HOME"
chmod 755 "$PROJECT_DIR"
sudo -u "$REAL_USER" chmod -R 755 "$UI_DIST_DIR"

# 9. Configure Nginx
# The site file only carries ports/TLS/paths; every route lives in the
# tracked deploy/nginx/linuxcnc-ui-routes.conf (included), so updates
# apply new routes with a plain nginx reload.
echo -e "\n---> Configuring Nginx..."
bash "$PROJECT_DIR/scripts/configure_nginx.sh"

# 10. Configure sudoers for passwordless service management
#
# scripts/update.sh runs as $REAL_USER (not root) and needs to
# restart the system unit after pulling new code; start_network.sh
# (boot-time cert renewal) needs the nginx reload.
echo -e "\n---> Configuring passwordless service management for $REAL_USER..."
SUDOERS_FILE="/etc/sudoers.d/linuxcnc-ui"
# Superseded by the consolidated rule below (re-running install.sh
# on an already-installed machine would otherwise leave this stale).
rm -f "/etc/sudoers.d/linuxcnc-nginx-reload"

cat << EOF > "$SUDOERS_FILE"
$REAL_USER ALL=(ALL) NOPASSWD: /bin/systemctl reload nginx
$REAL_USER ALL=(ALL) NOPASSWD: /bin/systemctl restart linuxcnc-ui-system*
$REAL_USER ALL=(ALL) NOPASSWD: /bin/systemctl stop linuxcnc-ui-system*
$REAL_USER ALL=(ALL) NOPASSWD: /bin/systemctl start linuxcnc-ui-system*
$REAL_USER ALL=(ALL) NOPASSWD: /bin/systemctl daemon-reload
EOF

# Sudoers files must have strict permissions or the system will ignore them
chmod 0440 "$SUDOERS_FILE"

# Grab just the first IP address for a clean display output
DISPLAY_IP=$(echo $ALL_IPS | awk '{print $1}')


echo -e "\n---> Configuring boot-time certificate renewal (linuxcnc-ui-cert)..."
CERT_SERVICE="/etc/systemd/system/linuxcnc-ui-cert.service"
cat << EOF > "$CERT_SERVICE"
[Unit]
Description=LinuxCNC UI - re-mint TLS certificate for current IPs (start_network.sh)
After=network-online.target time-sync.target
Wants=network-online.target time-sync.target

[Service]
Type=oneshot
User=$REAL_USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$PROJECT_DIR/start_network.sh

[Install]
WantedBy=multi-user.target
EOF

sudo -u "$REAL_USER" chmod +x "$PROJECT_DIR/start_network.sh"
systemctl daemon-reload
systemctl enable linuxcnc-ui-cert

# Final check: nothing above may have left a root-owned file in the tree.
find "$PROJECT_DIR" -xdev -user root -exec chown -h "$REAL_USER:$REAL_GROUP" {} +

echo "=========================================="
echo " Installation Complete!"
echo " "
echo " App (HTTP Popup):   http://$DISPLAY_IP"
echo " App (HTTPS Secure): https://$DISPLAY_IP"
echo "=========================================="